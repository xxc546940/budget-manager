"""Budget math: category variance, savings-goal pacing, anomalies, trends.

Everything numeric lives here so the agent never does arithmetic. The agent
reads this module's output and writes the judgment: what matters, why, and
what to do about it.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from . import config as cfgmod
from .ledger import fetch
from .schema import NON_SPEND, Transaction, fmt

# ---------------------------------------------------------------- periods


def week_bounds(d: date) -> tuple[date, date]:
    """Monday..Sunday containing d."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def months_between(a: date, b: date) -> float:
    """Fractional months from a to b. Used for savings pacing."""
    return (b - a).days / 30.44


def period_kind(spec: str) -> str:
    """The shape of a period, so a renderer can label it in any language."""
    spec = (spec or "week").strip().lower()
    if spec in ("week", "this-week", "last-week"):
        return "week"
    if spec.endswith("-days") and spec[:-5].isdigit():
        return "days"
    return "month"


def resolve_period(spec: str, today: date) -> tuple[date, date, str]:
    """Turn 'week' | 'last-week' | 'month' | 'last-month' | 'YYYY-MM' | 'N-days' into bounds."""
    spec = (spec or "week").strip().lower()
    if spec in ("week", "this-week"):
        s, e = week_bounds(today); return s, min(e, today), f"Week of {s:%b %d, %Y}"
    if spec == "last-week":
        s, e = week_bounds(today - timedelta(days=7)); return s, e, f"Week of {s:%b %d, %Y}"
    if spec in ("month", "this-month"):
        s, e = month_bounds(today); return s, min(e, today), f"{s:%B %Y}"
    if spec == "last-month":
        s, e = month_bounds(today.replace(day=1) - timedelta(days=1)); return s, e, f"{s:%B %Y}"
    if spec.endswith("-days") and spec[:-5].isdigit():
        n = int(spec[:-5]); s = today - timedelta(days=n - 1)
        return s, today, f"Last {n} days"
    if len(spec) == 7 and spec[4] == "-":
        y, m = int(spec[:4]), int(spec[5:])
        s, e = month_bounds(date(y, m, 1)); return s, e, f"{s:%B %Y}"
    raise ValueError(f"unrecognized period: {spec!r}")


# ---------------------------------------------------------------- helpers


def window(conn, cfg: dict, start: date, end: date, clamp: bool = True) -> list[Transaction]:
    """fetch(), clamped to the configured analysis start.

    Every read of the ledger goes through here so a single setting cannot be
    honoured in one place and forgotten in another - which would make totals
    and the medians they are compared against disagree.

    `clamp=False` is for savings and income. The analysis start exists because
    CARD exports cover a short window; checking goes back years and is where
    savings transfers and pay land. Clamping those would discard a year of good
    data and make an annual contribution impossible to measure.
    """
    floor = cfgmod.analysis_start(cfg) if clamp else None
    if floor and start < floor:
        start = floor
    if start > end:
        return []
    return fetch(conn, start, end)


def spend_only(txns: list[Transaction], exclude: list[str] | None = None) -> list[Transaction]:
    ex = set(exclude or [])
    return [t for t in txns
            if t.amount_cents < 0 and t.category not in NON_SPEND and t.account not in ex]


def income_only(txns, exclude=None) -> list[Transaction]:
    ex = set(exclude or [])
    return [t for t in txns if t.category == "Income" and t.account not in ex]


def savings_only(txns, exclude=None) -> list[Transaction]:
    """Money moved INTO savings (outflow from checking tagged Savings)."""
    ex = set(exclude or [])
    return [t for t in txns
            if t.category == "Savings" and t.amount_cents < 0 and t.account not in ex]


def retirement_only(txns, exclude=None) -> list[Transaction]:
    """Money into retirement accounts: not spending, and not the monthly goal."""
    ex = set(exclude or [])
    return [t for t in txns
            if t.category == "Retirement" and t.amount_cents < 0 and t.account not in ex]


