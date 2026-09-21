"""The recommendations page: summary, what can be optimized, what to do next.

Reuses the dashboard's design tokens so the two pages read as one system, and
stays a single self-contained file with no external assets so it can be emailed.

All wording comes from budget.i18n, and every sentence is composed here from the
structured `facts` the optimizer emits - the data layer never produces prose.
"""

from __future__ import annotations

from .i18n import Translator
from .report_html import CSS, ICON, e

EXTRA_CSS = """
.hero-gap{font-size:40px;font-weight:650;letter-spacing:-.025em;line-height:1.1;margin:6px 0 4px}
.derive{margin:20px 0 0;font-size:13.5px}
.derive .r{display:grid;grid-template-columns:1fr auto;gap:14px;padding:8px 0;align-items:baseline}
.derive .r .lbl{color:var(--text-2)}
.derive .r .lbl b{color:var(--text);font-weight:600}
.derive .r .how{display:block;font-size:12px;color:var(--muted);margin-top:2px}
.derive .r .amt{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--text-2)}
.derive .r.sum{border-top:1px solid var(--border);margin-top:2px}
.derive .r.sum .lbl b,.derive .r.sum .amt{color:var(--text);font-weight:600}
.derive .r.final{border-top:2px solid var(--axis);margin-top:2px;padding-top:11px}
.derive .r.final .lbl b{font-size:14.5px}
.derive .r.final .amt{font-size:17px;font-weight:650;color:var(--text)}
.searchbar{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:10px 0 9px;
  background:var(--track)}
.searchbar i{display:block;height:100%}
.verdict{border-left:3px solid var(--critical);background:var(--surface);border-radius:8px;
  padding:14px 16px;margin:16px 0 0;font-size:14px;line-height:1.55;color:var(--text-2)}
.verdict.ok{border-left-color:var(--good)}
.verdict.warn{border-left-color:var(--warning)}
.verdict b{color:var(--text)}
.cand{display:grid;grid-template-columns:1fr 112px;gap:14px;align-items:start;
  padding:13px 0;border-bottom:1px solid var(--border)}
.cand:last-child{border-bottom:0}
.cand .t{font-size:14.5px;font-weight:600;margin-bottom:3px}
.cand .ev{font-size:12.5px;color:var(--muted);line-height:1.45}
.cand .amt{text-align:right}
.cand .amt b{font-size:15px;font-weight:650;display:block}
.cand .amt span{font-size:11.5px;color:var(--muted)}
.cand .tags{margin-top:7px;display:flex;gap:6px;flex-wrap:wrap}
.split{display:flex;height:26px;border-radius:6px;overflow:hidden;margin:6px 0 10px}
.split i{display:block;height:100%}
.splitkey{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--text-2)}
.splitkey span{display:inline-flex;align-items:center;gap:6px}
.lever td.n b{color:var(--text)}
.lever tr.tot td{font-weight:650;border-top:1px solid var(--axis);border-bottom:0}
.lever tr.tot td.n{color:var(--text)}
.wk{display:grid;grid-template-columns:1fr 108px 108px;gap:12px;align-items:center;
  padding:11px 0;border-bottom:1px solid var(--border);font-size:13.5px}
.wk:last-child{border-bottom:0}
.wk .n{text-align:right;font-variant-numeric:tabular-nums}
.wk .n b{font-size:15px}
.wkhead{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  font-weight:600;border-bottom:1px solid var(--border);padding-bottom:8px}
.arrow{display:grid;grid-template-columns:1fr 96px 24px 96px;gap:10px;align-items:center;
  padding:10px 0;border-bottom:1px solid var(--border);font-size:13.5px}
.arrow:last-child{border-bottom:0}
.arrow .n{text-align:right;font-variant-numeric:tabular-nums}
.arrow .ar{text-align:center;color:var(--muted)}
.beforeafter{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:center;
  margin-top:8px}
.ba{text-align:center;padding:16px 10px;background:var(--plane);border-radius:10px;
  border:1px solid var(--border)}
.ba .l{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.ba .v{font-size:22px;font-weight:650;margin-top:4px;letter-spacing:-.01em}
.ba .s{font-size:12px;color:var(--text-2);margin-top:2px}
.baarrow{font-size:22px;color:var(--muted)}
.tot{display:flex;gap:26px;flex-wrap:wrap;padding-top:14px;margin-top:10px;
  border-top:1px solid var(--border)}
.tot .l{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tot .v{font-size:21px;font-weight:650;margin-top:2px}
@media (max-width:560px){
  .beforeafter{grid-template-columns:1fr;gap:10px}
  .baarrow{transform:rotate(90deg)}
  .wk{grid-template-columns:1fr 92px}.wk .third{display:none}
  .arrow{grid-template-columns:1fr 78px 20px 78px;gap:6px;font-size:12.5px}
}
"""

