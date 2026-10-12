"""Where the money could come from, and what to do about it this week.

Everything here is deterministic and sourced from the ledger. The agent turns
these candidates into prose and picks which ones suit the household; it does not
invent savings or do the arithmetic.

The central correctness risk is double counting. "Cancel Netflix, save $23" and
"bring Entertainment back to its median, save $80" overlap if Netflix sits
inside Entertainment. So subscriptions are extracted first and category targets
are computed on the *variable* remainder only.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta

from . import analyze, config as cfgmod
from .analyze import window as fetch_window
from .schema import NON_SPEND, Transaction

# Categories a recommendation should never propose cutting wholesale. Telling a
# household to spend less on childcare or medical care is not budgeting advice.
UNTOUCHABLE = {"Housing", "Utilities", "Insurance", "Childcare", "Health", "Debt", "Education"}

# Subscriptions are judged more finely than categories. A gym or streaming
# membership filed under Health is discretionary even though a medical bill in
# the same category is not, so subscriptions here are surfaced but flagged for
# a human to confirm rather than silently dropped.
NO_SUBSCRIPTION_CUT = {"Housing", "Utilities", "Insurance", "Childcare", "Debt", "Education"}

DIFFICULTY_ORDER = {"easy": 0, "moderate": 1, "hard": 2}


def _months_back(today: date, n: int) -> tuple[date, date]:
    """The n complete months before the current one."""
    end = today.replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    for _ in range(n - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    return start, end


# Below this many days of analysable history, trailing averages and medians are
# not meaningful and the optimizer must say so rather than report zeros.
MIN_HISTORY_DAYS = 28


def _trailing(cfg: dict, today: date, n: int) -> tuple[date, date, float]:
    """The n complete months before this one, as the ledger can actually see them.

    Returns (start, end, months), where months is how much time the window
    really covers. `analysis_start` clamps the window, so dividing its total by
    n would spread 24 days of spending over three months and report every
    monthly figure several times too low. When the clamp leaves fewer than
    MIN_HISTORY_DAYS inside complete months, the window runs on through today
    so it holds every day of history there is.
    """
    start, end = _months_back(today, n)
    floor = cfgmod.analysis_start(cfg)
    if not floor or floor <= start:
        return start, end, n
    start = floor
    if (end - start).days + 1 < MIN_HISTORY_DAYS:
        end = today
    return start, end, max((end - start).days + 1, 1) / 30.44


def history_days(cfg: dict, today: date) -> int:
    """Days of ledger actually in scope for trailing comparisons."""
    floor = cfgmod.analysis_start(cfg)
    if not floor:
        return 10 ** 4
    return max((today - floor).days + 1, 0)


def has_enough_history(cfg: dict, today: date) -> bool:
    return history_days(cfg, today) >= MIN_HISTORY_DAYS


def _subscription_ids(conn, cfg, today) -> tuple[set[str], dict[str, dict]]:
    """Transaction ids belonging to detected subscriptions, keyed by merchant."""
    subs = {s["merchant"]: s for s in analyze.recurring(conn, cfg, today, months=5)}
    ex = cfg["settings"].get("exclude_accounts", [])
    start, end = _months_back(today, 5)
    ids = {t.id for t in analyze.spend_only(fetch_window(conn, cfg, start, today), ex)
           if t.merchant in subs}
    return ids, subs


# ------------------------------------------------------------------ candidates


def subscription_candidates(conn, cfg: dict, today: date) -> list[dict]:
    """Recurring charges. The easiest money in any budget: one action, forever."""
    _, subs = _subscription_ids(conn, cfg, today)
    out = []
    for m, s in subs.items():
        if s["category"] in NO_SUBSCRIPTION_CUT:
            continue
        needs_check = s["category"] == "Health"
        # A subscription last seen more than ~6 weeks ago may already be gone.
        stale = (today - date.fromisoformat(s["last_seen"])).days > 45
        out.append({
            "id": f"sub:{m}",
            "type": "subscription",
            "title": f"Cancel or downgrade {m}",
            "category": s["category"] or "Other",
            "merchant": m,
            "current_monthly_cents": s["typical_cents"],
            "target_monthly_cents": 0,
            "saving_monthly_cents": s["typical_cents"],
            "annual_cents": s["annualized_cents"],
            "difficulty": "easy" if not needs_check else "moderate",
            "confidence": "high" if not needs_check else "medium",
            "needs_confirmation": needs_check,
            "evidence": (f"{s['typical_cents']/100:,.2f} charged in each of "
                         f"{s['months_seen']} months, last on {s['last_seen']}"
                         + (" - may already be cancelled" if stale else "")
                         + (" - filed under Health; confirm it is not medical" if needs_check else "")),
            "facts": {"amount_cents": s["typical_cents"], "months_seen": s["months_seen"],
                      "last_seen": s["last_seen"], "stale": stale, "health": needs_check},
            "reversible": True,
        })
    return sorted(out, key=lambda c: -c["saving_monthly_cents"])


def fee_candidates(conn, cfg: dict, today: date) -> list[dict]:
    """Bank and card fees. Pure waste - nothing is consumed for the money."""
    ex = cfg["settings"].get("exclude_accounts", [])
    start, end, months = _trailing(cfg, today, 3)
    fees = [t for t in analyze.spend_only(fetch_window(conn, cfg, start, end), ex) if t.category == "Fees"]
    if not fees:
        return []
    total = sum(abs(t.amount_cents) for t in fees)
    monthly = round(total / months)
    if monthly < 500:
        return []
    merchants = ", ".join(sorted({t.merchant for t in fees})[:3])
    return [{
        "id": "fees",
        "type": "fees",
        "title": "Eliminate bank and card fees",
        "category": "Fees",
        "merchant": "",
        "current_monthly_cents": monthly,
        "target_monthly_cents": 0,
        "saving_monthly_cents": monthly,
        "annual_cents": monthly * 12,
        "difficulty": "easy",
        "confidence": "high",
        "evidence": f"{len(fees)} fee charges over {months:.1f} months ({merchants}) - nothing received in return",
        "facts": {"count": len(fees), "months": round(months, 1), "merchants": merchants},
        "reversible": True,
    }]


def category_candidates(conn, cfg: dict, today: date) -> list[dict]:
    """Discretionary categories running above their own recent normal.

    The target is the household's own trailing median, not an external ideal:
    a month they have already lived through is a target they have already proven
    is possible, which is a far easier argument than an arbitrary cut.
    Subscription spend is removed first so nothing is counted twice.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    sub_ids, _ = _subscription_ids(conn, cfg, today)
    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, today)}
    env = cfgmod.envelopes(cfg)

    start, _ = _months_back(today, 4)
    rows = [t for t in analyze.spend_only(fetch_window(conn, cfg, start, today), ex)
            if t.id not in sub_ids]

    per_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in rows:
        per_month[t.category or "Uncategorized"][t.date.strftime("%Y-%m")] += abs(t.amount_cents)

    this_month = today.strftime("%Y-%m")
    out = []
    for cat, months in per_month.items():
        if cat in UNTOUCHABLE or cat in committed or cat == "Uncategorized":
            continue
        history = [v for k, v in months.items() if k != this_month]
        if len(history) < 2:
            continue
        median = int(statistics.median(history))
        recent = max(history[-1:] or [0], default=0)
        current = int(statistics.mean(history[-2:])) if len(history) >= 2 else median

        envelope = env.get(cat)
        # Prefer the household's own median; fall back to a set envelope only
        # when it is tighter and they chose it themselves.
        target = min(median, envelope) if envelope else median
        saving = current - target
        if saving < 2000:            # under $20/month is not worth an action
            continue
        out.append({
            "id": f"cat:{cat}",
            "type": "category",
            "title": f"Bring {cat} back to {'your usual' if target == median else 'budget'}",
            "category": cat,
            "merchant": "",
            "current_monthly_cents": current,
            "target_monthly_cents": target,
            "saving_monthly_cents": saving,
            "annual_cents": saving * 12,
            "difficulty": "moderate" if target == median else "hard",
            "confidence": "high" if len(history) >= 3 else "medium",
            "evidence": (f"averaging {current/100:,.0f}/month recently vs a "
                         f"{median/100:,.0f} median over {len(history)} months"),
            "facts": {"current_cents": current, "median_cents": median,
                      "months": len(history), "to_budget": target != median},
            "reversible": True,
        })
    return sorted(out, key=lambda c: -c["saving_monthly_cents"])