def by_category(txns: list[Transaction]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for t in txns:
        out[t.category or "Uncategorized"] += abs(t.amount_cents)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def by_merchant(txns: list[Transaction], limit: int = 15) -> list[dict]:
    agg: dict[str, dict] = {}
    for t in txns:
        a = agg.setdefault(t.merchant, {"merchant": t.merchant, "total_cents": 0,
                                        "count": 0, "category": t.category})
        a["total_cents"] += abs(t.amount_cents)
        a["count"] += 1
    return sorted(agg.values(), key=lambda a: -a["total_cents"])[:limit]


# ---------------------------------------------------------------- budget


def budget_status(conn, cfg: dict, start: date, end: date) -> list[dict]:
    """Month-to-date spending against the full monthly envelope.

    Not prorated. A monthly target is the number the household set and thinks
    in, so progress is shown against the whole of it - "spent $873 of $750" is
    read correctly, while "$873 of the $296 that 12 days is worth" makes every
    category look breached and is quietly comparing two different things.
    `days_observed` carries the context that the month is not over.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    env = cfgmod.envelopes(cfg)
    # Categories covered by a declared commitment are not discretionary
    # envelopes - the mortgage is not something to come in under this week.
    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, end) if x.get("category")}

    # Spending is measured over the calendar month the period ends in, so it is
    # comparable with a monthly target however the report period was asked for.
    m_start, m_end = month_bounds(end)
    obs_start = max(m_start, start) if start > m_start else m_start
    floor = cfgmod.analysis_start(cfg)
    if floor and obs_start < floor:
        obs_start = floor
    obs_end = min(m_end, end)
    txns = spend_only(window(conn, cfg, obs_start, obs_end), ex)
    actuals = by_category(txns)

    days_in_month = (m_end - m_start).days + 1
    days_observed = max((obs_end - obs_start).days + 1, 0)

    rows = []
    for cat in sorted((set(env) | set(actuals)) - committed):
        budget = env.get(cat, 0)
        actual = actuals.get(cat, 0)
        over = actual - budget
        rows.append({
            "category": cat,
            "actual_cents": actual,
            "budget_monthly_cents": budget,
            "variance_cents": -over,                       # negative = over budget
            "pct_used": round(actual / budget * 100, 1) if budget else None,
            "status": ("no_budget" if not budget else
                       "over" if over > 0 else
                       "at_risk" if actual >= budget * 0.9 else "ok"),
            "txn_count": sum(1 for t in txns if (t.category or "Uncategorized") == cat),
            "month": m_start.strftime("%B %Y"),
            "days_observed": days_observed,
            "days_in_month": days_in_month,
        })
    return sorted(rows, key=lambda r: -r["actual_cents"])


def propose_budget(conn, cfg: dict, today: date, months: int = 3) -> dict[str, int]:
    """Suggest monthly envelopes from trailing actuals, rounded to $5.

    Two corrections that a naive median gets wrong:
      - The current month is partial, so it is excluded; including it would drag
        every envelope below what the household actually spends.
      - A category that only shows up in a minority of months (travel, car
        repair, annual fees) is lumpy, not monthly. Its median is either zero or
        the size of the one big month, and neither is a usable budget, so it is
        amortized across the whole window instead.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    # Whole months only, ending with the last complete month.
    last_complete_end = today.replace(day=1) - timedelta(days=1)
    start = last_complete_end.replace(day=1)
    keys = [start.strftime("%Y-%m")]
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
        keys.append(start.strftime("%Y-%m"))
    keys = sorted(keys)
    if not keys:
        return {}

    txns = spend_only(window(conn, cfg, start, last_complete_end), ex)
    per_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in txns:
        cat = t.category or "Uncategorized"
        per_month[cat][t.date.strftime("%Y-%m")] += abs(t.amount_cents)

    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, today) if x.get("category")}
    out = {}
    for cat, month_map in per_month.items():
        if cat == "Uncategorized" or cat in committed:
            continue  # mysteries get categorized first; commitments are not envelopes
        series = [month_map.get(k, 0) for k in keys]
        present = sum(1 for v in series if v > 0)
        value = (statistics.median(series) if present >= len(keys) * 0.6
                 else sum(series) / len(keys))
        cents = int(round(value / 500) * 500)
        if cents:
            out[cat] = cents
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------- savings


PERIODS_PER_YEAR = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12}


def _cadence_from_gaps(gaps: list[int]) -> tuple[str, float]:
    """Name a pay cadence from the gaps between deposits.

    Biweekly and semimonthly are the pair that get confused: both land roughly
    twice a month, but 26 payslips a year is 8% more money than 24. Biweekly
    gaps are a flat 14; semimonthly alternate around 15 and drift with month
    length, so the spread between gaps is what separates them.
    """
    if not gaps:
        return "unknown", 0.0
    med = statistics.median(gaps)
    per_year = 365.25 / med if med else 0
    if med <= 8:
        return "weekly", per_year
    if 12 <= med <= 16:
        # A flat 14 every time is biweekly; anything that wanders is semimonthly.
        spread = max(gaps) - min(gaps)
        if med <= 14.5 and spread <= 2:
            return "biweekly", per_year
        return "semimonthly", per_year
    if 26 <= med <= 35:
        return "monthly", per_year
    return "irregular", per_year