# Chinese text needs a CJK-capable stack, a little more line height, and no
# negative tracking - tightening CJK glyphs makes them collide rather than
# look crisp. Uppercase/letter-spacing tricks do nothing useful for Han either.
CJK_CSS = """
body{font-family:system-ui,-apple-system,"PingFang SC","Hiragino Sans GB",
  "Microsoft YaHei","Noto Sans CJK SC","Source Han Sans SC",sans-serif;
  line-height:1.7}
h1,.hero-gap,.ba .v,.kpi .value,.tot .v{letter-spacing:0}
h2,.wkhead,.ba .l,.tot .l{text-transform:none;letter-spacing:.02em;font-size:13px}
.verdict,.note,.cand .ev,.derive{line-height:1.75}
.cand{grid-template-columns:1fr 124px}
.wk{grid-template-columns:1fr 118px 118px}
.arrow{grid-template-columns:1fr 104px 24px 104px}
.bname{font-size:14px}
"""

DIFF_KEY = {"easy": ("good", "easy"), "moderate": ("warning", "moderate"),
            "hard": ("critical", "hard")}


def chip(status: str, label: str) -> str:
    """Status is always icon + word, so hue never carries the meaning alone."""
    color = {"good": "var(--good)", "critical": "var(--critical)",
             "warning": "var(--warning)", "serious": "var(--serious)"}.get(status, "var(--muted)")
    return (f'<span class="chip" style="color:{color}">{ICON.get(status, ICON["muted"])}'
            f'<span style="color:var(--text)">{e(label)}</span></span>')


# ------------------------------------------------------------------ candidates


def candidate_text(c: dict, t: Translator) -> tuple[str, str]:
    """Compose a candidate's title and evidence in the active language."""
    f = c.get("facts") or {}
    kind = c["type"]
    if kind == "subscription":
        title = t("cand_sub_title", merchant=c["merchant"])
        ev = t("cand_sub_ev", amount=t.money(f.get("amount_cents", 0)),
               months=f.get("months_seen", 0), last=t.date(f.get("last_seen", "")))
        if f.get("stale"):
            ev += t("cand_sub_stale")
        if f.get("health"):
            ev += t("cand_sub_health")
        return title, ev
    if kind == "fees":
        return (t("cand_fee_title"),
                t("cand_fee_ev", count=f.get("count", 0), months=f.get("months", 3),
                  merchants=f.get("merchants", "")))
    if kind == "category":
        key = "cand_cat_title_budget" if f.get("to_budget") else "cand_cat_title_usual"
        return (t(key, category=t.category(c["category"])),
                t("cand_cat_ev", current=t.money(f.get("current_cents", 0)),
                  median=t.money(f.get("median_cents", 0)), months=f.get("months", 0)))
    if kind == "habit":
        return (t("cand_habit_title", merchant=c["merchant"]),
                t("cand_habit_ev", per_month=f.get("per_month", 0),
                  avg=t.money(f.get("avg_cents", 0)), monthly=t.money(f.get("monthly_cents", 0))))
    return c.get("title", ""), c.get("evidence", "")


# ------------------------------------------------------------------ blocks