def habit_candidates(conn, cfg: dict, today: date) -> list[dict]:
    """Frequent small purchases at one merchant - the classic slow leak."""
    ex = cfg["settings"].get("exclude_accounts", [])
    sub_ids, _ = _subscription_ids(conn, cfg, today)
    start, end, months = _trailing(cfg, today, 3)
    rows = [t for t in analyze.spend_only(fetch_window(conn, cfg, start, end), ex)
            if t.id not in sub_ids and t.category not in UNTOUCHABLE]

    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in rows:
        groups[t.merchant].append(t)

    out = []
    for merchant, ts in groups.items():
        per_month = len(ts) / months
        avg = statistics.mean(abs(t.amount_cents) for t in ts)
        monthly = round(sum(abs(t.amount_cents) for t in ts) / months)
        # A habit: frequent, individually small, and adds up.
        if per_month < 4 or avg > 5000 or monthly < 4000:
            continue
        saving = round(monthly / 2)
        out.append({
            "id": f"habit:{merchant}",
            "type": "habit",
            "title": f"Halve the {merchant} habit",
            "category": ts[0].category or "Other",
            "merchant": merchant,
            "current_monthly_cents": monthly,
            "target_monthly_cents": monthly - saving,
            "saving_monthly_cents": saving,
            "annual_cents": saving * 12,
            "difficulty": "moderate",
            "confidence": "medium",
            "evidence": (f"{per_month:.0f} visits a month averaging "
                         f"{avg/100:,.2f}, about {monthly/100:,.0f}/month"),
            "facts": {"per_month": round(per_month), "avg_cents": round(avg),
                      "monthly_cents": monthly},
            "reversible": True,
        })
    return sorted(out, key=lambda c: -c["saving_monthly_cents"])