def income_audit(conn, cfg: dict, today: date, months: int = 12) -> dict:
    """Derive each earner's true monthly income from their actual paycheck pattern.

    A configured round number is a guess until this agrees with it. Three things
    routinely make the guess wrong, and all three are handled here:
      - biweekly vs semimonthly (26 vs 24 payslips: an 8% error)
      - a job change, which makes a long average blend pay you no longer receive
      - a signing bonus, which drags any mean upward
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    start = today - timedelta(days=round(months * 30.44))
    rows = income_only(window(conn, cfg, start, today, clamp=False), ex)

    streams: dict[tuple, list] = defaultdict(list)
    for t in rows:
        streams[(t.account, t.merchant)].append(t)

    out = []
    for (account, merchant), txns in streams.items():
        txns.sort(key=lambda t: t.date)
        if len(txns) < 3:
            continue
        amounts = [t.amount_cents for t in txns]
        med = statistics.median(amounts)
        # A signing bonus or a back-payment is not salary.
        regular = [a for a in amounts if abs(a - med) <= med * 0.15]
        outliers = [{"date": t.date.isoformat(), "amount_cents": t.amount_cents}
                    for t in txns if abs(t.amount_cents - med) > med * 0.15]
        if not regular:
            continue
        gaps = [(txns[i + 1].date - txns[i].date).days for i in range(len(txns) - 1)]
        gaps = [g for g in gaps if 0 < g <= 45]
        cadence, per_year_obs = _cadence_from_gaps(gaps)
        periods = PERIODS_PER_YEAR.get(cadence, round(per_year_obs) or 12)
        typical = int(statistics.median(regular))
        out.append({
            "account": account, "employer": merchant,
            "first_seen": txns[0].date.isoformat(), "last_seen": txns[-1].date.isoformat(),
            "deposits": len(txns), "regular_deposits": len(regular),
            "cadence": cadence, "periods_per_year": periods,
            "median_gap_days": int(statistics.median(gaps)) if gaps else None,
            "typical_cents": typical,
            "implied_monthly_cents": round(typical * periods / 12),
            "one_offs": outliers,
            # A stream with no deposit in the last ~6 weeks is probably a past job.
            "active": (today - txns[-1].date).days <= 45,
        })

    out.sort(key=lambda r: (not r["active"], -r["implied_monthly_cents"]))
    active = [r for r in out if r["active"]]
    implied = sum(r["implied_monthly_cents"] for r in active)
    # Compare like with like: benefits that never hit the bank are excluded.
    configured = sum(s.get("net_monthly_cents", 0)
                     for s in cfgmod.deposit_sources(cfg, today)
                     if s.get("basis", "net") == "net")
    non_deposit = cfgmod.monthly_income(cfg, today) - configured
    return {
        "streams": out,
        "active_streams": len(active),
        "implied_monthly_cents": implied,
        "configured_monthly_cents": configured,
        "non_deposit_monthly_cents": non_deposit,
        "total_monthly_cents": configured + non_deposit,
        "difference_cents": configured - implied,
        "agrees": bool(configured) and abs(configured - implied) <= max(configured * 0.02, 2500),
    }


def income_check(conn, cfg: dict, today: date, months: int = 3) -> dict | None:
    """Quietly verify the configured income against what actually arrived.

    The configured figure is the basis for the whole spending ceiling, so it has
    to be right - but it is not something to track week to week. This checks it
    in the background and only speaks up when it has drifted.

    Trailing 3 months on purpose: over a longer window a job change makes an
    accurate figure look wrong.
    """
    # Only the part that arrives as a deposit can be checked against deposits.
    configured = sum(s.get("net_monthly_cents", 0)
                     for s in cfgmod.deposit_sources(cfg, today)
                     if s.get("basis", "net") == "net")
    if not configured:
        return None
    ex = cfg["settings"].get("exclude_accounts", [])
    start = today - timedelta(days=round(months * 30.44))
    # Income lands in checking, which is complete, so the analysis clamp does
    # not apply here.
    rows = income_only(window(conn, cfg, start, today, clamp=False), ex)
    if len(rows) < 2:
        return None
    observed = round(sum(t.amount_cents for t in rows) / months)
    drift = observed - configured
    return {
        "configured_monthly_cents": configured,
        "observed_monthly_cents": observed,
        "drift_cents": drift,
        "drift_pct": round(drift / configured * 100, 1),
        "months": months,
        "deposits": len(rows),
        "ok": abs(drift) <= configured * 0.10,
    }


def residual_savings(conn, cfg: dict, today: date, months: int = 3) -> dict:
    """Savings measured as income minus spending, not as a transfer.

    Most households never make a "savings transaction" - whatever is not spent
    simply stays in the account. Measuring the goal from Savings-category rows
    then reports 0% forever. Here the residual is the measure, and the goal
    restates as a spending ceiling: income minus the target is the most that can
    be spent without eating into it.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    start = today - timedelta(days=round(months * 30.44))
    floor = cfgmod.analysis_start(cfg)
    if floor and start < floor:
        start = floor
    days = (today - start).days + 1
    if days < 1:
        return {"days": 0, "monthly_income_cents": 0, "monthly_spend_cents": 0,
                "monthly_residual_cents": 0}

    spend = sum(abs(t.amount_cents)
                for t in spend_only(window(conn, cfg, start, today), ex))
    income = cfgmod.expected_income(cfg, start, today)
    scale = 30.44 / days
    m_income = round(income * scale)
    m_spend = round(spend * scale)
    return {
        "days": days,
        "start": start.isoformat(),
        "period_income_cents": income,
        "period_spend_cents": spend,
        "monthly_income_cents": m_income,
        "monthly_spend_cents": m_spend,
        "monthly_residual_cents": m_income - m_spend,
    }


def goal_contributions(txns: list[Transaction], goal: dict, claimed: set[str]) -> list[Transaction]:
    """Savings outflows belonging to this goal.

    A goal naming `account_match` takes only contributions whose account or
    description mention it, so two goals funded from two institutions never
    double-count the same dollar. A goal with no match claims whatever is left.
    """
    m = (goal.get("account_match") or "").strip().lower()
    out = []
    for t in txns:
        if t.id in claimed:
            continue
        if m and m not in f"{t.account} {t.merchant} {t.description}".lower():
            continue
        out.append(t)
    return out