def _gap_block(gap: dict, levers: dict, goals: list[dict], t: Translator,
               income: int = 0) -> str:
    """Lead with the answer, then show every number that produced it.

    An unexplained shortfall is not a finding, it is an assertion. The reader has
    to be able to follow the arithmetic from their own goal dates, or they cannot
    check it and will not act on it.
    """
    g = gap.get("gap_cents", 0)
    dated = [x for x in goals if x.get("required_monthly_cents")]

    if not goals:
        return ('<div class="card"><h2>' + t("on_track_q") + '</h2>'
                f'<div class="hero-gap" style="color:var(--muted)">{t("no_goals")}</div>'
                f'<div class="hero-sub">{t("no_goals_sub")}</div></div>')
    if not dated:
        return ('<div class="card"><h2>' + t("on_track_q") + '</h2>'
                f'<div class="hero-gap" style="color:var(--muted)">{t("no_dates")}</div>'
                f'<div class="hero-sub">{t("no_dates_sub")}</div></div>')
    if not g:
        return ('<div class="card"><h2>' + t("on_track_q") + '</h2>'
                f'<div class="hero-gap" style="color:var(--success-text)">{t("on_track_yes")}</div>'
                f'<div class="hero-sub">{t("on_track_yes_sub")}</div></div>')

    suffix = "" if t.is_cjk else "/mo"
    rows = []
    for x in dated:
        if x.get("goal_type") == "rate":
            pct = x.get("target_percent_of_income")
            how = (t("goal_row_rate", pct=f"{pct:g}", income=t.money(income))
                   if pct is not None else t("goal_row_rate_fixed"))
        else:
            how = t("goal_row_how", amount=t.money(x["remaining_cents"]),
                    months=f'{x["months_remaining"]:g}')
        rows.append(
            f'<div class="r"><div class="lbl">{e(x["name"])}'
            f'<span class="how">{how}</span></div>'
            f'<div class="amt">{t.money(x["required_monthly_cents"])}{suffix}</div></div>')

    # A rate goal has no date, so date language would be simply untrue.
    all_rate = all(x.get("goal_type") == "rate" for x in dated)
    if all_rate:
        need_label = (t("goals_need_rate_one") if len(dated) == 1
                      else t("goals_need_rate_many", n=len(dated)))
    else:
        need_label = (t("goals_need_one") if len(dated) == 1
                      else t("goals_need_many", n=len(dated)))
    rows.append(
        f'<div class="r sum"><div class="lbl"><b>{need_label}</b></div>'
        f'<div class="amt">{t.money(gap["goal_required_cents"])}{suffix}</div></div>')

    residual = any(x.get("savings_model") == "residual" for x in dated)
    days = next((x.get("measured_days") for x in dated if x.get("measured_days")), 0)
    rows.append(
        f'<div class="r"><div class="lbl">'
        f'{t("you_keeping") if residual else t("you_saving")}'
        f'<span class="how">'
        f'{t("keeping_how", days=days) if residual else t("saving_how")}</span></div>'
        f'<div class="amt">&minus;{t.money(gap.get("currently_saving_cents", 0))}{suffix}</div>'
        f'</div>')

    rows.append(
        f'<div class="r final"><div class="lbl"><b>{t("short_every_month")}</b></div>'
        f'<div class="amt">{t.money(g)}{suffix}</div></div>')

    found = gap["identified_cents"]
    pct = min(found / g * 100, 100) if g else 0
    search = (
        f'<h2 style="margin-top:26px">{t("can_it_come_q")}</h2>'
        f'<p class="note" style="margin:0 0 4px">{t("searching", amount=t.money(g))}</p>'
        f'<div class="searchbar" role="img" aria-label="{pct:.0f}%">'
        f'<i style="width:{pct:.1f}%;background:var(--fill)"></i></div>'
        f'<div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap">'
        f'<span class="note">{t("found_listed", amount=t.money(found))}</span>'
        f'<span class="note">{t("not_accounted", amount=t.money(gap["uncovered_cents"]))}</span>'
        f'</div>')

    depth = gap.get("cut_depth_needed") or {}
    req = depth.get("required_pct")
    if not gap.get("sufficient_history", True) and not gap["covers_gap"]:
        # Saying "no amount of restraint closes it" off a zero baseline would be
        # a confident claim built on missing data.
        verdict = ('<div class="verdict warn">'
                   + t("verdict_no_history", days=gap.get("history_days", 0)) + "</div>")
    elif gap["covers_gap"]:
        verdict = f'<div class="verdict ok">{t("verdict_covers")}</div>'
    elif req is not None and req <= 25:
        verdict = ('<div class="verdict warn">'
                   + t("verdict_tight", amount=t.money(gap["uncovered_cents"]), pct=f"{req:g}")
                   + "</div>")
    elif req is not None and depth.get("achievable"):
        verdict = ('<div class="verdict">'
                   + t("verdict_deep", amount=t.money(gap["uncovered_cents"]), pct=f"{req:g}")
                   + "</div>")
    else:
        verdict = ('<div class="verdict">'
                   + t("verdict_impossible",
                       amount=t.money(levers["discretionary_monthly_cents"])) + "</div>")

    return (
        f'<div class="card"><h2>{t("on_track_q")}</h2>'
        f'<div class="hero-gap">{t("short_hero", amount=t.money(g))}</div>'
        f'<div class="hero-sub">{t("short_sub_rate" if all_rate else "short_sub")}</div>'
        f'<div class="derive">{"".join(rows)}</div>{search}{verdict}</div>')


