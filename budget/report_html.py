"""Self-contained HTML dashboard.

No external assets: inline SVG and one <style> block, so the file opens
offline and survives being pasted into an email body later.

Palette is the validated default from the dataviz reference: categorical slots
1-3 (blue/orange/aqua) for the three trend series, a one-hue blue ramp for
magnitude, and the reserved status tokens for budget verdicts - each status
paired with an icon and a word, never color alone.
"""

from __future__ import annotations

import html
import json
from datetime import date

from .schema import fmt

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --plane:#f9f9f7; --surface:#fcfcfb;
  --text:#0b0b0b; --text-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --track:#cde2fb; --fill:#2a78d6;
  --success-text:#006300;
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --plane:#0d0d0d; --surface:#1a1a19;
    --text:#fff; --text-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70;
    --track:#2c2c2a; --fill:#3987e5;
    --success-text:#0ca30c;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19;
  --text:#fff; --text-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --track:#2c2c2a; --fill:#3987e5;
  --success-text:#0ca30c;
}
/* Status tokens are fixed - never themed. Always shipped with icon + label. */
:root{--good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b}

html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--plane); color:var(--text);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
}
.wrap{max-width:960px; margin:0 auto; padding:32px 16px 72px}
header.top{margin-bottom:24px}
h1{font-size:22px; font-weight:650; margin:0 0 2px; letter-spacing:-.01em}
.sub{color:var(--text-2); font-size:14px}
h2{font-size:13px; font-weight:650; letter-spacing:.06em; text-transform:uppercase;
   color:var(--text-2); margin:0 0 12px}
.card{background:var(--surface); border:1px solid var(--border); border-radius:12px;
      padding:20px; margin-bottom:16px}
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(148px,1fr)); gap:1px;
      background:var(--border); border:1px solid var(--border); border-radius:12px;
      overflow:hidden; margin-bottom:16px}
.kpi{background:var(--surface); padding:16px 18px}
.kpi .label{font-size:12px; color:var(--muted); letter-spacing:.03em}
.kpi .value{font-size:26px; font-weight:600; letter-spacing:-.02em; margin-top:3px}
.kpi .foot{font-size:12px; color:var(--text-2); margin-top:2px}
.hero{font-size:52px; font-weight:650; letter-spacing:-.03em; line-height:1.05; margin:4px 0}
.hero-sub{color:var(--text-2); font-size:14px}
.meter{height:14px; border-radius:7px; background:var(--track); overflow:hidden;
  margin:16px 0 8px; box-shadow:inset 0 0 0 1px var(--border)}
.meter > i{display:block; height:100%; background:var(--fill); border-radius:7px}
.pace{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin-top:18px}
.pace div .l{font-size:12px; color:var(--muted)}
.pace div .v{font-size:19px; font-weight:600; margin-top:1px}
.chip{display:inline-flex; align-items:center; gap:6px; font-size:12.5px; font-weight:600;
      padding:3px 10px 3px 8px; border-radius:999px; border:1px solid var(--border)}
.chip svg{flex:none}
/* budget rows */
.brow{display:grid; grid-template-columns:118px 1fr 104px; gap:14px; align-items:center;
      padding:11px 0; border-bottom:1px solid var(--border)}