def goal_status(conn, cfg: dict, goal: dict, today: date,
                claimed: set[str] | None = None) -> dict:
    """Is this goal on track, and what would it take to get there?"""
    claimed = claimed if claimed is not None else set()
    target = goal.get("target_cents", 0)
    tdate = cfgmod.goal_date(goal)
    asof = cfgmod.balance_as_of(goal)
    ex = cfg["settings"].get("exclude_accounts", [])

    # Current balance = stated balance + contributions observed since that date.
    contributed_since = 0
    if asof:
        rows = savings_only(window(conn, cfg, asof + timedelta(days=1), today, clamp=False), ex)
        mine = goal_contributions(rows, goal, claimed)
        contributed_since = sum(abs(t.amount_cents) for t in mine)
    current = goal.get("current_balance_cents", 0) + contributed_since

    # Observed pace, averaged over the goal's measurement window. A yearly IRA
    # contribution looked at over 3 months reads as either a huge month or three
    # empty ones; measured over 12 it reads as what it is.
    months = max(int(goal.get("measure_months") or 3), 1)
    recent = goal_contributions(
        savings_only(window(conn, cfg, today - timedelta(days=round(months * 30.44)), today,
                            clamp=False), ex), goal, claimed)
    for t in recent:
        claimed.add(t.id)
    observed_monthly = round(sum(abs(t.amount_cents) for t in recent) / months) if recent else 0

    planned = cfgmod.planned_monthly(cfg, goal, today)
    kind = cfgmod.goal_type(goal)
    income = cfgmod.monthly_income(cfg, today)

    out = {
        "id": goal.get("id", ""),
        "name": goal.get("name", "Savings goal"),
        "goal_type": kind,
        "priority": goal.get("priority", 99),
        "contribution_type": goal.get("contribution_type", "auto"),
        "percent_of_net_income": goal.get("percent_of_net_income"),
        "planned_monthly_cents": planned,
        "observed_monthly_cents": observed_monthly,
        "measure_months": months,
        "target_cents": target,
        "current_cents": current,
        "remaining_cents": max(target - current, 0) if target else 0,
        "pct_complete": round(current / target * 100, 1) if target else None,
        "target_date": tdate.isoformat() if tdate else None,
        "required_monthly_cents": None,
        "months_remaining": None,
        "on_track": None,
        "monthly_gap_cents": None,
        "projected_completion": None,
        "actual_percent_of_income": (round(observed_monthly / income * 100, 1)
                                     if income else None),
    }

    # ---- rate goal: the percentage is the goal ---------------------------
    if kind == "rate":
        required = planned or 0
        out["required_monthly_cents"] = required
        out["spending_ceiling_cents"] = max(income - required, 0)

        if cfgmod.savings_model(cfg) == "residual":
            res = residual_savings(conn, cfg, today, months)
            # With several rate goals the single household residual is shared
            # out in proportion to what each one asks for, so it is never
            # counted twice.
            all_rate = [g for g in cfgmod.goals(cfg, today)
                        if cfgmod.goal_type(g) == "rate"]
            total_req = sum(cfgmod.planned_monthly(cfg, g, today) or 0 for g in all_rate) or 1
            share = required / total_req if total_req else 1
            observed_monthly = round(res["monthly_residual_cents"] * share)
            out["observed_monthly_cents"] = observed_monthly
            out["actual_spend_monthly_cents"] = res["monthly_spend_cents"]
            out["measured_days"] = res["days"]
            out["savings_model"] = "residual"
            out["actual_percent_of_income"] = (
                round(observed_monthly / income * 100, 1) if income else None)
            out["overspend_monthly_cents"] = max(
                res["monthly_spend_cents"] - out["spending_ceiling_cents"], 0)
        else:
            out["savings_model"] = "transactions"
        out["target_percent_of_income"] = (
            goal.get("percent_of_net_income") if goal.get("contribution_type") == "percent"
            else (round(required / income * 100, 1) if income else None))
        if not required:
            out["note"] = ("No contribution set for this goal - choose a percentage of "
                           "after-tax income or a fixed monthly amount.")
            return out
        # Success is behavioral: did the money actually move, not will it by a date.
        out["on_track"] = observed_monthly >= required
        out["monthly_gap_cents"] = observed_monthly - required
        out["following_plan"] = out["on_track"]
        out["plan_vs_actual_cents"] = observed_monthly - required
        out["plan_covers_goal"] = True      # the plan is the goal, by definition
        out["plan_gap_cents"] = 0
        return out

    # ---- target goal: an amount by a date --------------------------------
    if not target or not tdate:
        out["note"] = "Set a target amount and date for this goal to track its pace."
        if planned is not None:
            out["following_plan"] = observed_monthly >= planned
            out["plan_vs_actual_cents"] = observed_monthly - planned
        return out

    months_left = max(months_between(today, tdate), 0.1)
    required = round(out["remaining_cents"] / months_left)
    out["months_remaining"] = round(months_left, 1)
    out["required_monthly_cents"] = required
    out["on_track"] = observed_monthly >= required
    out["monthly_gap_cents"] = observed_monthly - required

    if observed_monthly > 0:
        months_needed = out["remaining_cents"] / observed_monthly
        proj = today + timedelta(days=round(months_needed * 30.44))
        out["projected_completion"] = proj.isoformat()
        out["projected_slip_days"] = (proj - tdate).days

    if planned is not None:
        # Three different numbers, and conflating them hides the real problem:
        #   required - what the target and date demand
        #   planned  - what the household committed to put in
        #   observed - what actually moved
        # A plan below required means the goal misses even if followed perfectly.
        out["following_plan"] = observed_monthly >= planned
        out["plan_vs_actual_cents"] = observed_monthly - planned
        out["plan_covers_goal"] = planned >= required
        out["plan_gap_cents"] = planned - required
        if planned > 0:
            months_at_plan = out["remaining_cents"] / planned
            out["projected_at_plan"] = (
                today + timedelta(days=round(months_at_plan * 30.44))).isoformat()
    return out


def goals_status(conn, cfg: dict, today: date) -> list[dict]:
    """Every active goal, highest priority first.

    Goals are resolved in priority order and each claims its own contributions,
    so an unmatched catch-all goal cannot absorb a higher-priority goal's money.
    """
    claimed: set[str] = set()
    specific = [g for g in cfgmod.goals(cfg) if g.get("account_match")]
    general = [g for g in cfgmod.goals(cfg) if not g.get("account_match")]
    out = {}
    for g in specific + general:
        out[id(g)] = goal_status(conn, cfg, g, today, claimed)
    # Restore the caller-facing priority order.
    return [out[id(g)] for g in cfgmod.goals(cfg)]


def savings_status(conn, cfg: dict, today: date) -> dict:
    """The primary goal, or an empty shell when none is configured."""
    all_goals = goals_status(conn, cfg, today)
    if all_goals:
        return all_goals[0]
    return {"name": "Savings goal", "target_cents": 0, "current_cents": 0,
            "remaining_cents": 0, "pct_complete": None, "on_track": None,
            "observed_monthly_cents": 0, "required_monthly_cents": None,
            "note": "No savings goal configured. Add one with `python3 -m budget ui`."}


# ---------------------------------------------------------------- commitments