def candidates(conn, cfg: dict, today: date) -> list[dict]:
    """Every optimization candidate, easiest and largest first."""
    all_c = (subscription_candidates(conn, cfg, today)
             + fee_candidates(conn, cfg, today)
             + category_candidates(conn, cfg, today)
             + habit_candidates(conn, cfg, today))

    # A habit inside a category already being cut would double count.
    cut_categories = {c["category"] for c in all_c if c["type"] == "category"}
    deduped = [c for c in all_c
               if not (c["type"] == "habit" and c["category"] in cut_categories)]
    return sorted(deduped, key=lambda c: (DIFFICULTY_ORDER.get(c["difficulty"], 3),
                                          -c["saving_monthly_cents"]))


# ------------------------------------------------------------------ the plan


def discretionary_levers(conn, cfg: dict, today: date) -> dict:
    """What every discretionary category is worth at 10%, 25% and 40% less.

    Candidates above only find spending that is abnormal. A household already
    living at its own normal has no anomalies to cut, but still has choices -
    and this is the honest menu of them: here is what you spend, here is what
    each level of restraint is worth. The household picks; the tool does not
    pretend a 25% cut is painless.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, today)}
    start, end, months = _trailing(cfg, today, 3)
    rows_tx = analyze.spend_only(fetch_window(conn, cfg, start, end), ex)

    per_cat: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for t in rows_tx:
        cat = t.category or "Uncategorized"
        per_cat[cat] += abs(t.amount_cents)
        counts[cat] += 1

    levers, disc_total, fixed_total = [], 0, 0
    for cat, total in sorted(per_cat.items(), key=lambda kv: -kv[1]):
        monthly = round(total / months)
        if cat in UNTOUCHABLE or cat in committed:
            fixed_total += monthly
            continue
        disc_total += monthly
        if monthly < 2000:
            continue
        levers.append({
            "category": cat,
            "monthly_cents": monthly,
            "txns_per_month": round(counts[cat] / months),
            "cut_10_cents": round(monthly * 0.10),
            "cut_25_cents": round(monthly * 0.25),
            "cut_40_cents": round(monthly * 0.40),
        })

    days = history_days(cfg, today)
    return {
        "categories": levers,
        "history_days": days,
        "sufficient_history": days >= MIN_HISTORY_DAYS,
        "discretionary_monthly_cents": disc_total,
        "committed_monthly_cents": fixed_total,
        # What the monthly figures were measured over, so the page can say so.
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_days": (end - start).days + 1,
        "complete_months": months == 3,
        "total_at_10_cents": sum(l["cut_10_cents"] for l in levers),
        "total_at_25_cents": sum(l["cut_25_cents"] for l in levers),
        "total_at_40_cents": sum(l["cut_40_cents"] for l in levers),
    }


def gap_analysis(conn, cfg: dict, today: date) -> dict:
    """How far short the plan is, and which cuts would close it."""
    statuses = analyze.goals_status(conn, cfg, today)
    flow = analyze.cashflow(conn, cfg, today.replace(day=1), today, today)["monthly"]

    required = sum(g["required_monthly_cents"] or 0 for g in statuses)
    planned = flow.get("goal_planned_cents", 0)
    # Measure the gap against what actually moved, not against what was intended.
    # For a rate goal the plan IS the goal, so comparing required to planned would
    # always read zero even if nothing was saved all quarter.
    observed = sum(g["observed_monthly_cents"] or 0 for g in statuses)
    gap = max(required - observed, 0)

    picks, running = [], 0
    for c in candidates(conn, cfg, today):
        if running >= gap and gap > 0:
            break
        picks.append(c)
        running += c["saving_monthly_cents"]

    # When named candidates cannot close the gap, say how deep an across-the-board
    # discretionary cut would have to go - or that no cut is enough.
    levers = discretionary_levers(conn, cfg, today)
    shortfall = max(gap - running, 0)
    depth = None
    if shortfall and levers["discretionary_monthly_cents"] and levers["sufficient_history"]:
        pct = shortfall / levers["discretionary_monthly_cents"] * 100
        depth = {"required_pct": round(pct, 1), "achievable": pct <= 100}

    primary = statuses[0] if statuses else None
    projection = None
    if primary and primary.get("remaining_cents") and (observed + running) > 0:
        months = primary["remaining_cents"] / (observed + running)
        arrival = today + timedelta(days=round(months * 30.44))
        projection = {
            "new_monthly_cents": observed + running,
            "arrival": arrival.isoformat(),
            "target_date": primary.get("target_date"),
            "on_time": bool(primary.get("target_date")
                            and arrival <= date.fromisoformat(primary["target_date"])),
            "months_saved": (
                round((date.fromisoformat(primary["projected_completion"]) - arrival).days / 30.44, 1)
                if primary.get("projected_completion") else None),
        }

    return {
        "goal_required_cents": required,
        "currently_planned_cents": planned,
        "currently_saving_cents": observed,
        "plan_vs_actual_cents": observed - planned,
        "gap_cents": gap,
        "identified_cents": running,
        "covers_gap": running >= gap,
        "uncovered_cents": max(gap - running, 0),
        "picks": picks,
        "cut_depth_needed": depth,
        "sufficient_history": levers["sufficient_history"],
        "history_days": levers["history_days"],
        "discretionary_monthly_cents": levers["discretionary_monthly_cents"],
        "projection": projection,
        "free_cents": flow.get("free_cents", 0),
    }


def next_week(conn, cfg: dict, today: date) -> dict:
    """A spendable allowance per category for the coming 7 days.

    Derived from what is left in this month's envelopes, not from a fresh weekly
    budget: by the 20th, an envelope already spent is spent, and an allowance
    that ignores that is fiction.
    """
    ex = cfg["settings"].get("exclude_accounts", [])
    m_start, m_end = analyze.month_bounds(today)
    env = cfgmod.envelopes(cfg)
    committed = {x.get("category") for x in cfgmod.fixed_expenses(cfg, today)}

    spent = analyze.by_category(analyze.spend_only(fetch_window(conn, cfg, m_start, today), ex))
    days_left = max((m_end - today).days, 1)
    window = min(7, days_left)
    month_days = (m_end - m_start).days + 1
    elapsed_pct = ((today - m_start).days + 1) / month_days * 100

    rows = []
    for cat, budget in sorted(env.items(), key=lambda kv: -kv[1]):
        if cat in committed or cat in UNTOUCHABLE:
            continue
        used = spent.get(cat, 0)
        left = budget - used
        allowance = max(round(left * window / days_left), 0)
        used_pct = used / budget * 100 if budget else 0
        # 80% of an envelope spent is fine on the 25th and alarming on the 8th.
        # Compare against how much of the month has actually gone by.
        if left < 0:
            status = "over"
        elif used_pct > elapsed_pct + 10:
            status = "tight"
        else:
            status = "ok"
        rows.append({
            "category": cat,
            "month_budget_cents": budget,
            "spent_cents": used,
            "remaining_cents": left,
            "week_allowance_cents": allowance,
            "status": status,
            "pct_used": round(used_pct),
            "pct_elapsed": round(elapsed_pct),
            "ahead_of_pace_pct": round(used_pct - elapsed_pct),
        })

    # The headline must equal the rows beneath it. Categories already overspent
    # contribute 0 to the allowance, and their overspend is reported separately
    # rather than silently netted off - otherwise the total disagrees with the
    # list and neither number can be trusted.
    over = [r for r in rows if r["remaining_cents"] < 0]
    return {
        "window_days": window,
        "days_left_in_month": days_left,
        "categories": rows,
        "total_allowance_cents": sum(r["week_allowance_cents"] for r in rows),
        "total_remaining_cents": sum(max(r["remaining_cents"], 0) for r in rows),
        "overspent_cents": sum(-r["remaining_cents"] for r in over),
        "overspent_categories": [r["category"] for r in over],
        "pct_elapsed": round(elapsed_pct),
    }


def next_month(conn, cfg: dict, today: date) -> dict:
    """Envelope targets for next month that deliver the identified savings."""
    gap = gap_analysis(conn, cfg, today)
    env = cfgmod.envelopes(cfg)
    baseline = analyze.propose_budget(conn, cfg, today, months=3)

    cuts: dict[str, int] = defaultdict(int)
    for c in gap["picks"]:
        cuts[c["category"]] += c["saving_monthly_cents"]

    rows = []
    for cat in sorted(set(env) | set(cuts) | set(baseline), key=lambda c: -cuts.get(c, 0)):
        # Skip untouchable categories only when nothing specific was picked from
        # them; otherwise the envelope total would not match identified savings.
        if cat in UNTOUCHABLE and not cuts.get(cat):
            continue
        current = env.get(cat) or baseline.get(cat, 0)
        cut = cuts.get(cat, 0)
        if not current and not cut:
            continue
        proposed = max(current - cut, 0)
        rows.append({
            "category": cat,
            "current_cents": current,
            "proposed_cents": proposed,
            "change_cents": proposed - current,
            "actions": [c["title"] for c in gap["picks"] if c["category"] == cat],
            "action_ids": [c["id"] for c in gap["picks"] if c["category"] == cat],
        })

    changed = [r for r in rows if r["change_cents"]]
    return {
        "envelopes": rows,
        "changed": changed,
        "total_cut_cents": sum(-r["change_cents"] for r in changed),
        "new_contribution_cents": gap["currently_planned_cents"] + gap["identified_cents"],
    }


def build(conn, cfg: dict, today: date | None = None, period: str = "month") -> dict:
    """The full recommendation payload the HTML page and the agent both read."""
    today = today or date.today()
    report = analyze.build_report(conn, cfg, period, today)
    gap = gap_analysis(conn, cfg, today)
    return {
        "generated_at": today.isoformat(),
        "household": cfg["household"]["name"],
        "report": report,
        "gap": gap,
        "candidates": candidates(conn, cfg, today),
        "levers": discretionary_levers(conn, cfg, today),
        "next_week": next_week(conn, cfg, today),
        "next_month": next_month(conn, cfg, today),
        "goals": report["goals"],
        "cashflow": report["cashflow"],
    }
