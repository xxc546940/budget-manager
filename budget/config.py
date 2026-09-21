"""Configuration: four separate JSON inputs, assembled into one view.

Split by what changes and how often:
  income.json          pay, effective-dated - changes on a raise or job change
  fixed_expenses.json  known commitments - changes when you sign something
  goals.json           savings goals - changes rarely, matters most
  budget.json          discretionary envelopes + household settings

Everything holds money as integer cents and dates as ISO strings, so the files
stay diffable and hand-editable. The HTML UI (`python3 -m budget ui`) writes
these same files.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("BUDGET_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("BUDGET_DATA_DIR", ROOT / "data"))
INBOX = DATA_DIR / "inbox"
ARCHIVE = DATA_DIR / "archive"
REPORTS_DIR = Path(os.environ.get("BUDGET_REPORTS_DIR", ROOT / "reports"))

FILES = {
    "budget": "budget.json",
    "income": "income.json",
    "fixed": "fixed_expenses.json",
    "goals": "goals.json",
    "reminders": "reminders.json",
}

DEFAULTS = {
    "budget": {"household": {"name": "Our Household", "members": []},
               "envelopes_cents": {},
               "settings": {"currency": "USD", "week_starts": "monday",
                            "large_transaction_cents": 20000, "exclude_accounts": []}},
    "income": {"sources": []},
    "fixed": {"expenses": []},
    "goals": {"goals": []},
    "reminders": {"reminders": []},
}

# Cadence -> how many times a year it happens. Used to normalize any commitment
# or income stream to a comparable monthly figure.
PER_YEAR = {
    "weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12,
    "quarterly": 4, "semiannual": 2, "annual": 1, "irregular": 12,
}


def _in_test_run() -> bool:
    import sys
    return ("pytest" in sys.modules
            or os.environ.get("BUDGET_TEST") == "1"
            or Path(sys.argv[0]).name.startswith("test_"))


def _is_temp(path: Path) -> bool:
    import tempfile
    root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return root in resolved.parents or resolved == root


def path_for(key: str) -> Path:
    return CONFIG_DIR / FILES[key]


def read(key: str) -> dict:
    p = path_for(key)
    if not p.exists():
        # First run: seed from the tracked template so a fresh clone works.
        example = p.with_suffix(".example.json")
        if example.exists():
            p.write_text(example.read_text())
        else:
            return json.loads(json.dumps(DEFAULTS[key]))
    data = json.loads(p.read_text())
    for k, v in DEFAULTS[key].items():
        data.setdefault(k, v)
    return data


def write(key: str, data: dict) -> None:
    # A test that writes to the real config silently corrupts the household's
    # figures; this already happened once, adding a $5,000 phantom salary.
    # Under pytest or the suite, refuse any write outside a temp directory.
    if _in_test_run() and not _is_temp(CONFIG_DIR):
        raise RuntimeError(
            f"refusing to write real config at {CONFIG_DIR} from a test run. "
            "Point config.CONFIG_DIR at a temp directory first.")
    p = path_for(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Never let a crash mid-write truncate a config file.
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)


def monthly_cents(amount_cents: int, cadence: str) -> int:
    """Normalize any cadence to a monthly figure."""
    return round(amount_cents * PER_YEAR.get(cadence or "monthly", 12) / 12)


def _active(entry: dict, on: date) -> bool:
    f = entry.get("effective_from")
    t = entry.get("effective_to")
    if f and date.fromisoformat(f) > on:
        return False
    if t and date.fromisoformat(t) < on:
        return False
    return entry.get("active", True)


# ---------------------------------------------------------------- income


def income_sources(cfg: dict, on: date) -> list[dict]:
    return [s for s in cfg["income"]["sources"] if _active(s, on)]


def deposit_sources(cfg: dict, on: date) -> list[dict]:
    """Income that actually lands as a categorized deposit.

    Pre-tax benefits (a dependent-care FSA) are real spendable money but never
    appear as a payroll deposit - they are deducted before the paycheck and come
    back as reimbursements, which are Transfers. Comparing configured income
    against observed deposits has to skip them or it reports a permanent
    shortfall.
    """
    return [s for s in income_sources(cfg, on) if s.get("in_deposits", True)]


def monthly_income(cfg: dict, on: date | None = None) -> int:
    """Household NET (after-tax, take-home) income per month.

    Every figure in this file is after tax. Nothing in the system consumes a
    gross number: a percentage-based savings plan applied to gross would quietly
    commit money that never reaches the account.
    """
    on = on or date.today()
    total = 0
    for src in income_sources(cfg, on):
        if src.get("basis", "net") != "net":
            # Refuse to silently treat a gross figure as spendable.
            continue
        total += src.get("net_monthly_cents", 0)
    return total


def gross_sources(cfg: dict, on: date | None = None) -> list[dict]:
    """Sources mistakenly recorded as gross - excluded from every calculation."""
    on = on or date.today()
    return [s for s in income_sources(cfg, on) if s.get("basis", "net") != "net"]


def expected_income(cfg: dict, start: date, end: date) -> int:
    """Income expected across a date range, integrated daily.

    Daily rather than a single rate for the whole window, because a raise that
    lands mid-month would otherwise be applied to the whole month or none of it.
    """
    total = 0.0
    d = start
    while d <= end:
        total += monthly_income(cfg, d) / 30.44
        d += timedelta(days=1)
    return round(total)


# ---------------------------------------------------------------- fixed


def fixed_expenses(cfg: dict, on: date | None = None) -> list[dict]:
    on = on or date.today()
    return [x for x in cfg["fixed"]["expenses"] if _active(x, on)]


def fixed_monthly_total(cfg: dict, on: date | None = None) -> int:
    return sum(monthly_cents(x.get("amount_cents", 0), x.get("cadence", "monthly"))
               for x in fixed_expenses(cfg, on))


def occurrences(expense: dict, start: date, end: date) -> list[date]:
    """Dates this commitment is expected to fall on within [start, end]."""
    cadence = expense.get("cadence", "monthly")
    day = int(expense.get("due_day") or 1)
    out: list[date] = []

    if cadence in ("monthly", "quarterly", "semiannual", "annual"):
        step = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}[cadence]
        anchor = expense.get("effective_from")
        anchor_month = date.fromisoformat(anchor).month if anchor else start.month
        m = date(start.year, start.month, 1)
        while m <= end:
            if step == 1 or (m.month - anchor_month) % step == 0:
                last = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                due = m.replace(day=min(day, last.day))
                if start <= due <= end:
                    out.append(due)
            m = (m + timedelta(days=32)).replace(day=1)
    else:
        every = {"weekly": 7, "biweekly": 14, "semimonthly": 15}.get(cadence, 30)
        anchor = date.fromisoformat(expense["effective_from"]) if expense.get("effective_from") else start
        d = anchor
        while d < start:
            d += timedelta(days=every)
        while d <= end:
            out.append(d)
            d += timedelta(days=every)
    return out


# ---------------------------------------------------------------- goals


def goals(cfg: dict, on: date | None = None) -> list[dict]:
    on = on or date.today()
    live = [g for g in cfg["goals"]["goals"] if g.get("active", True)]
    return sorted(live, key=lambda g: (g.get("priority", 99), g.get("name", "")))


def primary_goal(cfg: dict) -> dict | None:
    g = goals(cfg)
    return g[0] if g else None


def goal_type(goal: dict) -> str:
    """"rate" (save a share of income every month) or "target" (an amount by a date).

    A rate goal is the common case and needs no long-term target: the percentage
    IS the goal, and success is whether the money actually moved this month.
    """
    declared = goal.get("goal_type")
    if declared in ("rate", "target"):
        return declared
    return "target" if goal.get("target_cents") else "rate"


def planned_monthly(cfg: dict, goal: dict, on: date | None = None) -> int | None:
    """What this goal is *planned* to receive each month.

    Three kinds of plan:
      "percent" - a share of NET (after-tax) income, so it scales with a raise
      "fixed"   - a flat amount
      "auto"    - no plan; the caller falls back to whatever the target and date
                  require, which is the old behavior

    Returns None for "auto" so callers can tell "no plan" from "plans zero".
    """
    kind = goal.get("contribution_type", "auto")
    if kind == "percent":
        pct = float(goal.get("percent_of_net_income") or 0)
        return round(monthly_income(cfg, on) * pct / 100)
    if kind == "fixed":
        # A $7,500 yearly IRA contribution is $625 a month, not a $7,500 month
        # followed by eleven empty ones.
        return monthly_cents(int(goal.get("contribution_fixed_cents") or 0),
                             goal.get("contribution_cadence", "monthly"))
    return None


def planned_total(cfg: dict, on: date | None = None) -> int:
    """Total planned contributions across goals. 'auto' goals contribute 0 here."""
    return sum(planned_monthly(cfg, g, on) or 0 for g in goals(cfg, on))


def committed_percent(cfg: dict, on: date | None = None) -> float:
    """Share of net income committed to percentage-based goals."""
    return sum(float(g.get("percent_of_net_income") or 0)
               for g in goals(cfg, on) if g.get("contribution_type") == "percent")


# ---------------------------------------------------------------- assemble


def load() -> dict:
    """The single config view the rest of the code reads."""
    cfg = {k: read(k) for k in FILES}
    b = cfg["budget"]
    return {
        "household": b.get("household", DEFAULTS["budget"]["household"]),
        "settings": b.get("settings", DEFAULTS["budget"]["settings"]),
        "budget": {"period": "monthly", "envelopes_cents": b.get("envelopes_cents", {})},
        "income": cfg["income"],
        "fixed": cfg["fixed"],
        "goals": cfg["goals"],
        "reminders": cfg["reminders"],
    }


def reminders(cfg: dict, on: date | None = None) -> list[dict]:
    """Active reminders, soonest due first, undated last."""
    on = on or date.today()
    out = []
    for r in cfg.get("reminders", {}).get("reminders", []):
        if not r.get("active", True):
            continue
        due = r.get("due")
        overdue = bool(due and date.fromisoformat(due) < on)
        # Normalize the optional keys so callers and the sort never KeyError.
        out.append({**r, "due": due, "tag": r.get("tag", "admin"),
                    "detail": r.get("detail", ""), "overdue": overdue,
                    "days_until": (date.fromisoformat(due) - on).days if due else None})
    return sorted(out, key=lambda r: (r["due"] is None, r["due"] or ""))


def analysis_start(cfg: dict) -> date | None:
    """Earliest date the ledger is complete enough to analyse.

    Card exports usually cover a short recent window while checking goes back
    years. Averaging across that boundary silently mixes months where the cards
    were visible with months where they were not, so every trailing median and
    category total comes out low. This clamps all analysis to the period where
    the accounts are comparable.
    """
    raw = cfg.get("settings", {}).get("analysis_start")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def savings_model(cfg: dict) -> str:
    """"residual" (income minus spending) or "transactions" (tracked transfers).

    Residual is the default because most households never make an explicit
    savings transfer; what is not spent simply stays put.
    """
    m = cfg.get("settings", {}).get("savings_model", "residual")
    return m if m in ("residual", "transactions") else "residual"


def envelopes(cfg: dict) -> dict[str, int]:
    """Only categories with a non-zero budget count as actually budgeted."""
    return {k: v for k, v in cfg["budget"]["envelopes_cents"].items() if v}


def slugify(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "item").lower()).strip("-") or "item"
    cand, n = base, 2
    while cand in existing:
        cand, n = f"{base}-{n}", n + 1
    return cand


def validate(cfg: dict) -> list[str]:
    """Problems worth telling the user about, in the order they matter."""
    problems = []
    if not cfg["income"]["sources"]:
        problems.append("No income sources set - add them in the UI (`python3 -m budget ui`) "
                        "or income.json, or every 'left over' figure is meaningless")
    if not goals(cfg):
        problems.append("No savings goal set - nothing to stay on track for")
    else:
        for g in goals(cfg):
            if goal_type(g) == "rate":
                # A rate goal needs only a contribution; a target and date are optional.
                if planned_monthly(cfg, g) in (None, 0):
                    problems.append(
                        f"Goal {g.get('name')!r} saves nothing - set a percentage of "
                        "after-tax income or a fixed monthly amount")
            elif not g.get("target_date"):
                problems.append(f"Goal {g.get('name')!r} has a target amount but no date - "
                                "cannot compute a required pace")
    if not cfg["fixed"]["expenses"]:
        problems.append("No fixed expenses declared - mortgage, car loan and daycare will be "
                        "treated as discretionary spending")
    if not envelopes(cfg):
        problems.append("No budget envelopes set - run `python3 -m budget propose-budget`")

    for src in gross_sources(cfg):
        problems.append(
            f"Income source {src.get('name')!r} is marked basis={src.get('basis')!r}, not 'net' - "
            "it is being EXCLUDED from every calculation. Record after-tax (take-home) pay.")

    pct = committed_percent(cfg)
    if pct > 100:
        problems.append(f"Savings goals claim {pct:.0f}% of after-tax income - over 100%")

    # Committing more than you earn is the one thing worth shouting about.
    inc = monthly_income(cfg)
    fix = fixed_monthly_total(cfg)
    if inc and fix > inc:
        problems.append(f"Fixed commitments (${fix/100:,.0f}/mo) exceed after-tax income "
                        f"(${inc/100:,.0f}/mo)")
    plan = planned_total(cfg)
    if inc and fix + plan > inc:
        problems.append(
            f"Commitments (${fix/100:,.0f}) + planned savings (${plan/100:,.0f}) exceed "
            f"after-tax income (${inc/100:,.0f}/mo)")
    return problems


# Back-compat helpers used by analyze.py
def goal_date(g: dict) -> date | None:
    d = g.get("target_date")
    return date.fromisoformat(d) if d else None


def balance_as_of(g: dict) -> date | None:
    d = g.get("balance_as_of")
    return date.fromisoformat(d) if d else None