def verify_commitments(conn, cfg: dict, start: date, end: date) -> list[dict]:
    """Check each declared fixed expense against what actually posted.

    Fixed expenses are NOT added to spending - they already arrive in the
    checking CSV, and adding them would double-count. Declaring them buys
    something else: knowing when the mortgage did not post, or when the utility
    bill quietly went up.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    rows = [t for t in window(conn, cfg, start - timedelta(days=10), end + timedelta(days=10))
            if t.amount_cents < 0 and t.account not in ex]
    used: set[str] = set()
    out = []
    # Occurrences due before the analysis window cannot be matched - their
    # transactions are deliberately out of scope - so reporting them as MISSING
    # would invent a problem. The mortgage really did post; we just are not
    # looking at that week.
    floor = cfgmod.analysis_start(cfg)

    for x in cfgmod.fixed_expenses(cfg, end):
        match = (x.get("match") or x.get("name", "")).strip().lower()
        acct = (x.get("account") or "").strip().lower()
        expected = x.get("amount_cents", 0)
        for due in cfgmod.occurrences(x, start, end):
            if floor and due < floor:
                continue
            matches = [t for t in rows
                       if t.id not in used
                       and abs((t.date - due).days) <= 10
                       and (not match or match in f"{t.merchant} {t.description}".lower())
                       and (not acct or acct in t.account.lower())]
            # Prefer the candidate closest to the expected amount, then the date.
            matches.sort(key=lambda t: (abs(abs(t.amount_cents) - expected), abs((t.date - due).days)))
            hit = matches[0] if matches else None

            if hit:
                used.add(hit.id)
                actual = abs(hit.amount_cents)
                drift = actual - expected
                variable = x.get("variable", False)
                status = ("paid" if variable or not expected or abs(drift) <= max(expected * 0.02, 100)
                          else "drift")
                out.append({"name": x.get("name"), "category": x.get("category", ""),
                            "due": due.isoformat(), "status": status,
                            "expected_cents": expected, "actual_cents": actual,
                            "drift_cents": drift, "variable": variable,
                            "date": hit.date.isoformat(), "txn_id": hit.id,
                            "description": hit.description})
            elif due <= end:
                # Only call it missing once the due date has actually passed.
                status = "missing" if due < date.today() else "upcoming"
                out.append({"name": x.get("name"), "category": x.get("category", ""),
                            "due": due.isoformat(), "status": status,
                            "expected_cents": expected, "actual_cents": 0,
                            "drift_cents": 0, "variable": x.get("variable", False)})
    return sorted(out, key=lambda r: r["due"])


def month_to_date(conn, cfg: dict, today: date) -> dict:
    """The monthly free-to-spend budget and how much of it is gone.

    Scoped to the calendar month regardless of the report's own period, because
    the budget is monthly. Reports how many of the month's days are actually
    observed, since an analysis window starting mid-month means the spend figure
    is a floor, not a total - without that the percentage reads better than it is.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    m_start, m_end = month_bounds(today)
    floor = cfgmod.analysis_start(cfg)
    obs_start = max(m_start, floor) if floor else m_start

    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, today)}
    spend = spend_only(window(conn, cfg, obs_start, today), ex)
    disc = sum(abs(t.amount_cents) for t in spend
               if (t.category or "Uncategorized") not in committed)

    flow = cashflow(conn, cfg, m_start, min(m_end, today), today)
    free_m = flow["monthly"]["free_cents"]
    days_in_month = (m_end - m_start).days + 1
    days_observed = max((today - obs_start).days + 1, 0)
    days_elapsed = (today - m_start).days + 1

    return {
        "month": m_start.strftime("%B %Y"),
        "free_monthly_cents": free_m,
        "spent_cents": disc,
        "remaining_cents": free_m - disc,
        "pct_used": round(disc / free_m * 100, 1) if free_m else None,
        "days_in_month": days_in_month,
        "days_observed": days_observed,
        "days_elapsed": days_elapsed,
        "days_left": max((m_end - today).days, 0),
        "pct_month_observed": round(days_observed / days_in_month * 100),
        "partial": days_observed < days_elapsed,
    }