def _summary_block(rep: dict, levers: dict, t: Translator) -> str:
    committed = levers["committed_monthly_cents"]
    disc = levers["discretionary_monthly_cents"]
    total = committed + disc or 1
    cp = committed / total * 100
    split = (
        f'<div class="split">'
        f'<i style="width:{cp:.1f}%;background:var(--s2)"></i>'
        f'<i style="width:2px;background:var(--surface)"></i>'
        f'<i style="width:{100-cp:.1f}%;background:var(--fill)"></i></div>'
        f'<div class="splitkey">'
        f'<span><i class="sw" style="background:var(--s2)"></i>'
        + t("committed_key", amount=t.money(committed), pct=f"{cp:.0f}") + '</span>'
        f'<span><i class="sw" style="background:var(--fill)"></i>'
        + t("discretionary_key", amount=t.money(disc), pct=f"{100-cp:.0f}") + '</span></div>')

    cats = [c for c in rep["categories"] if c["amount_cents"]][:8]
    scale = max([c["amount_cents"] for c in cats] + [1])
    bars = "".join(
        f'<div class="brow"><div class="bname">{e(t.category(c["category"]))}</div>'
        f'<div class="bcell"><div style="height:10px"><i style="display:block;height:10px;'
        f'width:{c["amount_cents"]/scale*100:.1f}%;background:var(--fill);border-radius:5px"></i>'
        f'</div></div><div class="bnum"><b>{t.money(c["amount_cents"])}</b></div></div>'
        for c in cats)

    return (
        f'<div class="card"><h2>{t("summary_h")}</h2>'
        f'<p class="note" style="margin:0 0 8px">{t("typical_month")}</p>'
        f'{split}'
        f'<p class="note" style="margin:4px 0 20px">{t("only_discretionary")}</p>'
        f'<p class="note" style="margin:0 0 10px">'
        + t("period_actual", period=e(t.period(rep["period"]))) + '</p>'
        + bars + "</div>")


def _candidates_block(cands: list[dict], gap: dict, t: Translator) -> str:
    if not cands:
        key = "no_candidates_history" if not gap.get("sufficient_history", True) else "no_candidates"
        return (f'<div class="card"><h2>{t("where_from_h")}</h2>'
                f'<p class="note">{t(key)}</p></div>')
    picked = {c["id"] for c in gap.get("picks", [])}
    rows = []
    for c in cands:
        title, ev = candidate_text(c, t)
        tone, word = DIFF_KEY.get(c["difficulty"], ("muted", c["difficulty"]))
        tags = [chip(tone, t(word))]
        if c.get("needs_confirmation"):
            tags.append(chip("warning", t("confirm_first")))
        if c["id"] in picked:
            tags.append(chip("good", t("in_the_plan")))
        rows.append(
            f'<div class="cand"><div><div class="t">{e(title)}</div>'
            f'<div class="ev">{e(ev)}</div>'
            f'<div class="tags">{"".join(tags)}</div></div>'
            f'<div class="amt"><b>{t.money(c["saving_monthly_cents"])}</b>'
            f'<span>{t("per_mo_per_yr", annual=t.money(c["annual_cents"]))}</span></div></div>')
    total = sum(c["saving_monthly_cents"] for c in cands)
    return (f'<div class="card"><h2>{t("where_from_h")}</h2>'
            f'<p class="note" style="margin:0 0 6px">{t("where_from_sub")}</p>'
            + "".join(rows) +
            f'<div class="cand" style="border-top:1px solid var(--axis);border-bottom:0;'
            f'margin-top:6px"><div class="t">{t("all_of_above")}</div>'
            f'<div class="amt"><b style="color:var(--success-text)">{t.money(total)}</b>'
            f'<span>{t("per_mo_per_yr", annual=t.money(total*12))}</span></div></div></div>')