.brow:last-child{border-bottom:0}
.bname{font-size:13.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.bcell{min-width:0}
.brow.wide{grid-template-columns:168px 1fr 104px}
.cmt{display:grid;grid-template-columns:1fr 130px 108px;gap:14px;align-items:center;
  padding:11px 0;border-bottom:1px solid var(--border)}
.cmt:last-child{border-bottom:0}
.cmt .nm{font-size:14px;font-weight:600}
.cmt .meta{font-size:12px;color:var(--muted);margin-top:2px}
.cmt .n{text-align:right;font-variant-numeric:tabular-nums}
.cmt .n b{font-size:14.5px;font-weight:650}
.cmt .n span{display:block;font-size:11.5px;color:var(--muted)}
.act{display:flex;gap:11px;align-items:flex-start;padding:11px 0;
  border-bottom:1px solid var(--border)}
.act:last-child{border-bottom:0}
.act .tag{flex:none;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:3px 7px;border-radius:5px;margin-top:1px;min-width:62px;text-align:center}
.act .body{min-width:0}
.act .t{font-size:14px;font-weight:600}
.act .d{font-size:12.5px;color:var(--muted);margin-top:3px;line-height:1.5}
.act .when{font-size:11.5px;color:var(--muted);margin-top:4px}
.cmthead{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
  font-weight:600;border-bottom:1px solid var(--border);padding-bottom:8px}
@media (max-width:560px){.cmt{grid-template-columns:1fr 104px}.cmt .third{display:none}}
.bcell .chip{margin-top:7px}
.bnum{text-align:right; font-size:13px; font-variant-numeric:tabular-nums; color:var(--text-2)}
.bnum b{color:var(--text); font-weight:600}
table{width:100%; border-collapse:collapse; font-size:13.5px}
th{text-align:left; font-weight:600; font-size:11.5px; letter-spacing:.05em;
   text-transform:uppercase; color:var(--muted); padding:0 8px 8px 0; border-bottom:1px solid var(--border)}
td{padding:8px 8px 8px 0; border-bottom:1px solid var(--border); color:var(--text-2)}
td.n{text-align:right; font-variant-numeric:tabular-nums; color:var(--text); padding-right:0}
th.n{text-align:right; padding-right:0}
tr:last-child td{border-bottom:0}
.legend{display:flex; flex-wrap:wrap; gap:16px; margin:0 0 6px; font-size:12.5px; color:var(--text-2)}
.legend span{display:inline-flex; align-items:center; gap:6px}
.sw{width:11px; height:11px; border-radius:3px; flex:none}
.note{font-size:13px; color:var(--text-2)}
ul.signals{list-style:none; margin:0; padding:0}
ul.signals li{padding:9px 0; border-bottom:1px solid var(--border); font-size:13.5px; color:var(--text-2)}
ul.signals li:last-child{border-bottom:0}
ul.signals b{color:var(--text); font-weight:600}
details{margin-top:12px} summary{cursor:pointer; font-size:12.5px; color:var(--text-2)}
details.fold{margin-top:14px;border-top:1px solid var(--border);padding-top:12px}
details.fold > summary{list-style:none;display:flex;align-items:center;gap:7px;
  font-size:13.5px;font-weight:600;color:var(--text-2);user-select:none}
details.fold > summary::-webkit-details-marker{display:none}
details.fold > summary::before{content:"›";display:inline-block;transition:transform .15s;
  font-size:16px;line-height:1}
details.fold[open] > summary::before{transform:rotate(90deg)}
details.fold > summary:hover{color:var(--text)}
details.fold .cmthead{margin-top:12px}
.narrative p{margin:0 0 10px; font-size:14.5px; line-height:1.6}
.narrative ol{margin:0; padding-left:20px} .narrative li{margin-bottom:8px; font-size:14.5px}
footer{color:var(--muted); font-size:12px; text-align:center; margin-top:28px}
@media (max-width:560px){
  .brow{grid-template-columns:1fr auto; gap:8px}
  .brow .bcell{grid-column:1/-1; order:3}
  .brow .bnum{text-align:right}
  .hero{font-size:42px}
}
"""

ICON = {
    "good": '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.4l2.3 2.3 4.7-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "critical": '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.6l5 8.8H1z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M6 5v2.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="6" cy="8.9" r=".8" fill="currentColor"/></svg>',
    "warning": '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6 3.4v3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="6" cy="8.5" r=".8" fill="currentColor"/></svg>',
    "serious": '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6 3.4v3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="6" cy="8.5" r=".8" fill="currentColor"/></svg>',
    "muted": '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
}


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def chip(status: str, label: str) -> str:
    """Status is always icon + word, so hue never carries the meaning alone."""
    color = {"good": "var(--good)", "critical": "var(--critical)",
             "warning": "var(--warning)", "serious": "var(--serious)"}.get(status, "var(--muted)")
    return (f'<span class="chip" style="color:{color}">{ICON.get(status, ICON["muted"])}'
            f'<span style="color:var(--text)">{e(label)}</span></span>')


# ------------------------------------------------------------------ charts


def trend_chart(trend: list[dict]) -> str:
    """Three same-unit series (all dollars) on ONE axis. Never a second scale."""
    if len(trend) < 2:
        return '<p class="note">Not enough history yet for a trend chart.</p>'

    W, H = 720, 240
    PL, PR, PT, PB = 52, 74, 16, 30      # right pad holds the direct labels
    iw, ih = W - PL - PR, H - PT - PB

    series = [
        ("Spending", "spend_cents", "var(--s1)"),
        ("Income", "income_cents", "var(--s2)"),
        ("Saved", "savings_cents", "var(--s3)"),
    ]
    vals = [p[k] for p in trend for _, k, _ in series]
    top = max(vals + [1])
    # Round the axis top to a friendly number.
    step = 10 ** (len(str(int(top / 100))) - 1) * 100 or 100
    top = (int(top / step) + 1) * step

    def x(i): return PL + (iw * i / (len(trend) - 1))
    def y(v): return PT + ih - (ih * v / top)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
             f'aria-label="Spending, income and savings over the last {len(trend)} weeks" '
             f'style="overflow:visible" id="trendsvg">']

    # Recessive solid hairline grid + y ticks
    for g in range(5):
        v = top * g / 4
        yy = y(v)
        parts.append(f'<line x1="{PL}" y1="{yy:.1f}" x2="{PL+iw}" y2="{yy:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{PL-8}" y="{yy+4:.1f}" text-anchor="end" fill="var(--muted)" '
                     f'font-size="11" font-variant-numeric="tabular-nums">${int(v/100):,}</text>')

    for i, p in enumerate(trend):
        parts.append(f'<text x="{x(i):.1f}" y="{PT+ih+18}" text-anchor="middle" '
                     f'fill="var(--muted)" font-size="11">{e(p["label"])}</text>')

    for name, key, color in series:
        pts = " ".join(f"{x(i):.1f},{y(p[key]):.1f}" for i, p in enumerate(trend))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
        last = trend[-1]
        parts.append(f'<circle cx="{x(len(trend)-1):.1f}" cy="{y(last[key]):.1f}" r="4" '
                     f'fill="{color}" stroke="var(--surface)" stroke-width="2"/>')
        # Direct label at the endpoint: the light-mode contrast relief, and it
        # means identity is never carried by hue alone.
        parts.append(f'<text x="{x(len(trend)-1)+10:.1f}" y="{y(last[key])+4:.1f}" '
                     f'fill="var(--text-2)" font-size="11.5">{e(name)}</text>')

    parts.append(f'<line x1="{PL}" y1="{PT+ih}" x2="{PL+iw}" y2="{PT+ih}" '
                 f'stroke="var(--axis)" stroke-width="1"/>')
    # Hover layer: one full-height band per period, ~24px+ hit area.
    band = iw / (len(trend) - 1)
    parts.append(f'<line id="cross" x1="0" y1="{PT}" x2="0" y2="{PT+ih}" stroke="var(--axis)" '
                 f'stroke-width="1" opacity="0"/>')
    for i, p in enumerate(trend):
        parts.append(
            f'<rect x="{max(PL, x(i)-band/2):.1f}" y="{PT}" width="{max(band,26):.1f}" height="{ih}" '
            f'fill="transparent" class="hit" data-x="{x(i):.1f}" '
            f'data-label="{e(p["start"])} .. {e(p["end"])}" '
            f'data-spend="{fmt(p["spend_cents"])}" data-income="{fmt(p["income_cents"])}" '
            f'data-saved="{fmt(p["savings_cents"])}"/>')
    parts.append("</svg>")

    legend = (
        '<div class="legend">'
        '<span><i class="sw" style="background:var(--s1)"></i>Spending</span>'
        '<span><i class="sw" style="background:var(--s2)"></i>Income</span>'
        '<span><i class="sw" style="background:var(--s3)"></i>Saved</span>'
        "</div>"
    )
    rows = "".join(
        f'<tr><td>{e(p["label"])}</td><td class="n">{fmt(p["spend_cents"])}</td>'
        f'<td class="n">{fmt(p["income_cents"])}</td><td class="n">{fmt(p["savings_cents"])}</td></tr>'
        for p in trend)
    table = (
        '<details><summary>View as table</summary>'
        '<table style="margin-top:10px"><thead><tr><th>Week</th><th class="n">Spending</th>'
        '<th class="n">Income</th><th class="n">Saved</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></details>")
    return legend + "".join(parts) + table


def budget_rows(rows: list[dict], mtd: dict | None = None) -> str:
    """Horizontal magnitude bars, one hue; over-budget overflow in status-critical.

    Categories budgeted but untouched this period are folded away - in a weekly
    view most of the monthly envelopes are simply not due yet, and listing them
    all buries the handful that actually moved.
    """
    live = [r for r in rows if r["actual_cents"] or r["budget_monthly_cents"]]
    if not live:
        return '<p class="note">No spending recorded in this period.</p>'
    spent = [r for r in live if r["actual_cents"]]
    unspent = [r for r in live if not r["actual_cents"]]
    if not spent:
        return '<p class="note">No spending recorded in this period.</p>'
    scale = max([max(r["actual_cents"], r["budget_monthly_cents"]) for r in spent] + [1])

    out = []
    for r in spent:
        actual, bud = r["actual_cents"], r["budget_monthly_cents"]
        within = min(actual, bud) if bud else actual
        over = max(actual - bud, 0) if bud else 0
        w_within, w_over = within / scale * 100, over / scale * 100

        seg = []
        if w_within:
            radius = "5px" if not w_over else "5px 0 0 5px"
            seg.append(f'<i style="width:{w_within:.2f}%;background:var(--fill);'
                       f'border-radius:{radius};display:block"></i>')
        if w_over:
            # 2px surface gap between fills, never a border.
            seg.append('<i style="width:2px;background:var(--surface);display:block;flex:none"></i>')
            seg.append(f'<i style="width:{w_over:.2f}%;background:var(--critical);'
                       f'border-radius:0 5px 5px 0;display:block"></i>')
        tick = (f'<i style="position:absolute;left:{bud/scale*100:.2f}%;top:-4px;width:1px;'
                f'height:18px;background:var(--axis);display:block"></i>') if bud else ""
        bar = (f'<div style="position:relative;height:10px">'
               f'<div style="display:flex;height:10px">{"".join(seg)}</div>{tick}</div>')

        if r["status"] == "over":
            tag = chip("critical", f"over {fmt(over)}")
        elif r["status"] == "at_risk":
            tag = chip("warning", f"{r['pct_used']:.0f}% of budget used")
        elif r["status"] == "no_budget":
            tag = chip("muted", "no budget set")
        else:
            tag = chip("good", f"{r['pct_used']:.0f}% of budget used")

        budget_txt = f"of {fmt(bud)}" if bud else "unbudgeted"
        out.append(
            f'<div class="brow"><div class="bname">{e(r["category"])}</div>'
            f'<div class="bcell">{bar}{tag}</div>'
            f'<div class="bnum"><b>{fmt(actual)}</b><br>{budget_txt}</div></div>')

    obs = (f'<p class="note" style="margin:14px 0 0">Spending so far this month against the '
           f'full monthly envelope &mdash; {mtd.get("days_observed", 0)} of '
           f'{mtd.get("days_in_month", 0)} days observed, so a category under its target may '
           f'still reach it. The hairline marks the target.</p>'
           if mtd.get("days_in_month") else "")
    out.append(obs)

    if unspent:
        names = ", ".join(e(r["category"]) for r in unspent)
        total = sum(r["budget_monthly_cents"] for r in unspent)
        out.append(
            f'<details><summary>{len(unspent)} budgeted categories with no spending '
            f'this period ({fmt(total)} unused)</summary>'
            f'<p class="note" style="margin:8px 0 0">{names}</p></details>')
    return "".join(out)


def cashflow_block(flow: dict, warn_free: bool = True) -> str:
    """Where the money is committed before anyone decides anything."""
    m = flow["monthly"]
    if not m["income_cents"]:
        return ('<div class="card"><h2>Monthly commitments</h2>'
                '<p class="note">No income sources set, so there is nothing to allocate '
                'against. Add them with <code>python3 -m budget ui</code>.</p></div>')

    free = m["free_cents"]
    inc = m["income_cents"]
    # A single magnitude scale shared by all four bars, so they are comparable.
    scale = max(inc, 1)
    parts = []
    for label, cents, color in [
        ("After-tax income", inc, "var(--fill)"),
        ("Fixed commitments", m["fixed_cents"], "var(--s2)"),
        ("Planned savings", m.get("goal_planned_cents", m["goal_required_cents"]), "var(--s3)"),
    ]:
        parts.append(
            f'<div class="brow wide"><div class="bname">{e(label)}</div>'
            f'<div class="bcell"><div style="height:10px"><i style="display:block;height:10px;'
            f'width:{min(cents/scale*100,100):.2f}%;background:{color};border-radius:5px"></i></div></div>'
            f'<div class="bnum"><b>{fmt(cents)}</b></div></div>')

    tone = "var(--success-text)" if free >= 0 else "var(--critical)"
    shortfall = m.get("plan_shortfall_cents", 0)
    if free < 0:
        # The plan itself does not fit inside income.
        verdict = chip("critical", f"Short {fmt(abs(free))}/mo")
    elif shortfall < 0:
        # The plan fits, but it is not enough to reach the goals on their dates.
        # Calling this "affordable" would be true of the plan and false of the goals.
        verdict = chip("warning", "Plan fits, dates do not")
    else:
        verdict = chip("good", "Goals fully funded")
    short = m.get("plan_shortfall_cents", 0)
    rate = m.get("savings_rate_pct")
    extra = ""
    if rate is not None:
        extra = (f'<p class="note" style="margin:14px 0 0">Savings rate: '
                 f'<b style="color:var(--text)">{rate:g}%</b> of after-tax income.')
        if short < 0:
            extra += (f' That is {fmt(abs(short))}/mo below what the goal dates require &mdash; '
                      'following this plan exactly still misses them.')
        extra += "</p>"
    note = ("" if free >= 0 else
            '<p class="note" style="margin:14px 0 0">Commitments and goal contributions together '
            'exceed income, so the goals cannot all be met at their current dates without '
            'either moving a date, lowering a target, or cutting a commitment.</p>')
    return (
        '<div class="card"><h2>Monthly commitments</h2>'
        + "".join(parts) +
        f'<div class="brow wide" style="border-bottom:0"><div class="bname" style="font-weight:600">'
        f'Free to spend</div><div class="bcell">{verdict}</div>'
        f'<div class="bnum"><b style="color:{tone}">{fmt(free, sign=True)}</b></div></div>'
        + extra + note + "</div>")


def commitments_block(rows: list[dict]) -> str:
    if not rows:
        return ""
    problems = [r for r in rows if r["status"] in ("missing", "drift")]
    body = []
    for r in rows:
        if r["status"] == "missing":
            tag, detail = chip("critical", "did not post"), f'expected {fmt(r["expected_cents"])}'
        elif r["status"] == "drift":
            tag = chip("warning", f'{fmt(r["drift_cents"], sign=True)}')
            detail = f'{fmt(r["actual_cents"])} vs {fmt(r["expected_cents"])} expected'
        elif r["status"] == "upcoming":
            tag, detail = chip("muted", "not due yet"), f'{fmt(r["expected_cents"])} expected'
        else:
            tag = chip("good", "paid")
            detail = fmt(r["actual_cents"]) + (" (varies)" if r["variable"] else "")
        body.append(
            f'<div class="brow"><div class="bname">{e(r["name"])}</div>'
            f'<div class="bcell">{tag}</div>'
            f'<div class="bnum"><b>{e(detail.split(" vs ")[0])}</b><br>'
            f'{e(r["due"])}</div></div>')
    head = ("" if not problems else
            f'<p class="note" style="margin:0 0 12px">'
            f'{len(problems)} commitment(s) need a look.</p>')
    return f'<div class="card"><h2>Fixed commitments</h2>{head}{"".join(body)}</div>'


def goals_block(goals: list[dict]) -> str:
    """Secondary goals, listed compactly beneath the primary hero."""
    if len(goals) < 2:
        return ""
    rows = []
    for g in goals[1:]:
        if g.get("on_track") is True:
            tag = chip("good", "on track")
        elif g.get("on_track") is False:
            tag = chip("critical", f'behind {fmt(abs(g["monthly_gap_cents"]))}/mo')
        else:
            tag = chip("muted", "no pace set")
        pct = g.get("pct_complete") or 0
        rows.append(
            f'<div class="brow"><div class="bname">{e(g["name"])}</div>'
            f'<div class="bcell"><div class="meter" style="margin:0;height:10px">'
            f'<i style="width:{min(pct,100):.1f}%"></i></div>{tag}</div>'
            f'<div class="bnum"><b>{fmt(g["current_cents"])}</b><br>'
            f'of {fmt(g["target_cents"])}</div></div>')
    return f'<div class="card"><h2>Other goals</h2>{"".join(rows)}</div>'


def savings_block(s: dict) -> str:
    if s.get("goal_type") == "rate":
        return _rate_goal_block(s)
    return _target_goal_block(s)


def _rate_goal_block(s: dict) -> str:
    """A rate goal has no finish line, and under the residual model no
    transactions either: what is not spent is what is saved. So the useful
    framing is a ceiling - the most that can be spent without eating into it.
    """
    required = s.get("required_monthly_cents") or 0
    if not required:
        return ('<div class="card"><h2>Savings goal</h2>'
                f'<p class="note">{e(s.get("note", "No contribution set."))}</p></div>')

    observed = s.get("observed_monthly_cents") or 0
    target_pct = s.get("target_percent_of_income")
    actual_pct = s.get("actual_percent_of_income")
    residual = s.get("savings_model") == "residual"
    ceiling = s.get("spending_ceiling_cents")
    spending = s.get("actual_spend_monthly_cents")
    over = s.get("overspend_monthly_cents") or 0

    hit = max(min(observed / required * 100, 100), 0) if required else 0
    if s.get("on_track"):
        verdict = chip("good", "Within the ceiling")
    elif residual and over:
        verdict = chip("critical", f"Overspending {fmt(over)}/mo")
    else:
        verdict = chip("critical", f'Short {fmt(abs(s["monthly_gap_cents"]))}/mo')

    hero = f'{actual_pct:g}%' if actual_pct is not None else fmt(observed)
    sub = (f'of after-tax income kept, against a {target_pct:g}% goal'
           if target_pct is not None and actual_pct is not None
           else f'kept each month, against a {fmt(required)} goal')

    if residual and ceiling is not None:
        detail = (
            '<div class="pace">'
            f'<div><div class="l">Spending ceiling</div><div class="v">{fmt(ceiling)}</div>'
            f'<div class="l">income less the {target_pct:g}% target</div></div>'
            f'<div><div class="l">Actually spending</div>'
            f'<div class="v" style="color:{"var(--critical)" if over else "var(--text)"}">'
            f'{fmt(spending or 0)}</div>'
            f'<div class="l">rate over {s.get("measured_days", 0)} days</div></div>'
            f'<div><div class="l">{"Over by" if over else "Headroom"}</div>'
            f'<div class="v" style="color:{"var(--critical)" if over else "var(--success-text)"}">'
            f'{fmt(over if over else max((ceiling or 0) - (spending or 0), 0))}</div>'
            f'<div class="l">per month</div></div></div>'
            '<p class="note" style="margin:14px 0 0">Savings here is what is left after '
            'spending, not a transfer. Staying under the ceiling <em>is</em> hitting the goal.</p>')
    else:
        detail = (
            '<div class="pace">'
            f'<div><div class="l">Goal each month</div><div class="v">{fmt(required)}</div></div>'
            f'<div><div class="l">Actually saving</div><div class="v">{fmt(observed)}</div></div>'
            "</div>")

    return (
        '<div class="card"><h2>Savings goal &mdash; ' + e(s["name"]) + "</h2>"
        f'<div class="hero">{hero}</div>'
        f'<div class="hero-sub">{sub}</div>'
        f'<div class="meter" role="img" aria-label="{hit:.0f} percent of the monthly target">'
        f'<i style="width:{hit:.1f}%"></i></div>'
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;'
        f'flex-wrap:wrap"><span class="note">measured over {s.get("measured_days", 0)} days</span>'
        f'{verdict}</div>{detail}</div>')


def _target_goal_block(s: dict) -> str:
    if not s.get("target_cents"):
        return ('<div class="card"><h2>Savings goal</h2>'
                f'<p class="note">{e(s.get("note", "No goal configured."))}</p></div>')

    pct = min(s["pct_complete"] or 0, 100)
    on = s.get("on_track")
    if on is True:
        verdict = chip("good", "On track")
    elif on is False:
        gap = abs(s["monthly_gap_cents"])
        verdict = chip("critical", f"Behind by {fmt(gap)}/mo")
    else:
        verdict = chip("muted", "Pace unknown")

    plan_line = ""
    planned = s.get("planned_monthly_cents")
    if planned is not None:
        kind = s.get("contribution_type")
        basis = (f'{s["percent_of_net_income"]:g}% of after-tax income'
                 if kind == "percent" else "fixed amount")
        if s.get("plan_covers_goal") is False:
            tag = chip("critical", f'plan short {fmt(abs(s["plan_gap_cents"]))}/mo')
            tail = (f' Following it lands you on {e(s["projected_at_plan"])}.'
                    if s.get("projected_at_plan") else "")
        elif s.get("plan_covers_goal") is True:
            tag = chip("good", "plan covers it")
            tail = ""
        else:
            tag, tail = chip("muted", "no target set"), ""
        plan_line = (
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
            'margin-top:16px;padding-top:14px;border-top:1px solid var(--border)">'
            f'<span class="note">Plan: <b style="color:var(--text)">{fmt(planned)}/mo</b> '
            f'&mdash; {e(basis)}.{tail}</span>{tag}</div>')

    pace = ""
    if s.get("required_monthly_cents") is not None:
        proj = ""
        if s.get("projected_completion"):
            slip = s.get("projected_slip_days", 0)
            word = (f"{abs(slip)} days late" if slip > 0 else
                    f"{abs(slip)} days early" if slip < 0 else "on the day")
            proj = (f'<div><div class="l">At current pace</div>'
                    f'<div class="v">{e(s["projected_completion"])}</div>'
                    f'<div class="l">{e(word)}</div></div>')
        pace = (
            '<div class="pace">'
            f'<div><div class="l">Needed each month</div><div class="v">{fmt(s["required_monthly_cents"])}</div>'
            f'<div class="l">over {s["months_remaining"]} months</div></div>'
            f'<div><div class="l">Actually saving</div><div class="v">{fmt(s["observed_monthly_cents"])}</div>'
            f'<div class="l">3-month average</div></div>'
            f'{proj}</div>')

    return (
        '<div class="card"><h2>Savings goal &mdash; ' + e(s["name"]) + "</h2>"
        f'<div class="hero">{fmt(s["current_cents"])}</div>'
        f'<div class="hero-sub">of {fmt(s["target_cents"])} target'
        + (f' by {e(s["target_date"])}' if s.get("target_date") else "") + "</div>"
        f'<div class="meter" role="img" aria-label="{pct:.0f} percent of goal saved">'
        f'<i style="width:{pct:.1f}%"></i></div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">'
        f'<span class="note">{s["pct_complete"]}% complete &middot; {fmt(s["remaining_cents"])} to go</span>'
        f"{verdict}</div>{pace}{plan_line}</div>")


TAG_COLOR = {"tax": ("var(--critical)", "rgba(208,59,59,.13)"),
             "spending": ("var(--warning)", "rgba(250,178,25,.13)"),
             "goal": ("var(--s3)", "rgba(27,175,122,.13)"),
             "data": ("var(--s1)", "rgba(42,120,214,.13)"),
             "admin": ("var(--muted)", "rgba(137,135,129,.13)")}


def actions_block(reminders: list[dict], actions: list[dict]) -> str:
    """What needs doing, above everything else on the page.

    Reminders are what the household told us to remember; spending actions are
    derived from this month's own numbers. Both belong at the top, because a
    dashboard nobody acts on is just a receipt.
    """
    rows = []
    for a in actions:
        d = a.get("driver")
        if a["status"] == "over":
            title = (f'{e(a["category"])} is {fmt(a["over_cents"])} over its '
                     f'{fmt(a["budget_cents"])} budget')
        else:
            title = (f'{e(a["category"])} has {fmt(a["left_cents"])} left of '
                     f'{fmt(a["budget_cents"])}')
        detail = (f'{d["merchant"]} is {fmt(d["total_cents"])} of it across {d["count"]} '
                  f'purchases. ' if d else "")
        detail += (f'{a["days_left"]} days left in the month.'
                   if a["days_left"] else "The month is over.")
        colour, bg = TAG_COLOR["spending"]
        rows.append(
            f'<div class="act"><div class="tag" style="color:{colour};background:{bg}">'
            f'spend</div><div class="body"><div class="t">{title}</div>'
            f'<div class="d">{e(detail)}</div></div></div>')

    for r in reminders:
        colour, bg = TAG_COLOR.get(r.get("tag", "admin"), TAG_COLOR["admin"])
        when = ""
        if r.get("due"):
            when = (f'<div class="when" style="color:var(--critical)">overdue &mdash; '
                    f'was due {e(r["due"])}</div>' if r["overdue"] else
                    f'<div class="when">due {e(r["due"])}'
                    + (f' &middot; {r["days_until"]} days' if r["days_until"] is not None
                       and r["days_until"] <= 60 else "") + '</div>')
        rows.append(
            f'<div class="act"><div class="tag" style="color:{colour};background:{bg}">'
            f'{e(r.get("tag", "admin"))}</div><div class="body">'
            f'<div class="t">{e(r["text"])}</div>'
            + (f'<div class="d">{e(r["detail"])}</div>' if r.get("detail") else "")
            + when + '</div></div>')

    if not rows:
        return ""
    return ('<div class="card"><h2>Needs doing</h2>' + "".join(rows) + "</div>")


def free_items_block(items: list[dict], mtd: dict, goal: dict) -> str:
    """What consumed the free-to-spend budget, split by account.

    A flat list of every purchase is too long to read; the per-account totals
    are the shape of it, and the individual rows fold away underneath.
    """
    free_b = mtd.get("free_monthly_cents") or 0
    spent = mtd.get("spent_cents") or 0
    left = mtd.get("remaining_cents") or 0
    month = mtd.get("month", "this month")

    if not items:
        return ('<div class="card"><h2>Free-to-spend transactions</h2>'
                '<p class="note">Nothing discretionary recorded in this period.</p></div>')

    verdict = (chip("good", f"{fmt(left)} left") if left >= 0
               else chip("critical", f"{fmt(abs(left))} over"))
    note = ("" if left >= 0 else
            '<p class="note" style="margin:12px 0 0">Past the monthly allowance, every '
            'further dollar comes out of the savings target.</p>')

    by_account: dict[str, list[dict]] = {}
    for i in items:
        by_account.setdefault(i["account"] or "unknown", []).append(i)
    groups = sorted(by_account.items(),
                    key=lambda kv: -sum(x["amount_cents"] for x in kv[1]))
    detail = []
    for acct, rows_ in groups:
        tot = sum(x["amount_cents"] for x in rows_)
        detail.append(
            f'<div class="cmt cmthead" style="margin-top:16px">'
            f'<div>{e(acct)}</div><div class="n">{fmt(tot)}</div>'
            f'<div class="n third">{len(rows_)} purchases</div></div>')
        for i in sorted(rows_, key=lambda x: -x["amount_cents"]):
            detail.append(
                f'<div class="cmt"><div>'
                f'<div class="nm">{e((i["merchant"] or i["description"])[:44])}</div>'
                f'<div class="meta">{e(i["category"] or "uncategorized")} &middot; '
                f'{e(i["date"])}</div></div>'
                f'<div class="n"><b>{fmt(i["amount_cents"])}</b></div>'
                f'<div class="n third"></div></div>')

    return ('<div class="card"><h2>Free-to-spend transactions</h2>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'gap:12px;flex-wrap:wrap;margin-bottom:14px">'
            f'<span class="note">{len(items)} purchases totalling '
            f'<b style="color:var(--text)">{fmt(spent)}</b> against the {fmt(free_b)} '
            f'budget for {e(month)}</span>{verdict}</div>'
            + note +
            f'<details class="fold"><summary>Show all {len(items)} purchases by account'
            f'</summary>' + "".join(detail) + "</details></div>")


def history_block(hist: dict) -> str:
    """Month-over-month, complete months only.

    Deliberately empty until whole months exist: a partial month plotted beside
    full ones reads as a drop in spending that never happened.
    """
    months = hist.get("months") or []
    if not months:
        first = hist.get("first_complete_month")
        return (
            '<div class="card"><h2>Month by month</h2>'
            '<p class="note" style="margin:0 0 14px">No complete month of data yet, so there '
            'is nothing to compare. A partial month shown next to whole ones would read as a '
            'fall in spending that never happened.</p>'
            '<div class="cmt cmthead"><div>Month</div><div class="n">Free to spend</div>'
            '<div class="n third">Spent of it</div></div>'
            '<div class="cmt"><div><div class="nm" style="color:var(--muted)">'
            + (f'{e(first)} &mdash; the first complete month' if first else 'Awaiting data')
            + '</div><div class="meta">allowance, discretionary spend, over/under, and '
              'what the savings target kept</div></div>'
              '<div class="n" style="color:var(--muted)"><b>&mdash;</b></div>'
              '<div class="n third" style="color:var(--muted)"><b>&mdash;</b></div></div>'
            + (f'<p class="note" style="margin:14px 0 0">Analysis starts '
               f'{e(hist.get("analysis_start"))}; the first whole month after that is '
               f'{e(first)}.</p>' if first else "")
            + "</div>")

    scale = max([m["discretionary_cents"] for m in months] + [1])
    rows = []
    for m in months:
        over = m["over_cents"]
        tag = (chip("critical", f'over {fmt(over)}') if over
               else chip("good", f'{fmt(m["free_budget_cents"] - m["discretionary_cents"])} spare'))
        w = m["discretionary_cents"] / scale * 100
        rows.append(
            f'<div class="cmt"><div><div class="nm">{e(m["label"])}</div>'
            f'<div style="height:8px;margin:7px 0 6px"><i style="display:block;height:8px;'
            f'width:{w:.1f}%;background:{"var(--critical)" if over else "var(--fill)"};'
            f'border-radius:4px"></i></div>{tag}</div>'
            f'<div class="n"><b>{fmt(m["free_budget_cents"])}</b></div>'
            f'<div class="n third"><b>{fmt(m["discretionary_cents"])}</b>'
            f'<span>{fmt(m["spend_cents"])} all in</span></div></div>')
    return ('<div class="card"><h2>Month by month</h2>'
            '<p class="note" style="margin:0 0 12px">Complete months only.</p>'
            '<div class="cmt cmthead"><div>Month</div><div class="n">Free to spend</div>'
            '<div class="n third">Spent of it</div></div>' + "".join(rows) + "</div>")


def tracker_block(rows: list[dict], monthly_total: int) -> str:
    """Every declared commitment, always listed, so nothing quietly stops paying."""
    if not rows:
        return ('<div class="card"><h2>Fixed commitments</h2>'
                '<p class="note">None declared. Until they are, the mortgage, loans and '
                'daycare count as discretionary spending and the free-to-spend figure is '
                'wrong. Add them with <code>python3 -m budget add-fixed</code>.</p></div>')

    body = [f'<div class="cmt cmthead"><div>Commitment</div>'
            f'<div class="n">Last payment</div><div class="n third">Per month</div></div>']
    for r in rows:
        if r["status"] == "overdue":
            tag = chip("critical", f'overdue {r["days_overdue"]} days')
        elif r["status"] == "never_seen":
            tag = chip("warning", "never seen")
        elif r["status"] == "drift":
            tag = chip("warning", f'{fmt(r["drift_cents"], sign=True)} vs expected')
        else:
            tag = chip("good", "on track")

        last = (f'<b>{fmt(r["last_amount_cents"])}</b>'
                f'<span>{e(r["last_paid"])}</span>' if r["last_paid"]
                else '<b>&mdash;</b><span>no payment found</span>')
        nxt = (f'<span>next {e(r["next_due"])}</span>' if r["next_due"] else "")
        cad = "" if r["cadence"] == "monthly" else f' &middot; {e(r["cadence"])}'
        body.append(
            f'<div class="cmt"><div><div class="nm">{e(r["name"])}</div>'
            f'<div class="meta">{e(r["category"])}{cad}'
            + (" &middot; varies" if r["variable"] else "")
            + f'</div><div style="margin-top:7px">{tag}</div></div>'
            f'<div class="n">{last}</div>'
            f'<div class="n third"><b>{fmt(r["monthly_cents"])}</b>{nxt}</div></div>')

    problems = [r for r in rows if r["status"] in ("overdue", "never_seen", "drift")]
    head = ("" if not problems else
            f'<p class="note" style="margin:0 0 12px">'
            f'{len(problems)} of {len(rows)} need a look.</p>')
    return ('<div class="card"><h2>Fixed commitments</h2>' + head + "".join(body)
            + f'<div class="tot" style="display:flex;gap:26px;flex-wrap:wrap;padding-top:14px;'
              f'margin-top:10px;border-top:1px solid var(--border)">'
              f'<div><div style="font-size:11.5px;color:var(--muted);text-transform:uppercase;'
              f'letter-spacing:.04em">Committed every month</div>'
              f'<div style="font-size:21px;font-weight:650;margin-top:2px">'
              f'{fmt(monthly_total)}</div></div></div></div>')


def signals_block(rep: dict) -> str:
    items = []
    for a in rep["anomalies"]:
        if a["type"] == "category_spike":
            items.append(
                f'<li><b>{e(a["category"])}</b> is {a["ratio"]}&times; its usual pace '
                f'&mdash; {fmt(a["amount_cents"])} vs a typical {fmt(a["typical_cents"])} '
                f'({fmt(a["excess_cents"])} extra)</li>')
        elif a["type"] == "large_transaction":
            items.append(
                f'<li>Large charge: <b>{fmt(a["amount_cents"])}</b> at '
                f'{e(a["merchant"] or a["description"])} on {e(a["date"])} '
                f'({e(a["category"] or "uncategorized")})</li>')
        elif a["type"] == "new_merchant":
            items.append(
                f'<li>First time here: <b>{e(a["merchant"])}</b> &mdash; '
                f'{fmt(a["total_cents"])} across {a["count"]} charge(s)</li>')
    if not items:
        items.append('<li>Nothing unusual against the last 12 weeks.</li>')
    return f'<ul class="signals">{"".join(items)}</ul>'


def narrative_block(n: dict | None) -> str:
    if not n:
        return ""
    head = f'<p>{e(n["summary"])}</p>' if n.get("summary") else ""
    recs = ""
    if n.get("recommendations"):
        lis = "".join(
            f'<li><b>{e(r["action"])}</b>'
            + (f' &mdash; {e(r["rationale"])}' if r.get("rationale") else "")
            + (f' <span style="color:var(--success-text);font-weight:600">'
               f'saves ~{fmt(r["impact_cents"])}/mo</span>' if r.get("impact_cents") else "")
            + "</li>"
            for r in n["recommendations"])
        recs = f'<h2 style="margin-top:18px">What to do</h2><ol>{lis}</ol>'
    return f'<div class="card narrative"><h2>Read on the week</h2>{head}{recs}</div>'


# ------------------------------------------------------------------ page


def render(rep: dict) -> str:
    t, p = rep["totals"], rep["period"]
    disc_left = rep["cashflow"]["period"]["discretionary_left_cents"]
    # Under the residual model nothing is "moved into savings" - what is kept is
    # simply income less spending, so the tile must say that instead of $0.
    residual_model = any(g.get("savings_model") == "residual" for g in rep.get("goals", []))
    kept = t["expected_income_cents"] - t["spend_cents"] - t["retirement_cents"]
    _ceil_m = rep["cashflow"]["monthly"].get("spending_ceiling_cents") or 0
    ceiling_period = round(_ceil_m * p["days"] / 30.44)
    # Positive-but-short is not success: green only once the target is met.
    _target_m = sum(g.get("required_monthly_cents") or 0 for g in rep.get("goals", []))
    target_period = round(_target_m * p["days"] / 30.44)
    spend_share = (f'{t["spend_cents"]/ceiling_period*100:.0f}% of the ceiling'
                   if residual_model and ceiling_period
                   else (f'{t["spend_cents"]/t["expected_income_cents"]*100:.0f}% of income'
                         if t.get("expected_income_cents") else "&nbsp;"))

    cf = rep["cashflow"]["period"]
    mtd = rep.get("month_to_date") or {}
    free_m = mtd.get("free_monthly_cents") or 0
    spent_m = mtd.get("spent_cents") or 0
    remain_m = mtd.get("remaining_cents") or 0
    pct = mtd.get("pct_used")
    observed_pct = mtd.get("pct_month_observed") or 0

    # The budget is monthly, so the top row is scoped to the calendar month
    # rather than the report's own period. Ahead-of-pace is judged against the
    # share of the month actually observed, not the share elapsed - an analysis
    # window starting mid-month means the spend figure is a floor.
    if free_m:
        ahead = pct is not None and pct > observed_pct
        kpis = "".join([
            f'<div class="kpi"><div class="label">Monthly free to spend</div>'
            f'<div class="value">{fmt(free_m)}</div>'
            f'<div class="foot">after commitments and savings</div></div>',

            f'<div class="kpi"><div class="label">Spent</div>'
            f'<div class="value">{fmt(spent_m)}</div>'
            f'<div class="foot">{mtd.get("days_observed", 0)} of '
            f'{mtd.get("days_in_month", 0)} days observed</div></div>',

            f'<div class="kpi"><div class="label">Remaining</div>'
            f'<div class="value" style="color:{"var(--critical)" if remain_m < 0 else "var(--text)"}">'
            f'{fmt(remain_m)}</div>'
            f'<div class="foot">{mtd.get("days_left", 0)} days left in '
            f'{e(mtd.get("month", "").split()[0])}</div></div>',

            f'<div class="kpi"><div class="label">Budget used</div>'
            f'<div class="value" style="color:{"var(--critical)" if ahead else "var(--success-text)"}">'
            f'{pct:g}%</div>'
            f'<div class="foot">{observed_pct}% of the month observed</div></div>',
        ])
    else:
        kpis = "".join([
            f'<div class="kpi"><div class="label">Spent</div>'
            f'<div class="value">{fmt(t["spend_cents"])}</div>'
            f'<div class="foot">{t["transactions"]} transactions</div></div>',
            f'<div class="kpi"><div class="label">Income</div>'
            f'<div class="value">{fmt(t["income_cents"])}</div>'
            f'<div class="foot">as recorded</div></div>',
            f'<div class="kpi"><div class="label">Commitments</div>'
            f'<div class="value">{fmt(rep["cashflow"]["monthly"]["fixed_cents"])}</div>'
            f'<div class="foot">per month, declared</div></div>',
            f'<div class="kpi"><div class="label">Free to spend</div>'
            f'<div class="value">{fmt(rep["cashflow"]["monthly"].get("free_cents", 0))}</div>'
            f'<div class="foot">set a budget to track it</div></div>',
        ])

    merch = "".join(
        f'<tr><td>{e(m["merchant"][:38] or "(unknown)")}</td>'
        f'<td>{e(m["category"] or "uncategorized")}</td>'
        f'<td class="n">{m["count"]}</td><td class="n">{fmt(m["total_cents"])}</td></tr>'
        for m in rep["top_merchants"]) or '<tr><td colspan="4">No spending.</td></tr>'

    subs = "".join(
        f'<tr><td>{e(s["merchant"][:38])}</td><td>{e(s["category"] or "-")}</td>'
        f'<td class="n">{fmt(s["typical_cents"])}</td>'
        f'<td class="n">{fmt(s["annualized_cents"])}</td></tr>'
        for s in rep["recurring"][:12])
    subs_card = (
        '<div class="card"><h2>Recurring charges</h2>'
        '<table><thead><tr><th>Merchant</th><th>Category</th><th class="n">Monthly</th>'
        f'<th class="n">Per year</th></tr></thead><tbody>{subs}</tbody></table>'
        f'<p class="note" style="margin-top:12px">Total: '
        f'<b style="color:var(--text)">{fmt(sum(s["annualized_cents"] for s in rep["recurring"]))}</b>'
        " a year in subscriptions.</p></div>") if subs else ""

    warn = ""
    flags = []
    # A missing statement reads as a quiet month, not as missing data. Say it.
    cov = rep.get("coverage") or {}
    for r in cov.get("accounts", []):
        if r["absent"]:
            flags.append(
                f'<b>{e(r["account"])}</b> has no transactions in this period at all '
                f'(last seen {e(r["last_transaction"])}). If that statement was not '
                f'uploaded, its spending is missing rather than zero.')
        elif r["stale"]:
            flags.append(
                f'<b>{e(r["account"])}</b> has nothing newer than '
                f'{e(r["last_transaction"])}, {r["days_behind"]} days before the period '
                f'ends &mdash; its latest statement may not be uploaded.')
    flags += list(rep.get("config_warnings", []))
    if rep["uncategorized"]:
        flags.insert(0, f'{len(rep["uncategorized"])} transaction(s) still uncategorized '
                        f'&mdash; run the analyze-spending skill to classify them')
    if flags:
        warn = ('<div class="card"><h2>Needs attention</h2><ul class="signals">'
                + "".join(f"<li>{f}</li>" for f in flags) + "</ul></div>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(rep["household"])} &mdash; {e(p["label"])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>{e(rep["household"])}</h1>
    <div class="sub">{e(p["label"])} &middot; {e(p["start"])} to {e(p["end"])} &middot; {p["days"]} days</div>
  </header>

  <div class="kpis">{kpis}</div>

  {actions_block(rep.get("reminders") or [], rep.get("spending_actions") or [])}

  {goals_block(rep.get("goals") or [])}

  {cashflow_block(rep["cashflow"])}

  {narrative_block(rep.get("narrative"))}

  <div class="card">
    <h2>Budget vs actual</h2>
    {budget_rows(rep["budget"], rep.get("month_to_date") or {})}

  </div>

  {history_block(rep.get("monthly_history") or {})}

  {free_items_block(rep.get("free_spend_items") or [], rep.get("month_to_date") or {}, rep["savings"])}

  {tracker_block(rep.get("commitment_tracker") or [],
                 rep["cashflow"]["monthly"]["fixed_cents"])}

  <div class="card">
    <h2>Worth noticing</h2>
    {signals_block(rep)}
  </div>

  <div class="card">
    <h2>Where it went</h2>
    <table><thead><tr><th>Merchant</th><th>Category</th><th class="n">Times</th>
    <th class="n">Total</th></tr></thead><tbody>{merch}</tbody></table>
  </div>

  {subs_card}
  {warn}

  <footer>Generated {e(rep["generated_at"])} by budget-manager</footer>
</div>
</body>
</html>"""
