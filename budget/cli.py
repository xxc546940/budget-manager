"""Command-line surface. The skills in .claude/skills/ call these subcommands.

Every command supports --json so the agent can read structured output instead
of parsing prose.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import analyze, categorize as catmod, config as cfgmod, ledger
from .parse import ParseError, sniff
from .schema import fmt

ROOT = cfgmod.ROOT
INBOX = cfgmod.INBOX
ARCHIVE = cfgmod.ARCHIVE
REPORTS = cfgmod.REPORTS_DIR


DATA_SUFFIXES = (".csv", ".txt", ".tsv")


REPORT_ARCHIVE = "archive"


def _publish_report(html: str, kind: str, today) -> Path:
    """Write to reports/latest-<kind>.html, archiving whatever was there.

    The mailer reads a fixed filename, so generating a report has to leave the
    newest one at a predictable path. The previous copy is moved aside rather
    than overwritten, keeping a history without the mailer ever having to guess
    which dated file is current.
    """
    REPORTS.mkdir(parents=True, exist_ok=True)
    archive = REPORTS / REPORT_ARCHIVE
    archive.mkdir(parents=True, exist_ok=True)
    latest = REPORTS / f"latest-{kind}.html"

    if latest.exists():
        stamp = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
        dest = archive / f"{kind}-{stamp}.html"
        n = 2
        while dest.exists():
            dest = archive / f"{kind}-{stamp}-{n}.html"
            n += 1
        shutil.move(str(latest), dest)

    latest.write_text(html)
    return latest


def _coverage_gap(conn, account: str, txns) -> dict | None:
    """Days between what is stored for this account and what the file starts at.

    Exports default to a short recent window, so downloading "last 7 days" a
    fortnight later leaves a hole that nothing else will ever reveal - the
    missing days just look like days without spending. Each upload should
    overlap the last one.
    """
    if not txns:
        return None
    _, stored_last = ledger.account_span(conn, account)
    if stored_last is None:
        return None                     # first upload for this account
    new_first = min(t.date for t in txns)
    missing = (new_first - stored_last).days - 1
    if missing <= 0:
        return None                     # overlapping or contiguous
    return {"account": account, "stored_through": stored_last.isoformat(),
            "file_starts": new_first.isoformat(), "missing_days": missing}


def _archive_name(path: Path, account: str) -> Path:
    """A non-colliding destination in the archive.

    Banks reuse export filenames: two people's Discover downloads are both
    'Discover-RecentActivity-20260920.csv', and a plain move silently destroys
    the first one. The account label disambiguates, then a counter if needed.
    """
    dest = ARCHIVE / path.name
    if not dest.exists():
        return dest
    stem, suffix = path.stem, path.suffix
    candidate = ARCHIVE / f"{stem}__{account}{suffix}"
    n = 2
    while candidate.exists():
        candidate = ARCHIVE / f"{stem}__{account}-{n}{suffix}"
        n += 1
    return candidate


def _inbox_files() -> list[Path]:
    if not INBOX.exists():
        return []
    return sorted(p for p in INBOX.iterdir()
                  if p.is_file() and p.suffix.lower() in DATA_SUFFIXES)


def _inbox_files_names() -> list[str]:
    return [p.name for p in _inbox_files()]


def _out(data, as_json: bool, text_fn=None):
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    elif text_fn:
        text_fn(data)
    return 0


# ---------------------------------------------------------------- ingest


def cmd_ingest(args) -> int:
    paths = [Path(p) for p in args.paths] if args.paths else _inbox_files()
    if not paths:
        print(f"No files. Drop bank CSVs into {INBOX}/ or pass paths explicitly.")
        return 1

    conn = ledger.connect()
    rules = catmod.load_rules()
    known = ledger.sign_conventions(conn)
    results = []

    for p in paths:
        try:
            flip = None if args.flip is None else args.flip
            det, txns = sniff(p, account=args.account, sign_flipped=flip,
                              known_conventions=known)
        except ParseError as e:
            results.append({"file": p.name, "error": str(e)})
            print(f"\n{p.name}\n  FAILED: {e}", file=sys.stderr)
            continue

        catmod.categorize_all(txns, rules)
        uncat = sum(1 for t in txns if not t.category)
        gap = _coverage_gap(conn, det.account, txns)

        if args.dry_run:
            print(f"\n{p.name}  [dry run]")
            print(det.summary())
            if gap:
                print(f"  ! GAP: {det.account} is stored through {gap['stored_through']} but "
                      f"this file starts {gap['file_starts']}")
                print(f"    {gap['missing_days']} day(s) in between will be missing for good. "
                      f"Re-export with an overlapping start date.")
            print(f"  uncategorized: {uncat}/{len(txns)}")
            for t in txns[:8]:
                print(f"    {t.date}  {fmt(t.amount_cents, sign=True):>12}  "
                      f"{(t.category or '?'):<14} {t.description[:44]}")
            results.append({"file": p.name, "dry_run": True, "rows": len(txns),
                            "detection": det.summary()})
            continue

        new, dupes = ledger.insert(conn, txns)
        ledger.record_ingest(conn, p.name, det.account, len(txns), new, det.summary())
        # Remember the convention only when it was actually settled, so an
        # unconfident guess never becomes the precedent for later files.
        if det.sign_confident:
            ledger.remember_format(conn, det.signature, det.sign_flipped, p.name)
            known[det.signature] = det.sign_flipped
        print(f"\n{p.name}")
        print(det.summary())
        print(f"  ingested:     {new} new, {dupes} already present")
        print(f"  uncategorized: {uncat}")
        if gap:
            print(f"  ! GAP: stored through {gap['stored_through']}, file starts "
                  f"{gap['file_starts']} - {gap['missing_days']} day(s) never captured.")
            print(f"    Re-export {det.account} from {gap['stored_through']} or earlier.")
        results.append({"file": p.name, "account": det.account, "rows": len(txns),
                        "new": new, "duplicates": dupes, "uncategorized": uncat,
                        "gap": gap})

        if args.archive and p.resolve().parent == INBOX.resolve():
            ARCHIVE.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), _archive_name(p, det.account))

    if args.json:
        print(json.dumps(results, indent=2))
    return 0 if any("error" not in r for r in results) else 1


# ---------------------------------------------------------------- inspect


def cmd_status(args) -> int:
    conn = ledger.connect()
    s = ledger.stats(conn)
    cfg = cfgmod.load()
    s["config_warnings"] = cfgmod.validate(cfg)
    s["inbox_files"] = _inbox_files_names()
    floor = cfgmod.analysis_start(cfg)
    s["analysis_start"] = floor.isoformat() if floor else None

    def text(d):
        print(f"transactions:   {d['transactions']}")
        print(f"uncategorized:  {d['uncategorized']}")
        print(f"accounts:       {', '.join(d['accounts']) or '(none)'}")
        print(f"date range:     {d['first_date']} .. {d['last_date']}")
        if d.get("analysis_start"):
            print(f"analysis from:  {d['analysis_start']}  (earlier rows stored but not analyzed)")
        if d["inbox_files"]:
            print(f"inbox waiting:  {', '.join(d['inbox_files'])}")
        for w in d["config_warnings"]:
            print(f"  ! {w}")
    return _out(s, args.json, text)


def cmd_uncategorized(args) -> int:
    conn = ledger.connect()
    txns = ledger.fetch(conn, uncategorized=True)
    # Group by merchant: the agent should decide once per merchant, not per row.
    groups: dict[str, dict] = {}
    for t in txns:
        g = groups.setdefault(t.merchant, {
            "merchant": t.merchant, "count": 0, "total_cents": 0,
            "sample_description": t.description, "ids": [],
            "accounts": set(), "dates": [],
        })
        g["count"] += 1
        g["total_cents"] += t.amount_cents
        g["ids"].append(t.id)
        g["accounts"].add(t.account)
        g["dates"].append(t.date.isoformat())
    out = []
    for g in sorted(groups.values(), key=lambda g: -abs(g["total_cents"]))[:args.limit]:
        g["accounts"] = sorted(g["accounts"])
        g["date_range"] = [min(g["dates"]), max(g["dates"])]
        del g["dates"]
        out.append(g)

    def text(rows):
        if not rows:
            print("Everything is categorized.")
            return
        print(f"{len(rows)} merchant(s) need a category:\n")
        for r in rows:
            print(f"  {fmt(r['total_cents'], sign=True):>12}  x{r['count']:<3} "
                  f"{r['merchant'][:34]:<34} {r['sample_description'][:40]}")
    return _out(out, args.json, text)


# ---------------------------------------------------------------- mutate


def cmd_categorize(args) -> int:
    conn = ledger.connect()
    if args.merchant:
        n = ledger.set_category_by_merchant(
            conn, args.merchant, args.category, args.subcategory,
            only_uncategorized=not args.force)
        if args.learn:
            catmod.learn(args.merchant, args.category, args.subcategory)
        print(f"Updated {n} transaction(s) for merchant {args.merchant!r}"
              + (" and saved a learned rule." if args.learn else "."))
    elif args.id:
        n = ledger.set_category(conn, args.id, args.category, args.subcategory)
        print(f"Updated {n} transaction(s).")
    else:
        print("Need --id or --merchant", file=sys.stderr)
        return 1
    return 0


def cmd_recategorize(args) -> int:
    """Re-apply the rule set to transactions already in the ledger.

    Rules normally run at ingest. When a rule is added or corrected afterwards,
    this re-runs it over stored rows. Agent and manual decisions are preserved
    unless --force is given, so a human choice is never silently overwritten.
    """
    conn = ledger.connect()
    rules = catmod.load_rules()
    rows = ledger.fetch(conn) if args.force else ledger.fetch(conn, uncategorized=True)
    changed = 0
    for t in rows:
        if not args.force and t.category:
            continue
        if t.category_source == "manual" and not args.force:
            continue
        before = (t.category, t.subcategory)
        t.category = t.subcategory = ""
        catmod.categorize(t, rules)
        if t.category and (t.category, t.subcategory) != before:
            ledger.set_category(conn, t.id, t.category, t.subcategory, source="rule")
            changed += 1
    print(f"Recategorized {changed} transaction(s).")
    print(f"  {ledger.stats(conn)['uncategorized']} still uncategorized")
    return 0


def cmd_recommend(args) -> int:
    from . import optimize
    from .recommend_html import render
    conn = ledger.connect()
    cfg = cfgmod.load()
    today = date.fromisoformat(args.today) if args.today else date.today()
    data = optimize.build(conn, cfg, today, args.period)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0

    if args.html:
        REPORTS.mkdir(parents=True, exist_ok=True)
        settings = cfg.get("settings", {})
        lang = args.lang or settings.get("lang", "en")
        currency = args.currency or settings.get("currency", "USD")
        html = render(data, lang=lang, currency=currency)
        suffix = "" if lang == "en" else f"-{lang}"
        if args.out:
            REPORTS.mkdir(parents=True, exist_ok=True)
            out = Path(args.out)
            out.write_text(html)
        else:
            out = _publish_report(html, f"recommendations{suffix}", today)
        print(out)
        return 0

    g = data["gap"]
    if not g["gap_cents"]:
        print(f"\nOn track: saving {fmt(g['currently_saving_cents'])}/month against a "
              f"{fmt(g['goal_required_cents'])} goal.\n")
    else:
        print(f"\nGap to close: {fmt(g['gap_cents'])}/month "
              f"(goals need {fmt(g['goal_required_cents'])}, "
              f"actually saving {fmt(g['currently_saving_cents'])})\n")
    for c in data["candidates"]:
        print(f"  [{c['difficulty']:<8}] {fmt(c['saving_monthly_cents']):>10}/mo  "
              f"{fmt(c['annual_cents']):>11}/yr  {c['title']}")
        print(f"             {c['evidence']}")
    print(f"\n  identified {fmt(g['identified_cents'])}/mo, "
          f"uncovered {fmt(g['uncovered_cents'])}/mo")
    d = g.get("cut_depth_needed")
    if d:
        print(f"  closing the rest needs a {d['required_pct']:g}% cut across all "
              f"{fmt(g['discretionary_monthly_cents'])}/mo of discretionary spending")
    wk = data["next_week"]
    if wk["categories"]:
        print(f"\n  Next {wk['window_days']} days: {fmt(wk['total_allowance_cents'])} spendable")
        for r in wk["categories"][:6]:
            print(f"    {r['category']:<15} {fmt(r['week_allowance_cents']):>10}   "
                  f"({fmt(r['remaining_cents'], sign=True)} left this month)")
    return 0


def cmd_propose_budget(args) -> int:
    conn = ledger.connect()
    cfg = cfgmod.load()
    proposal = analyze.propose_budget(conn, cfg, date.today(), months=args.months)

    def text(p):
        if not p:
            print("Not enough history to propose a budget yet.")
            return
        print(f"Proposed monthly envelopes (median of last {args.months} months):\n")
        for cat, cents in p.items():
            cur = cfg["budget"]["envelopes_cents"].get(cat, 0)
            mark = "" if not cur else f"   (currently {fmt(cur)})"
            print(f"  {cat:<16} {fmt(cents):>12}{mark}")
        print(f"\n  {'TOTAL':<16} {fmt(sum(p.values())):>12}")
    return _out(proposal, args.json, text)


def cmd_set_budget(args) -> int:
    data = cfgmod.read("budget")
    data.setdefault("envelopes_cents", {})[args.category] = int(round(float(args.amount) * 100))
    cfgmod.write("budget", data)
    print(f"{args.category} budget set to ${float(args.amount):,.2f}/month")
    return 0


def cmd_income_audit(args) -> int:
    """Show what each earner is actually paid, derived from the ledger."""
    conn = ledger.connect()
    cfg = cfgmod.load()
    today = date.fromisoformat(args.today) if args.today else date.today()
    a = analyze.income_audit(conn, cfg, today, months=args.months)

    if args.json:
        print(json.dumps(a, indent=2, default=str))
        return 0

    if not a["streams"]:
        print("No income deposits found. Categorize some transactions as Income first.")
        return 1

    print(f"\n  {'account':<20}{'employer':<26}{'n':>3} {'cadence':<13}"
          f"{'per check':>11}{'per month':>12}")
    for r in a["streams"]:
        flag = "" if r["active"] else "  (ended)"
        print(f"  {r['account']:<20}{r['employer'][:24]:<26}{r['regular_deposits']:>3} "
              f"{r['cadence']:<13}{fmt(r['typical_cents']):>11}"
              f"{fmt(r['implied_monthly_cents']):>12}{flag}")
        for o in r["one_offs"]:
            print(f"  {'':<20}  one-off {o['date']}  {fmt(o['amount_cents'])} (excluded)")

    print(f"\n  implied from actual deposits   {fmt(a['implied_monthly_cents']):>12}/month")
    print(f"  configured as deposits         {fmt(a['configured_monthly_cents']):>12}/month")
    if a.get("non_deposit_monthly_cents"):
        print(f"  plus benefits not deposited    {fmt(a['non_deposit_monthly_cents']):>12}/month")
        print(f"  total household income         {fmt(a['total_monthly_cents']):>12}/month")
    diff = a["difference_cents"]
    if a["agrees"]:
        print(f"  -> agrees (within {fmt(abs(diff))})")
    else:
        word = "HIGHER than" if diff > 0 else "LOWER than"
        print(f"  -> configured is {fmt(abs(diff))}/month {word} the deposits")
        print(f"\n  The spending ceiling is income minus the savings target, so this moves it.")
        print(f"  Confirm with the household before changing anything: a cadence can be")
        print(f"  misread, and a bonus or missed period skews the annualization.")
    return 0


def cmd_set_income(args) -> int:
    """Add or replace an income source, preserving history via effective dating."""
    data = cfgmod.read("income")
    sources = data.setdefault("sources", [])
    today = date.today().isoformat()
    cents = int(round(float(args.amount) * 100))
    name = args.name or "Household income"

    if args.gross:
        print("Refusing: this tool stores after-tax (take-home) pay only. A percentage-based\n"
              "savings plan applied to gross would commit money that never reaches the account.\n"
              "Enter your net figure instead.", file=sys.stderr)
        return 1

    existing = next((s for s in sources if s.get("name") == name and not s.get("effective_to")), None)
    if existing and not args.replace:
        existing["net_monthly_cents"] = cents
        # Apply the other fields too: an update that silently ignores --cadence
        # leaves a wrong label behind that nobody notices.
        if args.cadence:
            existing["cadence"] = args.cadence
        if args.account:
            existing["account"] = args.account
        if args.match:
            existing["match"] = args.match.lower()
        existing.setdefault("basis", "net")
        print(f"Updated {name!r} to ${cents/100:,.2f}/month"
              + (f" ({existing['cadence']})" if existing.get("cadence") else ""))
    else:
        if existing:
            # Close the old entry so past months still analyze against past pay.
            existing["effective_to"] = (date.fromisoformat(args.since or today) -
                                        timedelta(days=1)).isoformat()
        sources.append({
            "id": cfgmod.slugify(name, {s.get("id", "") for s in sources}),
            "name": name,
            "net_monthly_cents": cents,
            "cadence": args.cadence or "semimonthly",
            "effective_from": args.since or today,
            "effective_to": None,
            "account": args.account or "",
            "match": (args.match or "").lower(),
            "basis": "net",
            "in_deposits": not args.not_deposited,
        })
        print(f"Added {name!r} at ${cents/100:,.2f}/month from {args.since or today}")
    cfgmod.write("income", data)
    print(f"Household after-tax monthly income is now "
          f"${cfgmod.monthly_income(cfgmod.load())/100:,.2f}")
    return 0


def cmd_add_fixed(args) -> int:
    data = cfgmod.read("fixed")
    expenses = data.setdefault("expenses", [])
    entry = {
        "id": cfgmod.slugify(args.name, {x.get("id", "") for x in expenses}),
        "name": args.name,
        "category": args.category,
        "amount_cents": int(round(float(args.amount) * 100)),
        "cadence": args.cadence,
        "due_day": args.due_day,
        "account": args.account or "",
        "match": (args.match or args.name).lower(),
        "variable": args.variable,
        "effective_from": args.since or date.today().isoformat(),
        "effective_to": None,
    }
    expenses.append(entry)
    cfgmod.write("fixed", data)
    cfg = cfgmod.load()
    print(f"Added {entry['name']} - {fmt(entry['amount_cents'])} {entry['cadence']}")
    print(f"Fixed commitments now {fmt(cfgmod.fixed_monthly_total(cfg))}/month")
    return 0


def cmd_remind(args) -> int:
    """Add, list or clear a reminder shown at the top of the dashboard."""
    data = cfgmod.read("reminders")
    items = data.setdefault("reminders", [])

    if args.done:
        key = args.done.strip().lower()
        hit = [r for r in items if r.get("id", "").lower() == key
               or r.get("text", "").lower().startswith(key)]
        if not hit:
            print(f"No reminder matching {args.done!r}.", file=sys.stderr)
            return 1
        for r in hit:
            r["active"] = False
        cfgmod.write("reminders", data)
        print(f"Cleared {len(hit)} reminder(s).")
        return 0

    if args.text:
        entry = {
            "id": cfgmod.slugify(args.text, {r.get("id", "") for r in items}),
            "text": args.text,
            "detail": args.detail or "",
            "tag": args.tag,
            "due": args.due,
            "active": True,
        }
        items.append(entry)
        cfgmod.write("reminders", data)
        print(f"Added [{entry['tag']}] {entry['text']}"
              + (f"  (due {entry['due']})" if entry["due"] else ""))
        return 0

    live = cfgmod.reminders(cfgmod.load())
    if not live:
        print("No active reminders.")
        return 0
    for r in live:
        when = ("overdue" if r["overdue"] else
                f"due {r['due']}" if r["due"] else "no date")
        print(f"  [{r['tag']:<8}] {r['text']}   ({when})")
        if r.get("detail"):
            print(f"             {r['detail']}")
    return 0


def cmd_remove_account(args) -> int:
    """Drop every transaction under one account label, for a mislabelled ingest."""
    conn = ledger.connect()
    rows = ledger.fetch(conn)
    mine = [t for t in rows if t.account == args.account]
    if not mine:
        print(f"No account {args.account!r}. Present:", file=sys.stderr)
        for a in sorted({t.account for t in rows}):
            print(f"  {a}", file=sys.stderr)
        return 1

    total = sum(abs(t.amount_cents) for t in mine)
    print(f"{args.account}: {len(mine)} transactions, {fmt(total)} gross, "
          f"{min(t.date for t in mine)} .. {max(t.date for t in mine)}")
    if not args.yes:
        print("\nRe-run with --yes to delete. The source CSV in data/archive/ is untouched,\n"
              "so you can re-ingest it under the right --account afterwards.")
        return 0
    n = ledger.delete_account(conn, args.account)
    print(f"Deleted {n} transactions.")
    return 0


def cmd_remove_fixed(args) -> int:
    """Drop a commitment that turned out to be a one-off."""
    data = cfgmod.read("fixed")
    before = data.get("expenses", [])
    key = args.name.strip().lower()
    keep = [x for x in before
            if x.get("id", "").lower() != key and x.get("name", "").lower() != key]
    if len(keep) == len(before):
        print(f"No commitment matching {args.name!r}. Declared:", file=sys.stderr)
        for x in before:
            print(f"  {x.get('id')}  {x.get('name')}", file=sys.stderr)
        return 1
    data["expenses"] = keep
    cfgmod.write("fixed", data)
    cfg = cfgmod.load()
    print(f"Removed {args.name!r}.")
    print(f"  {len(keep)} commitments, {fmt(cfgmod.fixed_monthly_total(cfg))}/month")
    print(f"  free to spend is now {fmt(cfgmod.monthly_income(cfg) - cfgmod.fixed_monthly_total(cfg) - cfgmod.planned_total(cfg))}/month")
    return 0


def cmd_set_goal(args) -> int:
    data = cfgmod.read("goals")
    goals = data.setdefault("goals", [])
    g = next((x for x in goals if x.get("name") == args.name), None)
    if g is None:
        g = {"id": cfgmod.slugify(args.name, {x.get("id", "") for x in goals}),
             "name": args.name, "priority": len(goals) + 1, "active": True}
        goals.append(g)
    if args.target:
        g["target_cents"] = int(round(float(args.target) * 100))
        g["goal_type"] = "target"
    if args.by:
        g["target_date"] = args.by
    if args.current is not None:
        g["current_balance_cents"] = int(round(float(args.current) * 100))
        g["balance_as_of"] = args.as_of or date.today().isoformat()
    if args.funded_from:
        g["account_match"] = args.funded_from.lower()
    if args.priority:
        g["priority"] = args.priority
    if args.rate is not None:
        # The percentage is the whole goal: no target amount, no date.
        g["goal_type"] = "rate"
        g["contribution_type"] = "percent"
        g["percent_of_net_income"] = float(args.rate)
        g["contribution_fixed_cents"] = 0
        g.pop("target_cents", None)
        g.pop("target_date", None)
    elif args.percent is not None:
        g["contribution_type"] = "percent"
        g["percent_of_net_income"] = float(args.percent)
        g["contribution_fixed_cents"] = 0
    elif args.contribute is not None:
        g["contribution_type"] = "fixed"
        g["contribution_fixed_cents"] = int(round(float(args.contribute) * 100))
        g["percent_of_net_income"] = None
    elif args.auto_contribute:
        g["contribution_type"] = "auto"
    g.setdefault("contribution_type", "auto")
    cfgmod.write("goals", data)

    cfg = cfgmod.load()
    planned = cfgmod.planned_monthly(cfg, g)
    inc = cfgmod.monthly_income(cfg)
    if cfgmod.goal_type(g) == "rate":
        print(f"{g['name']}: save {fmt(planned or 0)} every month"
              + (f" ({g['percent_of_net_income']:g}% of {fmt(inc)} after-tax income)"
                 if g.get("contribution_type") == "percent" else " (fixed)"))
        print("  no target amount or date - the rate is the goal")
        return 0
    print(f"{g['name']}: {fmt(g.get('target_cents', 0))} by {g.get('target_date') or '(no date)'}"
          f", {fmt(g.get('current_balance_cents', 0))} saved")
    if planned is None:
        print("  contribution: whatever the target date requires")
    elif g["contribution_type"] == "percent":
        print(f"  contribution: {g['percent_of_net_income']:g}% of {fmt(inc)} after-tax income "
              f"= {fmt(planned)}/month")
    else:
        print(f"  contribution: {fmt(planned)}/month (fixed)")

    # Say plainly when a plan cannot reach the goal, rather than only in the report.
    if g.get("target_cents") and g.get("target_date") and planned:
        from datetime import date as _d
        remaining = max(g["target_cents"] - g.get("current_balance_cents", 0), 0)
        months = max(analyze.months_between(date.today(), _d.fromisoformat(g["target_date"])), 0.1)
        required = round(remaining / months)
        if planned < required:
            print(f"  ! needs {fmt(required)}/month to hit {g['target_date']} - "
                  f"this plan is {fmt(required - planned)}/month short")
    return 0


def cmd_commitments(args) -> int:
    conn = ledger.connect()
    cfg = cfgmod.load()
    today = date.fromisoformat(args.today) if args.today else date.today()
    start, end, label = analyze.resolve_period(args.period, today)
    rows = analyze.verify_commitments(conn, cfg, start, end)

    def text(rows):
        if not rows:
            print("No fixed expenses declared. Add them with `python3 -m budget ui`.")
            return
        print(f"\n{label}  ({start} .. {end})\n")
        for r in rows:
            mark = {"paid": "ok", "drift": "CHANGED", "missing": "MISSING",
                    "upcoming": "due"}[r["status"]]
            amt = fmt(r["actual_cents"]) if r["actual_cents"] else "-"
            extra = ""
            if r["status"] == "drift":
                extra = f"  ({fmt(r['drift_cents'], sign=True)} vs {fmt(r['expected_cents'])})"
            print(f"  {r['due']}  {r['name']:<22} {amt:>11}  {mark}{extra}")
        cf = analyze.cashflow(conn, cfg, start, end, today)["monthly"]
        print(f"\n  income {fmt(cf['income_cents'])}  -  fixed {fmt(cf['fixed_cents'])}"
              f"  -  goals {fmt(cf['goal_required_cents'])}  =  free {fmt(cf['free_cents'])}/month")
    return _out(rows, args.json, text)


def cmd_ui(args) -> int:
    from .ui import serve
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


# ---------------------------------------------------------------- report


def cmd_report(args) -> int:
    conn = ledger.connect()
    cfg = cfgmod.load()
    today = date.fromisoformat(args.today) if args.today else date.today()
    rep = analyze.build_report(conn, cfg, args.period, today)

    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0

    t = rep["totals"]
    print(f"\n{rep['period']['label']}  ({rep['period']['start']} .. {rep['period']['end']})")
    print(f"  spend {fmt(t['spend_cents'])}   income {fmt(t['income_cents'])}   "
          f"saved {fmt(t['saved_cents'])}   net {fmt(t['net_cents'], sign=True)}")
    print("\n  Category            actual      budget    status")
    for r in rep["budget"]:
        if not r["actual_cents"] and not r["budget_monthly_cents"]:
            continue
        b = fmt(r["budget_monthly_cents"]) if r["budget_monthly_cents"] else "-"
        print(f"  {r['category']:<16} {fmt(r['actual_cents']):>10} {b:>11}    {r['status']}")
    s = rep["savings"]
    if s.get("target_cents"):
        print(f"\n  {s['name']}: {fmt(s['current_cents'])} / {fmt(s['target_cents'])} "
              f"({s['pct_complete']}%)")
        if s.get("required_monthly_cents") is not None:
            verdict = "ON TRACK" if s["on_track"] else "BEHIND"
            print(f"  need {fmt(s['required_monthly_cents'])}/mo, "
                  f"doing {fmt(s['observed_monthly_cents'])}/mo -> {verdict}")
    if rep["uncategorized"]:
        print(f"\n  ! {len(rep['uncategorized'])} uncategorized transaction(s)")
    for w in rep["config_warnings"]:
        print(f"  ! {w}")
    return 0


def cmd_dashboard(args) -> int:
    from .report_html import render
    conn = ledger.connect()
    cfg = cfgmod.load()
    today = date.fromisoformat(args.today) if args.today else date.today()
    rep = analyze.build_report(conn, cfg, args.period, today)
    if args.narrative and Path(args.narrative).exists():
        rep["narrative"] = json.loads(Path(args.narrative).read_text())
    html = render(rep)
    if args.out:
        REPORTS.mkdir(parents=True, exist_ok=True)
        out = Path(args.out)
        out.write_text(html)
    else:
        out = _publish_report(html, "dashboard", today)
    print(out)
    return 0


# ---------------------------------------------------------------- main


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="budget", description="Household budget analysis")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("ingest", help="parse bank CSVs into the ledger")
    g.add_argument("paths", nargs="*")
    g.add_argument("--account", help="override the account label")
    g.add_argument("--flip", dest="flip", action="store_true", default=None,
                   help="force: file lists spending as positive")
    g.add_argument("--no-flip", dest="flip", action="store_false",
                   help="force: file already lists spending as negative")
    g.add_argument("--dry-run", action="store_true", help="show what would be ingested")
    g.add_argument("--archive", action="store_true", help="move inbox files to data/archive after ingest")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_ingest)

    g = sub.add_parser("status", help="ledger summary")
    g.add_argument("--json", action="store_true"); g.set_defaults(func=cmd_status)

    g = sub.add_parser("uncategorized", help="merchants needing a category")
    g.add_argument("--limit", type=int, default=40)
    g.add_argument("--json", action="store_true"); g.set_defaults(func=cmd_uncategorized)

    g = sub.add_parser("categorize", help="assign a category")
    g.add_argument("category")
    g.add_argument("--id"); g.add_argument("--merchant")
    g.add_argument("--subcategory", default="")
    g.add_argument("--learn", action="store_true", help="remember this merchant mapping")
    g.add_argument("--force", action="store_true", help="also overwrite existing categories")
    g.set_defaults(func=cmd_categorize)

    g = sub.add_parser("report", help="analysis for a period")
    g.add_argument("--period", default="month",
                   help="week | last-week | month | last-month | YYYY-MM | N-days")
    g.add_argument("--today", help="override today's date (testing)")
    g.add_argument("--json", action="store_true"); g.set_defaults(func=cmd_report)

    g = sub.add_parser("dashboard", help="render the HTML dashboard")
    g.add_argument("--period", default="month")
    g.add_argument("--out"); g.add_argument("--today")
    g.add_argument("--narrative", help="JSON file with the agent's written analysis")
    g.set_defaults(func=cmd_dashboard)

    g = sub.add_parser("recategorize", help="re-apply rules to rows already in the ledger")
    g.add_argument("--force", action="store_true",
                   help="also re-run rules over already-categorized rows")
    g.set_defaults(func=cmd_recategorize)

    g = sub.add_parser("recommend", help="what to optimize, and what to do next week/month")
    g.add_argument("--period", default="month")
    g.add_argument("--today")
    g.add_argument("--html", action="store_true", help="render the HTML recommendations page")
    g.add_argument("--lang", choices=["en", "zh-Hans"], help="page language (default: config)")
    g.add_argument("--currency", help="currency symbol to render, e.g. USD, CNY")
    g.add_argument("--out")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_recommend)

    g = sub.add_parser("propose-budget", help="suggest envelopes from actuals")
    g.add_argument("--months", type=int, default=3)
    g.add_argument("--json", action="store_true"); g.set_defaults(func=cmd_propose_budget)

    g = sub.add_parser("set-budget", help="set one envelope")
    g.add_argument("category"); g.add_argument("amount")
    g.set_defaults(func=cmd_set_budget)

    g = sub.add_parser("income-audit",
                       help="derive each earner's true monthly pay from the ledger")
    g.add_argument("--months", type=int, default=12)
    g.add_argument("--today"); g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_income_audit)

    g = sub.add_parser("set-income", help="add or update an income source (AFTER TAX)")
    g.add_argument("amount", help="NET take-home per month after tax, in dollars")
    g.add_argument("--name", help="source name, e.g. 'Salary - Member A'")
    g.add_argument("--cadence", default=None,
                   choices=["weekly", "biweekly", "semimonthly", "monthly", "irregular"],
                   help="pay frequency (informational; default semimonthly for a new source)")
    g.add_argument("--since", help="effective from (YYYY-MM-DD), default today")
    g.add_argument("--replace", action="store_true",
                   help="close the current entry and start a new one (use for a raise)")
    g.add_argument("--account"); g.add_argument("--match")
    g.add_argument("--not-deposited", action="store_true",
                   help="income that never arrives as a deposit (a pre-tax FSA benefit); "
                        "excluded from the deposit comparison")
    g.add_argument("--gross", action="store_true",
                   help="(rejected) the amount is pre-tax - convert to net first")
    g.set_defaults(func=cmd_set_income)

    g = sub.add_parser("add-fixed", help="declare a recurring commitment")
    g.add_argument("name"); g.add_argument("amount")
    g.add_argument("--category", default="Other")
    g.add_argument("--cadence", default="monthly",
                   choices=["weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"])
    g.add_argument("--due-day", type=int, default=1, dest="due_day")
    g.add_argument("--account"); g.add_argument("--match")
    g.add_argument("--variable", action="store_true", help="amount changes monthly (utilities)")
    g.add_argument("--since")
    g.set_defaults(func=cmd_add_fixed)

    g = sub.add_parser("remind", help="add, list or clear a dashboard reminder")
    g.add_argument("text", nargs="?", help="the reminder; omit to list")
    g.add_argument("--detail", help="a second line of context")
    g.add_argument("--tag", default="admin",
                   choices=["tax", "admin", "spending", "goal", "data"])
    g.add_argument("--due", help="YYYY-MM-DD")
    g.add_argument("--done", help="clear a reminder by id or leading text")
    g.set_defaults(func=cmd_remind)

    g = sub.add_parser("remove-account", help="undo a mislabelled ingest")
    g.add_argument("account")
    g.add_argument("--yes", action="store_true", help="actually delete")
    g.set_defaults(func=cmd_remove_account)

    g = sub.add_parser("remove-fixed", help="drop a declared commitment")
    g.add_argument("name", help="the commitment's name or id")
    g.set_defaults(func=cmd_remove_fixed)

    g = sub.add_parser("set-goal", help="add or update a savings goal")
    g.add_argument("name")
    g.add_argument("--target"); g.add_argument("--by")
    g.add_argument("--current"); g.add_argument("--as-of")
    g.add_argument("--funded-from", help="account/merchant text this goal's contributions match")
    g.add_argument("--priority", type=int)
    plan = g.add_mutually_exclusive_group()
    plan.add_argument("--rate", type=float,
                      help="save this %% of NET monthly income, every month - no target "
                           "amount or date needed")
    plan.add_argument("--percent", type=float,
                      help="contribute this %% of NET (after-tax) monthly income toward "
                           "a target amount")
    plan.add_argument("--contribute", help="contribute this fixed amount per month, in dollars")
    plan.add_argument("--auto-contribute", action="store_true",
                      help="no fixed plan; use whatever the target and date require")
    g.set_defaults(func=cmd_set_goal)

    g = sub.add_parser("commitments", help="check fixed expenses actually posted")
    g.add_argument("--period", default="month")
    g.add_argument("--today"); g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_commitments)

    g = sub.add_parser("ui", help="open the manual-input web UI")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")
    g.set_defaults(func=cmd_ui)

    args = p.parse_args(argv)
    return args.func(args)