def _levers_block(levers: dict, t: Translator) -> str:
    if not levers["categories"]:
        return ""
    rows = "".join(
        f'<tr><td>{e(t.category(l["category"]))}</td>'
        f'<td class="n"><b>{t.money(l["monthly_cents"])}</b></td>'
        f'<td class="n">{t.money(l["cut_10_cents"])}</td>'
        f'<td class="n">{t.money(l["cut_25_cents"])}</td>'
        f'<td class="n">{t.money(l["cut_40_cents"])}</td>'
        f'<td class="n">{l["txns_per_month"]}</td></tr>'
        for l in levers["categories"])
    return (
        f'<div class="card"><h2>{t("levers_h")}</h2>'
        f'<p class="note" style="margin:0 0 14px">{t("levers_sub")}</p>'
        f'<table class="lever"><thead><tr><th>{t("col_category")}</th>'
        f'<th class="n">{t("col_now")}</th>'
        '<th class="n">&minus;10%</th><th class="n">&minus;25%</th><th class="n">&minus;40%</th>'
        f'<th class="n">{t("col_buys")}</th></tr></thead>'
        f'<tbody>{rows}'
        f'<tr class="tot"><td>{t("total_discretionary")}</td>'
        f'<td class="n">{t.money(levers["discretionary_monthly_cents"])}</td>'
        f'<td class="n">{t.money(levers["total_at_10_cents"])}</td>'
        f'<td class="n">{t.money(levers["total_at_25_cents"])}</td>'
        f'<td class="n">{t.money(levers["total_at_40_cents"])}</td><td></td></tr>'
        '</tbody></table></div>')


def _week_block(wk: dict, t: Translator) -> str:
    if not wk["categories"]:
        return f'<div class="card"><h2>{t("week_h")}</h2><p class="note">{t("week_no_env")}</p></div>'
    rows = [f'<div class="wk wkhead"><div>{t("col_category")}</div>'
            f'<div class="n">{t("col_left_month")}</div>'
            f'<div class="n third">{t("col_next7")}</div></div>']
    for r in wk["categories"]:
        if r["status"] == "over":
            tag = chip("critical", t("over_by", amount=t.money(abs(r["remaining_cents"]))))
        elif r["status"] == "tight":
            tag = chip("warning", t("used_ahead", pct=r["pct_used"], pts=r["ahead_of_pace_pct"]))
        else:
            tag = chip("good", t("used", pct=r["pct_used"]))
        tone = "var(--critical)" if r["status"] == "over" else "var(--text)"
        rows.append(
            f'<div class="wk"><div><div style="font-weight:600">{e(t.category(r["category"]))}</div>'
            f'<div style="margin-top:5px">{tag}</div></div>'
            f'<div class="n"><b style="color:{tone}">'
            f'{t.money(r["remaining_cents"], sign=True)}</b></div>'
            f'<div class="n third"><b>{t.money(r["week_allowance_cents"])}</b></div></div>')
    over = ""
    if wk.get("overspent_cents"):
        names = "、".join(t.category(c) for c in wk["overspent_categories"]) if t.is_cjk \
            else ", ".join(wk["overspent_categories"])
        over = (f'<div><div class="l">{t("already_over")}</div>'
                f'<div class="v" style="color:var(--critical)">'
                f'{t.money(wk["overspent_cents"])}</div>'
                f'<div style="font-size:12px;color:var(--text-2);margin-top:2px">{e(names)}</div></div>')
    return (
        f'<div class="card"><h2>{t("week_h")}</h2>'
        f'<p class="note" style="margin:0 0 6px">'
        + t("week_sub", days=wk["days_left_in_month"], pct=wk["pct_elapsed"]) + '</p>'
        + "".join(rows) +
        f'<div class="tot"><div><div class="l">{t("spendable_week")}</div>'
        f'<div class="v">{t.money(wk["total_allowance_cents"])}</div></div>{over}</div></div>')


