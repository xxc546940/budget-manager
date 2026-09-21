"""Local web UI for the manual inputs, backed by the JSON config files.

A static HTML page cannot write to disk, so this serves the page from a tiny
stdlib HTTP server that owns the writes. Everything the UI saves lands in
config/*.json - the same files the CLI and skills read, hand-editable and
diffable.

Bound to 127.0.0.1 only. Writes additionally require a token minted at startup
and embedded in the page, so a random website you happen to have open cannot
POST to this port behind your back.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import config as cfgmod
from .schema import to_cents

HERE = Path(__file__).resolve().parent
INBOX = cfgmod.INBOX
TOKEN = secrets.token_urlsafe(24)

SECTIONS = {"income": "sources", "fixed": "expenses", "goals": "goals"}


def _clean_money(value) -> int:
    """UI sends dollars as typed; store cents."""
    if value in (None, ""):
        return 0
    try:
        return abs(to_cents(value))
    except ValueError:
        return 0


def _clean_date(value):
    if not value:
        return None
    try:
        date.fromisoformat(value)
        return value
    except (ValueError, TypeError):
        return None


def sanitize(section: str, rows: list) -> list:
    """Never trust the page. Coerce every field to the shape the analyzer expects."""
    out, seen = [], set()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).strip()
        if not name:
            continue
        rid = str(r.get("id") or "").strip() or cfgmod.slugify(name, seen)
        seen.add(rid)
        base = {"id": rid, "name": name,
                "note": str(r.get("note", ""))[:500],
                "effective_from": _clean_date(r.get("effective_from")),
                "effective_to": _clean_date(r.get("effective_to"))}
        if section == "income":
            cadence = r.get("cadence", "monthly")
            base.update({
                "net_monthly_cents": _clean_money(r.get("net_monthly")),
                "basis": "net",   # after-tax only; nothing else is accepted
                "cadence": cadence if cadence in cfgmod.PER_YEAR else "monthly",
                "account": str(r.get("account", "")).strip(),
                "match": str(r.get("match", "")).strip().lower(),
            })
        elif section == "fixed":
            cadence = r.get("cadence", "monthly")
            try:
                due = max(1, min(31, int(r.get("due_day") or 1)))
            except (TypeError, ValueError):
                due = 1
            base.update({
                "category": str(r.get("category", "Other")).strip() or "Other",
                "amount_cents": _clean_money(r.get("amount")),
                "cadence": cadence if cadence in cfgmod.PER_YEAR else "monthly",
                "due_day": due,
                "account": str(r.get("account", "")).strip(),
                "match": str(r.get("match", "")).strip().lower(),
                "variable": bool(r.get("variable")),
            })
        else:  # goals
            try:
                prio = int(r.get("priority") or 1)
            except (TypeError, ValueError):
                prio = 1
            kind = r.get("contribution_type", "auto")
            if kind not in ("percent", "fixed", "auto"):
                kind = "auto"
            try:
                pct = max(0.0, min(100.0, float(r.get("percent_of_net_income") or 0)))
            except (TypeError, ValueError):
                pct = 0.0
            gtype = r.get("goal_type")
            if gtype not in ("rate", "target"):
                gtype = "target" if _clean_money(r.get("target")) else "rate"
            base.update({
                "goal_type": gtype,
                "contribution_type": kind,
                "percent_of_net_income": pct if kind == "percent" else None,
                "contribution_fixed_cents": _clean_money(r.get("contribution_fixed")) if kind == "fixed" else 0,
                "target_cents": _clean_money(r.get("target")),
                "target_date": _clean_date(r.get("target_date")),
                "current_balance_cents": _clean_money(r.get("current_balance")),
                "balance_as_of": _clean_date(r.get("balance_as_of")),
                "account_match": str(r.get("account_match", "")).strip().lower(),
                "priority": prio,
                "active": bool(r.get("active", True)),
            })
            base.pop("effective_from", None)
            base.pop("effective_to", None)
        out.append(base)
    return out


def to_ui(section: str, rows: list) -> list:
    """Cents -> dollar strings for the form fields."""
    def d(c):
        return f"{(c or 0) / 100:.2f}"
    out = []
    for r in rows:
        r = dict(r)
        if section == "income":
            r["net_monthly"] = d(r.get("net_monthly_cents"))
        elif section == "fixed":
            r["amount"] = d(r.get("amount_cents"))
        else:
            r["target"] = d(r.get("target_cents"))
            r["current_balance"] = d(r.get("current_balance_cents"))
            r["contribution_fixed"] = d(r.get("contribution_fixed_cents"))
        out.append(r)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "budget-manager"

    def log_message(self, fmt, *args):   # quiet; this is a desktop tool
        pass

    # -------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, default=str).encode(), "application/json")

    def _local(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            return False
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
            return False
        return True

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 32 * 1024 * 1024:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------- routes
    def do_GET(self):
        if not self._local():
            return self._send(403, b"forbidden", "text/plain")
        route = urlparse(self.path).path
        if route == "/":
            html = (HERE / "ui.html").read_text().replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if route == "/api/config":
            return self._json(self._snapshot())
        if route == "/api/propose":
            from . import analyze, ledger
            conn = ledger.connect()
            return self._json(analyze.propose_budget(conn, cfgmod.load(), date.today(), months=3))
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._local() or self.headers.get("X-Budget-Token") != TOKEN:
            return self._send(403, b"forbidden", "text/plain")
        route = urlparse(self.path).path
        body = self._body()

        if route.startswith("/api/save/"):
            section = route.rsplit("/", 1)[-1]
            if section in SECTIONS:
                key = SECTIONS[section]
                data = cfgmod.read(section)
                data[key] = sanitize(section, body.get("rows", []))
                cfgmod.write(section, data)
                return self._json({"ok": True, "saved": len(data[key])})
            if section == "budget":
                data = cfgmod.read("budget")
                env = {}
                for k, v in (body.get("envelopes") or {}).items():
                    cents = _clean_money(v)
                    if cents:
                        env[str(k)[:40]] = cents
                data["envelopes_cents"] = env
                hh = body.get("household") or {}
                if hh.get("name"):
                    data.setdefault("household", {})["name"] = str(hh["name"])[:80]
                if isinstance(hh.get("members"), list):
                    data["household"]["members"] = [str(m)[:60] for m in hh["members"][:8]]
                cfgmod.write("budget", data)
                return self._json({"ok": True})
            return self._json({"error": "unknown section"}, 400)

        if route == "/api/upload":
            name = Path(str(body.get("name", "upload.csv"))).name
            if not name.lower().endswith((".csv", ".txt", ".tsv")):
                return self._json({"error": "only .csv, .txt and .tsv files"}, 400)
            try:
                raw = base64.b64decode(body.get("content", ""), validate=True)
            except Exception:
                return self._json({"error": "bad file encoding"}, 400)
            if len(raw) > 32 * 1024 * 1024:
                return self._json({"error": "file too large"}, 400)
            INBOX.mkdir(parents=True, exist_ok=True)
            (INBOX / name).write_bytes(raw)
            return self._json({"ok": True, "saved": name, "bytes": len(raw)})

        if route == "/api/ingest":
            from . import categorize as catmod, ledger
            from .parse import ParseError, sniff
            conn = ledger.connect()
            rules = catmod.load_rules()
            results = []
            files = sorted(p for p in INBOX.iterdir()
                           if p.is_file() and p.suffix.lower() in (".csv", ".txt", ".tsv")) \
                if INBOX.exists() else []
            known = ledger.sign_conventions(conn)
            for f in files:
                try:
                    det, txns = sniff(f, known_conventions=known)
                    catmod.categorize_all(txns, rules)
                    new, dupes = ledger.insert(conn, txns)
                    ledger.record_ingest(conn, f.name, det.account, len(txns), new, det.summary())
                    if det.sign_confident:
                        ledger.remember_format(conn, det.signature, det.sign_flipped, f.name)
                        known[det.signature] = det.sign_flipped
                    results.append({"file": f.name, "account": det.account, "rows": len(txns),
                                    "new": new, "duplicates": dupes,
                                    "uncategorized": sum(1 for t in txns if not t.category),
                                    "date_range": det.date_range,
                                    "sign_flipped": det.sign_flipped,
                                    "warnings": det.warnings})
                except ParseError as exc:
                    results.append({"file": f.name, "error": str(exc)})
            return self._json({"results": results, "status": self._status()})

        return self._send(404, b"not found", "text/plain")

    # -------------------------------------------------- data
    def _status(self) -> dict:
        from . import ledger
        try:
            return ledger.stats(ledger.connect())
        except Exception as exc:
            return {"error": str(exc)}

    def _snapshot(self) -> dict:
        cfg = cfgmod.load()
        return {
            "budget": cfgmod.read("budget"),
            "income": to_ui("income", cfg["income"]["sources"]),
            "fixed": to_ui("fixed", cfg["fixed"]["expenses"]),
            "goals": to_ui("goals", cfg["goals"]["goals"]),
            "derived": {
                "monthly_income_cents": cfgmod.monthly_income(cfg),
                "fixed_monthly_cents": cfgmod.fixed_monthly_total(cfg),
                "planned_savings_cents": cfgmod.planned_total(cfg),
            },
            "warnings": cfgmod.validate(cfg),
            "status": self._status(),
            "categories": __import__("budget.schema", fromlist=["CATEGORIES"]).CATEGORIES,
            "cadences": list(cfgmod.PER_YEAR),
        }


def serve(port: int = 8765, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Budget inputs UI: {url}")
    print("  Editing: config/income.json, fixed_expenses.json, goals.json, budget.json")
    print("  Local only. Ctrl-C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