def monthly_history(conn, cfg: dict, today: date, months: int = 12) -> dict:
    """Complete months only, for month-over-month comparison.

    A month counts only when the analysis window covers all of it and the month
    has ended. Half a month plotted beside whole ones reads as a fall in
    spending that never happened, so partial months are excluded rather than
    shown with a caveat.
    """
    floor = cfgmod.analysis_start(cfg)
    ex = cfg["settings"].get("exclude_accounts", [])
    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, today)}

    rows = []
    cursor = today.replace(day=1)
    for _ in range(months):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        m_start, m_end = month_bounds(cursor)
        if m_end >= today:
            continue
        if floor and m_start < floor:
            continue          # window does not cover the whole month
        txns = window(conn, cfg, m_start, m_end)
        spend = spend_only(txns, ex)
        disc = sum(abs(t.amount_cents) for t in spend
                   if (t.category or "Uncategorized") not in committed)
        total = sum(abs(t.amount_cents) for t in spend)
        income = cfgmod.expected_income(cfg, m_start, m_end)
        target = sum(g["required_monthly_cents"] or 0
                     for g in goals_status(conn, cfg, m_end))
        free = income - (total - disc) - target
        rows.append({
            "month": m_start.strftime("%Y-%m"),
            "label": m_start.strftime("%b %Y"),
            "income_cents": income,
            "spend_cents": total,
            "committed_cents": total - disc,
            "discretionary_cents": disc,
            "free_budget_cents": free,
            "over_cents": max(disc - free, 0),
            "target_cents": target,
            "kept_cents": income - total,
        })
    rows.reverse()

    # When the first complete month will arrive, so the empty state can say so.
    first = None
    if not rows and floor:
        nxt = (floor.replace(day=1) if floor.day == 1
               else (floor.replace(day=1) + timedelta(days=32)).replace(day=1))
        first = (nxt + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return {"months": rows,
            "first_complete_month": first.strftime("%B %Y") if first else None,
            "analysis_start": floor.isoformat() if floor else None}


def spending_actions(conn, cfg: dict, rows: list[dict], mtd: dict, today: date) -> list[dict]:
    """What to do about spending right now, from the month's own numbers.

    Only categories where something is actually wrong, each with the merchant
    driving it - "Shopping is over" is a fact, "Shopping is over and Amazon is
    $458 of it across 6 orders" is something a household can act on.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    m_start, m_end = month_bounds(today)
    floor = cfgmod.analysis_start(cfg)
    obs_start = max(m_start, floor) if floor else m_start
    txns = spend_only(window(conn, cfg, obs_start, today), ex)

    left_days = max((m_end - today).days, 0)
    out = []
    for r in sorted(rows, key=lambda r: r["variance_cents"]):
        if r["status"] not in ("over", "at_risk"):
            continue
        cat_txns = [t for t in txns if (t.category or "Uncategorized") == r["category"]]
        merchants: dict[str, list] = defaultdict(list)
        for t in cat_txns:
            merchants[t.merchant.split()[0] if t.merchant else "?"].append(t)
        top = max(merchants.items(), key=lambda kv: sum(abs(t.amount_cents) for t in kv[1]),
                  default=(None, []))
        driver = None
        if top[0] and len(top[1]) >= 2:
            driver = {"merchant": top[0], "count": len(top[1]),
                      "total_cents": sum(abs(t.amount_cents) for t in top[1])}
        out.append({
            "category": r["category"],
            "status": r["status"],
            "spent_cents": r["actual_cents"],
            "budget_cents": r["budget_monthly_cents"],
            "over_cents": max(-r["variance_cents"], 0),
            "left_cents": max(r["variance_cents"], 0),
            "pct_used": r["pct_used"],
            "days_left": left_days,
            "driver": driver,
        })
    return out


def coverage(conn, cfg: dict, start: date, end: date, stale_days: int = 7) -> dict:
    """Which accounts actually have data for a period, and which look stale.

    A missing statement does not read as missing - it reads as a month where
    that card was not used, which quietly understates spending. So every known
    account is listed, and one whose newest transaction predates the period end
    is called out rather than assumed to be idle.
    """
    ex = set(cfg["settings"].get("exclude_accounts", []))
    rows = fetch(conn, None, end)
    if not rows:
        return {"accounts": [], "stale": [], "missing": [], "complete": True}

    latest: dict[str, date] = {}
    first: dict[str, date] = {}
    in_period: dict[str, list] = defaultdict(list)
    for t in rows:
        if t.account in ex:
            continue
        latest[t.account] = max(latest.get(t.account, t.date), t.date)
        first[t.account] = min(first.get(t.account, t.date), t.date)
        if start <= t.date <= end:
            in_period[t.account].append(t)

    out = []
    for acct in sorted(latest):
        txns = in_period.get(acct, [])
        last = latest[acct]
        behind = (end - last).days
        out.append({
            "account": acct,
            "last_transaction": last.isoformat(),
            "first_transaction": first[acct].isoformat(),
            "days_behind": behind,
            "txns_in_period": len(txns),
            "spend_in_period_cents": sum(abs(t.amount_cents) for t in txns
                                         if t.amount_cents < 0),
            "stale": behind > stale_days,
            "absent": not txns,
        })
    out.sort(key=lambda r: (-r["days_behind"], r["account"]))
    return {
        "accounts": out,
        "stale": [r["account"] for r in out if r["stale"]],
        "missing": [r["account"] for r in out if r["absent"]],
        "complete": not any(r["stale"] or r["absent"] for r in out),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
    }


def commitment_tracker(conn, cfg: dict, today: date) -> list[dict]:
    """One row per declared commitment: what it costs, when it last paid, when next.

    Distinct from verify_commitments, which checks occurrences falling inside a
    reporting period. This is the standing view - every commitment, always
    listed, so nothing quietly stops being paid. It reads full history because
    commitments are paid from checking, which is complete; the analysis clamp
    exists for partial card coverage and does not apply.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    rows = [t for t in fetch(conn, None, today)
            if t.amount_cents < 0 and t.account not in ex]
    out = []

    for x in cfgmod.fixed_expenses(cfg, today):
        match = (x.get("match") or x.get("name", "")).strip().lower()
        acct = (x.get("account") or "").strip().lower()
        expected = x.get("amount_cents", 0)
        cadence = x.get("cadence", "monthly")
        hits = [t for t in rows
                if (not match or match in f"{t.merchant} {t.description}".lower())
                and (not acct or acct in t.account.lower())]
        hits.sort(key=lambda t: t.date)

        every = round(365.25 / cfgmod.PER_YEAR.get(cadence, 12))
        last = hits[-1] if hits else None
        row = {
            "id": x.get("id"), "name": x.get("name"), "category": x.get("category", ""),
            "amount_cents": expected, "cadence": cadence,
            "monthly_cents": cfgmod.monthly_cents(expected, cadence),
            "account": x.get("account", ""), "variable": x.get("variable", False),
            "payments_seen": len(hits),
            "last_paid": last.date.isoformat() if last else None,
            "last_amount_cents": abs(last.amount_cents) if last else None,
            "next_due": None, "days_overdue": 0, "drift_cents": 0,
        }
        if not last:
            row["status"] = "never_seen"
            out.append(row)
            continue

        nxt = last.date + timedelta(days=every)
        row["next_due"] = nxt.isoformat()
        row["drift_cents"] = (0 if x.get("variable") or not expected
                              else abs(last.amount_cents) - expected)
        # A few days of slack: ACH timing moves a due date around.
        overdue_by = (today - nxt).days
        if overdue_by > 5:
            row["status"] = "overdue"
            row["days_overdue"] = overdue_by
        elif abs(row["drift_cents"]) > max(expected * 0.02, 100):
            row["status"] = "drift"
        else:
            row["status"] = "on_track"
        out.append(row)

    order = {"overdue": 0, "never_seen": 1, "drift": 2, "on_track": 3}
    return sorted(out, key=lambda r: (order.get(r["status"], 9), -r["monthly_cents"]))


def cashflow(conn, cfg: dict, start: date, end: date, today: date) -> dict:
    """Where the money is committed before anyone decides anything.

    The number a household actually needs: income, minus what is already
    promised to commitments and goals, is what is genuinely free to spend.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    days = (end - start).days + 1
    prorate = days / 30.44

    income_m = cfgmod.monthly_income(cfg, end)
    fixed_m = cfgmod.fixed_monthly_total(cfg, end)
    statuses = goals_status(conn, cfg, today)
    goal_req_m = sum(g["required_monthly_cents"] or 0 for g in statuses)
    # What actually leaves the account is the plan; a goal with no plan falls
    # back to what its target and date require.
    goal_plan_m = sum(g["planned_monthly_cents"] if g["planned_monthly_cents"] is not None
                      else (g["required_monthly_cents"] or 0) for g in statuses)
    free_m = income_m - fixed_m - goal_plan_m

    spend = spend_only(window(conn, cfg, start, end), ex)
    committed_cats = {x.get("category") for x in cfgmod.fixed_expenses(cfg, end) if x.get("category")}
    disc_actual = sum(abs(t.amount_cents) for t in spend
                      if (t.category or "Uncategorized") not in committed_cats)

    return {
        "monthly": {
            "income_cents": income_m,
            "income_basis": "net (after tax)",
            "fixed_cents": fixed_m,
            "goal_required_cents": goal_req_m,
            "goal_planned_cents": goal_plan_m,
            # Negative means the plan is short of what the goals actually need.
            "plan_shortfall_cents": goal_plan_m - goal_req_m,
            "free_cents": free_m,
            # The goal restated as a limit: the most that can be spent in a
            # month without eating into the target saving.
            "spending_ceiling_cents": max(income_m - goal_req_m, 0),
            "fixed_pct": round(fixed_m / income_m * 100, 1) if income_m else None,
            "savings_rate_pct": round(goal_plan_m / income_m * 100, 1) if income_m else None,
        },
        "period": {
            "days": days,
            "expected_income_cents": cfgmod.expected_income(cfg, start, end),
            "free_budget_cents": round(free_m * prorate),
            "discretionary_spent_cents": disc_actual,
            "discretionary_left_cents": round(free_m * prorate) - disc_actual,
            # Overspending the free allowance comes out of the savings target -
            # that is the whole point of the ceiling, so state what survives.
            "savings_target_cents": round(goal_req_m * prorate),
            "overspend_cents": max(disc_actual - round(free_m * prorate), 0),
            "savings_remaining_cents": (round(goal_req_m * prorate)
                                        - max(disc_actual - round(free_m * prorate), 0)),
        },
        "committed_categories": sorted(c for c in committed_cats if c),
    }


# ---------------------------------------------------------------- signals


def anomalies(conn, cfg: dict, start: date, end: date, lookback_weeks: int = 12) -> list[dict]:
    """Categories spending far above their own recent norm, plus one-off outliers."""
    ex = cfg["settings"].get("exclude_accounts", [])
    days = (end - start).days + 1
    hist_start = start - timedelta(weeks=lookback_weeks)
    hist = spend_only(window(conn, cfg, hist_start, start - timedelta(days=1)), ex)
    cur = spend_only(window(conn, cfg, start, end), ex)

    # Build comparable historical windows of the same length.
    buckets: dict[str, list[int]] = defaultdict(list)
    n_windows = max((start - hist_start).days // days, 1)
    for w in range(n_windows):
        w_end = start - timedelta(days=w * days + 1)
        w_start = w_end - timedelta(days=days - 1)
        per_cat: dict[str, int] = defaultdict(int)
        for t in hist:
            if w_start <= t.date <= w_end:
                per_cat[t.category or "Uncategorized"] += abs(t.amount_cents)
        for cat in set(per_cat) | {c for c in buckets}:
            buckets[cat].append(per_cat.get(cat, 0))

    found = []
    cur_by_cat = by_category(cur)
    for cat, amount in cur_by_cat.items():
        history = [v for v in buckets.get(cat, []) if v > 0]
        if len(history) < 3:
            continue
        med = statistics.median(history)
        if med <= 0:
            continue
        ratio = amount / med
        if ratio >= 1.75 and amount - med >= 5000:   # ignore noise under $50
            found.append({
                "type": "category_spike", "category": cat,
                "amount_cents": amount, "typical_cents": int(med),
                "ratio": round(ratio, 2),
                "excess_cents": int(amount - med),
            })

    large = cfg["settings"].get("large_transaction_cents", 20000)
    for t in sorted(cur, key=lambda t: t.amount_cents)[:5]:
        if abs(t.amount_cents) >= large:
            found.append({
                "type": "large_transaction", "category": t.category,
                "merchant": t.merchant, "description": t.description,
                "amount_cents": abs(t.amount_cents), "date": t.date.isoformat(),
            })

    # Merchants never seen before this period.
    known = {t.merchant for t in hist}
    for m in by_merchant(cur, limit=50):
        if m["merchant"] not in known and m["total_cents"] >= large // 2:
            found.append({"type": "new_merchant", **m})
    return found


def recurring(conn, cfg: dict, today: date, months: int = 4) -> list[dict]:
    """Detect subscriptions: same merchant, similar amount, 3+ distinct months."""
    ex = cfg["settings"].get("exclude_accounts", [])
    start = today - timedelta(days=months * 31)
    txns = spend_only(window(conn, cfg, start, today), ex)
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        groups[t.merchant].append(t)

    out = []
    for merchant, ts in groups.items():
        months_seen = {t.date.strftime("%Y-%m") for t in ts}
        if len(months_seen) < 3:
            continue
        amounts = [abs(t.amount_cents) for t in ts]
        med = statistics.median(amounts)
        if med == 0:
            continue
        # Stable amount => subscription; wildly varying => just a frequent merchant.
        spread = (max(amounts) - min(amounts)) / med
        if spread > 0.25:
            continue
        out.append({
            "merchant": merchant, "category": ts[0].category,
            "typical_cents": int(med), "months_seen": len(months_seen),
            "annualized_cents": int(med * 12),
            "last_seen": max(t.date for t in ts).isoformat(),
        })
    return sorted(out, key=lambda r: -r["typical_cents"])


def trend(conn, cfg: dict, today: date, periods: int = 8, unit: str = "week") -> list[dict]:
    """Spend/income/savings per period, oldest first, for the dashboard chart."""
    ex = cfg["settings"].get("exclude_accounts", [])
    floor = cfgmod.analysis_start(cfg)
    out = []
    for i in range(periods - 1, -1, -1):
        if unit == "week":
            ref = today - timedelta(weeks=i)
            s, e = week_bounds(ref)
            label = f"{s:%b %d}"
        else:
            ref = today.replace(day=1)
            for _ in range(i):
                ref = (ref - timedelta(days=1)).replace(day=1)
            s, e = month_bounds(ref)
            label = f"{s:%b}"
        if floor and e < floor:
            continue          # entirely before the window; plotting 0 would lie
        txns = window(conn, cfg, s, min(e, today))
        out.append({
            "label": label, "start": s.isoformat(), "end": e.isoformat(),
            "spend_cents": sum(abs(t.amount_cents) for t in spend_only(txns, ex)),
            "income_cents": sum(t.amount_cents for t in income_only(txns, ex)),
            "savings_cents": sum(abs(t.amount_cents) for t in savings_only(txns, ex)),
        })
    return out


# ---------------------------------------------------------------- report


def build_report(conn, cfg: dict, period: str = "week", today: date | None = None) -> dict:
    """The single structured payload the agent and the HTML dashboard both read."""
    today = today or date.today()
    start, end, label = resolve_period(period, today)
    ex = cfg["settings"].get("exclude_accounts", [])

    # Clamp the period to the analysable window, and say so. Reporting "last 30
    # days" while only 12 are in scope would make every prorated budget and the
    # daily burn rate wrong by the ratio between them.
    floor = cfgmod.analysis_start(cfg)
    clamped = False
    if floor and start < floor:
        start, clamped = floor, True
        label = f"{label} (from {floor.isoformat()})"

    txns = window(conn, cfg, start, end)
    spend = spend_only(txns, ex)
    income = income_only(txns, ex)
    saved = savings_only(txns, ex)
    retired = retirement_only(txns, ex)

    total_spend = sum(abs(t.amount_cents) for t in spend)
    total_income = sum(t.amount_cents for t in income)
    total_saved = sum(abs(t.amount_cents) for t in saved)
    total_retirement = sum(abs(t.amount_cents) for t in retired)

    _budget_rows = budget_status(conn, cfg, start, end)
    _mtd = month_to_date(conn, cfg, today)
    flow = cashflow(conn, cfg, start, end, today)
    expected_income = flow["period"]["expected_income_cents"] or total_income
    uncat = [t for t in txns if not t.category]

    return {
        "generated_at": date.today().isoformat(),
        "period": {"label": label, "kind": period_kind(period),
                   "start": start.isoformat(), "end": end.isoformat(),
                   "days": (end - start).days + 1,
                   "clamped_to_analysis_start": clamped},
        "household": cfg["household"]["name"],
        "totals": {
            "spend_cents": total_spend,
            "income_cents": total_income,
            "expected_income_cents": expected_income,
            "saved_cents": total_saved,
            "retirement_cents": total_retirement,
            # Retirement money really has left the account, so net must reflect
            # it even though it counts as neither spending nor goal savings.
            "net_cents": expected_income - total_spend - total_saved - total_retirement,
            "transactions": len(txns),
            "daily_burn_cents": round(total_spend / ((end - start).days + 1)),
        },
        "cashflow": flow,
        "commitments": verify_commitments(conn, cfg, start, end),
        "commitment_tracker": commitment_tracker(conn, cfg, today),
        "monthly_history": monthly_history(conn, cfg, today),
        "coverage": coverage(conn, cfg, start, end),
        "reminders": cfgmod.reminders(cfg, today),
        "month_to_date": _mtd,
        "spending_actions": spending_actions(conn, cfg, _budget_rows, _mtd, today),
        "free_spend_items": [
            {"date": t.date.isoformat(), "merchant": t.merchant,
             "description": t.description, "category": t.category,
             "account": t.account, "amount_cents": abs(t.amount_cents)}
            for t in sorted(
                (t for t in spend
                 if (t.category or "Uncategorized") not in
                 {x.get("category") for x in cfgmod.fixed_expenses(cfg, end)}),
                key=lambda t: -abs(t.amount_cents))
        ],
        "budget": _budget_rows,
        "savings": savings_status(conn, cfg, today),
        "goals": goals_status(conn, cfg, today),
        "top_merchants": by_merchant(spend, limit=12),
        "categories": [{"category": k, "amount_cents": v} for k, v in by_category(spend).items()],
        "anomalies": anomalies(conn, cfg, start, end),
        "recurring": recurring(conn, cfg, today),
        "trend": trend(conn, cfg, today, periods=8, unit="week"),
        "uncategorized": [
            {"id": t.id, "date": t.date.isoformat(), "merchant": t.merchant,
             "description": t.description, "amount_cents": t.amount_cents, "account": t.account}
            for t in uncat
        ],
        "income_check": income_check(conn, cfg, today),
        "config_warnings": cfgmod.validate(cfg) + _income_warning(conn, cfg, today),
    }


def _income_warning(conn, cfg: dict, today: date) -> list[str]:
    chk = income_check(conn, cfg, today)
    if not chk or chk["ok"]:
        return []
    direction = "above" if chk["drift_cents"] > 0 else "below"
    return [f"Configured income (${chk['configured_monthly_cents']/100:,.0f}/mo) is "
            f"{abs(chk['drift_pct']):.0f}% {direction} what actually arrived over the last "
            f"{chk['months']} months (${chk['observed_monthly_cents']/100:,.0f}/mo). "
            f"The spending ceiling is derived from it, so correct it in `budget ui`."]