def _month_block(nm: dict, cands: list[dict], t: Translator) -> str:
    changed = nm["changed"]
    if not changed:
        return ""
    titles = {c["id"]: candidate_text(c, t)[0] for c in cands}
    sep = "、" if t.is_cjk else "; "
    rows = "".join(
        f'<div class="arrow"><div><div style="font-weight:600">{e(t.category(r["category"]))}</div>'
        + (f'<div style="font-size:12px;color:var(--muted);margin-top:3px">'
           f'{e(sep.join(titles.get(i, "") for i in r.get("action_ids", [])))}</div>'
           if r.get("action_ids") else "")
        + f'</div><div class="n">{t.money(r["current_cents"])}</div>'
          f'<div class="ar">&rarr;</div>'
          f'<div class="n"><b>{t.money(r["proposed_cents"])}</b></div></div>'
        for r in changed)
    return (
        f'<div class="card"><h2>{t("month_h")}</h2>'
        f'<p class="note" style="margin:0 0 10px">{t("month_sub")}</p>{rows}'
        f'<div class="tot">'
        f'<div><div class="l">{t("freed_per_month")}</div>'
        f'<div class="v" style="color:var(--success-text)">{t.money(nm["total_cut_cents"])}</div></div>'
        f'<div><div class="l">{t("new_contribution")}</div>'
        f'<div class="v">{t.money(nm["new_contribution_cents"])}</div></div></div></div>')


def _effect_block(gap: dict, goals: list[dict], t: Translator) -> str:
    proj = gap.get("projection")
    if not proj or not goals:
        return ""
    primary = goals[0]
    before = primary.get("projected_completion") or primary.get("projected_at_plan")
    if not before:
        return ""
    saved = proj.get("months_saved")
    tone = "var(--success-text)" if proj.get("on_time") else "var(--text)"
    tail = (chip("good", t("arrives_on_time")) if proj.get("on_time")
            else chip("warning", t("still_target", date=t.date(primary.get("target_date") or ""))))
    return (
        f'<div class="card"><h2>{t("effect_h", goal=e(primary["name"]))}</h2>'
        '<div class="beforeafter">'
        f'<div class="ba"><div class="l">{t("doing_nothing")}</div>'
        f'<div class="v">{e(t.date(before))}</div>'
        f'<div class="s">{t("at_rate", amount=t.money(gap["currently_planned_cents"]))}</div></div>'
        f'<div class="baarrow">&rarr;</div>'
        f'<div class="ba"><div class="l">{t("with_changes")}</div>'
        f'<div class="v" style="color:{tone}">{e(t.date(proj["arrival"]))}</div>'
        f'<div class="s">{t("at_rate", amount=t.money(proj["new_monthly_cents"]))}</div></div></div>'
        + (f'<p class="note" style="margin:14px 0 0">'
           + t("months_earlier", months=f"{saved:g}",
               date=t.date(proj.get("target_date") or "")) + f' {tail}</p>' if saved else "")
        + "</div>")


# ------------------------------------------------------------------ page


def render(data: dict, lang: str = "en", currency: str = "USD") -> str:
    t = Translator(lang, currency)
    rep, gap, levers = data["report"], data["gap"], data["levers"]
    cjk = CJK_CSS if t.is_cjk else ""
    return f"""<!DOCTYPE html>
<html lang="{e(t.lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t("page_title", household=e(data["household"]))}</title>
<style>{CSS}{EXTRA_CSS}{cjk}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>{t("h1")}</h1>
    <div class="sub">{t("subhead", household=e(data["household"]),
                        period=e(t.period(rep["period"])), date=e(t.date(data["generated_at"])))}</div>
  </header>

  {_gap_block(gap, levers, data["goals"], t, data["cashflow"]["monthly"]["income_cents"])}
  {_summary_block(rep, levers, t)}
  {_candidates_block(data["candidates"], gap, t)}
  {_levers_block(levers, t)}
  {_week_block(data["next_week"], t)}
  {_month_block(data["next_month"], data["candidates"], t)}
  {_effect_block(gap, data["goals"], t)}

  <footer>{t("footer")}</footer>
</div>
</body>
</html>"""
