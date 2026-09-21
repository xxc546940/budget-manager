"""Language and currency for the rendered pages.

Strings live here as format templates rather than inline in the renderers, so
adding a language is a data change. The data layer (analyze, optimize) stays
language-free: it emits numbers and `facts`, and the renderer composes the
sentence.
"""

from __future__ import annotations

from datetime import date

LANGS = ("en", "zh-Hans")

# Symbol and whether it sits before the number.
CURRENCIES = {
    "USD": ("$", True), "CNY": ("¥", True), "EUR": ("€", True),
    "GBP": ("£", True), "JPY": ("¥", True), "CAD": ("$", True),
    "AUD": ("$", True), "TWD": ("NT$", True), "HKD": ("HK$", True),
}

ZH_MONTHS = [""] + [f"{i}月" for i in range(1, 13)]

STRINGS: dict[str, dict[str, str]] = {
    # --- page chrome ---
    "page_title": {"en": "{household} — Recommendations", "zh-Hans": "{household} · 行动建议"},
    "h1": {"en": "What to do next", "zh-Hans": "下一步怎么做"},
    "subhead": {"en": "{household} · {period} · generated {date}",
                "zh-Hans": "{household} · {period} · 生成于 {date}"},
    "footer": {"en": "Every figure is computed from your own transactions. budget-manager",
               "zh-Hans": "所有数字均由你自己的交易记录计算得出。budget-manager"},

    # --- gap block ---
    "on_track_q": {"en": "Are you on track?", "zh-Hans": "储蓄目标进度如何？"},
    "on_track_yes": {"en": "Yes", "zh-Hans": "进度正常"},
    "on_track_yes_sub": {"en": "Your savings plan already covers every goal by its date.",
                         "zh-Hans": "按当前的储蓄计划，每个目标都能在截止日期前达成。"},
    "no_goals": {"en": "No goals set", "zh-Hans": "尚未设置储蓄目标"},
    "no_goals_sub": {
        "en": "There is nothing to measure against yet. Add a savings goal with "
              "<code>python3 -m budget ui</code> and this page can tell you whether your "
              "spending supports it.",
        "zh-Hans": "目前没有可对照的目标。用 <code>python3 -m budget ui</code> 添加一个储蓄目标，"
                   "这个页面就能告诉你当前的支出能否支撑它。"},
    "no_dates": {"en": "No target dates", "zh-Hans": "目标没有截止日期"},
    "no_dates_sub": {
        "en": "Your goals have no dates, so there is no required monthly pace to compare "
              "against. Add a target date to each goal.",
        "zh-Hans": "目标没有设定截止日期，因此无法算出每月需要存多少。请为每个目标补上目标日期。"},
    "short_hero": {"en": "No — short {amount} a month", "zh-Hans": "每月还差 {amount}"},
    "short_sub_rate": {
        "en": "You are saving less each month than your goal rate. Here is where that number "
              "comes from:",
        "zh-Hans": "你每月实际存入的金额低于目标比例。这个数字是这样算出来的："},
    "goals_need_rate_one": {"en": "Your goal needs, every month", "zh-Hans": "这个目标每月需要"},
    "goals_need_rate_many": {"en": "Your {n} goals need, every month",
                             "zh-Hans": "{n} 个目标每月共需"},
    "short_sub": {
        "en": "Your savings plan puts in less than your goal dates require. Here is where "
              "that number comes from:",
        "zh-Hans": "你计划存入的金额，低于目标日期所要求的金额。这个数字是这样算出来的："},
    "goal_row_how": {"en": "{amount} still to save ÷ {months} months left",
                     "zh-Hans": "还需存 {amount} ÷ 剩余 {months} 个月"},
    "goal_row_rate": {"en": "{pct}% of {income} after-tax income, every month",
                      "zh-Hans": "每月税后收入 {income} 的 {pct}%"},
    "goal_row_rate_fixed": {"en": "a fixed amount, every month", "zh-Hans": "每月固定金额"},
    "you_saving": {"en": "What you are actually saving", "zh-Hans": "你实际每月存入"},
    "saving_how": {"en": "3-month average of money moved into savings",
                   "zh-Hans": "最近 3 个月实际转入储蓄的平均值"},
    "you_keeping": {"en": "What is actually left over", "zh-Hans": "实际剩下的钱"},
    "keeping_how": {"en": "after-tax income minus spending, measured over {days} days",
                    "zh-Hans": "税后收入减去支出，按 {days} 天测算"},
    "goals_need_one": {"en": "Your goal needs, to hit that date",
                       "zh-Hans": "要在目标日期前达成，每月需要"},
    "goals_need_many": {"en": "Your {n} goals need, to hit those dates",
                        "zh-Hans": "要在各自目标日期前达成，{n} 个目标每月共需"},
    "you_plan": {"en": "What you plan to put in", "zh-Hans": "你计划每月存入"},
    "plan_pct": {"en": "{pct}% of net income for {name}", "zh-Hans": "{name}：税后收入的 {pct}%"},
    "plan_fixed": {"en": "{amount} fixed for {name}", "zh-Hans": "{name}：固定 {amount}"},
    "plan_none": {"en": "no contribution plan set", "zh-Hans": "尚未设置存入计划"},
    "short_every_month": {"en": "Short every month", "zh-Hans": "每月缺口"},
    "can_it_come_q": {"en": "Can that come out of spending?", "zh-Hans": "这笔钱能从支出里省出来吗？"},
    "searching": {"en": "Searching your transactions for {amount}/mo of changes you could "
                        "actually make:",
                  "zh-Hans": "在你的交易记录里寻找每月 {amount} 的可行调整："},
    "found_listed": {"en": "<b>{amount}/mo</b> found (listed below)",
                     "zh-Hans": "已找到 <b>每月 {amount}</b>（见下方）"},
    "not_accounted": {"en": "<b>{amount}/mo</b> not accounted for",
                      "zh-Hans": "仍缺 <b>每月 {amount}</b> 没有着落"},
    "verdict_covers": {"en": "The changes listed below cover the whole shortfall. Nothing else "
                             "has to change.",
                       "zh-Hans": "下面列出的调整就能补上全部缺口，其他地方不需要改动。"},
    "verdict_tight": {
        "en": "The rest — {amount}/mo — would need roughly a <b>{pct}% cut across all "
              "discretionary spending</b>. Tight, but real.",
        "zh-Hans": "剩下的每月 {amount}，大约需要<b>把全部可调整支出削减 {pct}%</b>。会比较紧，但做得到。"},
    "verdict_deep": {
        "en": "The rest — {amount}/mo — would mean cutting <b>{pct}% of every discretionary "
              "dollar</b>: groceries, dining, transport, all of it. That is a different kind of "
              "decision from cancelling a subscription, and moving a goal date is usually the "
              "better answer. The menu below shows what each level of restraint is worth.",
        "zh-Hans": "剩下的每月 {amount}，意味着<b>每一笔可调整支出都要砍掉 {pct}%</b>："
                   "买菜、吃饭、交通，全都要减。这和取消一个订阅是完全不同性质的决定，"
                   "通常更合理的做法是把目标日期往后挪。下面的取舍清单列出了各档力度分别值多少钱。"},
    "verdict_no_history": {
        "en": "There are only {days} days of comparable history so far, so there is no reliable "
              "baseline to find savings against yet. Category totals below are real; the "
              "trade-off figures need about a month of data before they mean anything.",
        "zh-Hans": "目前只有 {days} 天可比较的历史数据，还无法建立可靠的基准来寻找可省的开支。"
                   "下方的分类合计是真实的；取舍数字需要大约一个月的数据才有意义。"},
    "no_candidates_history": {
        "en": "Not enough history yet to tell unusual spending from normal spending. This fills "
              "in as more statement data accumulates.",
        "zh-Hans": "历史数据还不足以区分异常支出和正常支出。随着账单数据积累，这部分会逐渐完善。"},
    "verdict_impossible": {
        "en": "The shortfall is larger than your entire discretionary budget of {amount}/mo. "
              "<b>No amount of spending restraint closes it.</b> A target date or a target "
              "amount has to move.",
        "zh-Hans": "缺口比你全部可调整支出（每月 {amount}）还要大。"
                   "<b>再怎么省也补不上。</b>必须调整目标日期或目标金额。"},

    # --- spending summary ---
    "summary_h": {"en": "Spending summary", "zh-Hans": "支出概览"},
    "typical_month": {"en": "<b>A typical month</b> — averaged over the last 3 complete months.",
                      "zh-Hans": "<b>典型月份</b> —— 按最近 3 个完整月份取平均。"},
    "committed_key": {"en": "Committed {amount}/mo · {pct}%",
                      "zh-Hans": "刚性支出 每月 {amount} · {pct}%"},
    "discretionary_key": {"en": "Discretionary {amount}/mo · {pct}%",
                          "zh-Hans": "可调整支出 每月 {amount} · {pct}%"},
    "only_discretionary": {
        "en": "Only the discretionary half is reachable by any recommendation. Committed money "
              "is already spoken for.",
        "zh-Hans": "任何建议能动的只有可调整的那一半；刚性支出已经被占住了。"},
    "period_actual": {"en": "<b>{period}</b> — what has actually gone out so far.",
                      "zh-Hans": "<b>{period}</b> —— 目前实际花出去的钱。"},

    # --- candidates ---
    "where_from_h": {"en": "Where it can come from", "zh-Hans": "钱能从哪里省出来"},
    "where_from_sub": {
        "en": "Specific, evidenced changes — easiest first. Each one is a single decision, not "
              "an ongoing act of willpower.",
        "zh-Hans": "有据可查的具体调整，由易到难。每一项都是做一次决定就好，不需要靠长期自制力。"},
    "no_candidates": {
        "en": "No unusual spending found — every category is running at its own normal. Use the "
              "trade-off menu below instead.",
        "zh-Hans": "没有发现异常支出 —— 每个类别都在你自己的常规水平上。请参考下方的取舍清单。"},
    "all_of_above": {"en": "All of the above", "zh-Hans": "以上全部"},
    "per_mo_per_yr": {"en": "/mo · {annual}/yr", "zh-Hans": "/月 · 每年 {annual}"},
    "easy": {"en": "easy", "zh-Hans": "容易"},
    "moderate": {"en": "moderate", "zh-Hans": "中等"},
    "hard": {"en": "hard", "zh-Hans": "较难"},
    "confirm_first": {"en": "confirm first", "zh-Hans": "需先确认"},
    "in_the_plan": {"en": "in the plan", "zh-Hans": "已纳入计划"},
    # candidate titles + evidence, composed from `facts`
    "cand_sub_title": {"en": "Cancel or downgrade {merchant}", "zh-Hans": "取消或降级 {merchant}"},
    "cand_sub_ev": {"en": "{amount} charged in each of {months} months, last on {last}",
                    "zh-Hans": "连续 {months} 个月每月扣费 {amount}，最近一次 {last}"},
    "cand_sub_stale": {"en": " — may already be cancelled", "zh-Hans": "；可能已经取消"},
    "cand_sub_health": {"en": " — filed under Health; confirm it is not medical",
                        "zh-Hans": "；归在「健康」类别下，请确认不是医疗必需"},
    "cand_fee_title": {"en": "Eliminate bank and card fees", "zh-Hans": "消除银行和信用卡手续费"},
    "cand_fee_ev": {"en": "{count} fee charges over {months} months ({merchants}) — nothing "
                          "received in return",
                    "zh-Hans": "{months} 个月内有 {count} 笔手续费（{merchants}），没有换来任何东西"},
    "cand_cat_title_usual": {"en": "Bring {category} back to your usual",
                             "zh-Hans": "把「{category}」降回你的常规水平"},
    "cand_cat_title_budget": {"en": "Bring {category} back to budget",
                              "zh-Hans": "把「{category}」降回预算内"},
    "cand_cat_ev": {"en": "averaging {current}/month recently vs a {median} median over "
                          "{months} months",
                    "zh-Hans": "近期平均每月 {current}，而 {months} 个月的中位数是 {median}"},
    "cand_habit_title": {"en": "Halve the {merchant} habit", "zh-Hans": "把 {merchant} 的消费减半"},
    "cand_habit_ev": {"en": "{per_month} visits a month averaging {avg}, about {monthly}/month",
                      "zh-Hans": "每月约 {per_month} 次，单次平均 {avg}，合计每月约 {monthly}"},

    # --- levers ---
    "levers_h": {"en": "The trade-off menu", "zh-Hans": "取舍清单"},
    "levers_sub": {
        "en": "What restraint is actually worth, per category. These are choices, not waste — "
              "the numbers are here so the decision is informed, not so every row gets cut.",
        "zh-Hans": "按类别列出「省一点」到底值多少钱。这些是选择，不是浪费 —— "
                   "列出数字是为了让你做决定时心里有数，而不是要求每一行都砍。"},
    "col_category": {"en": "Category", "zh-Hans": "类别"},
    "col_now": {"en": "Now /mo", "zh-Hans": "当前 /月"},
    "col_buys": {"en": "Buys /mo", "zh-Hans": "每月笔数"},
    "total_discretionary": {"en": "Total discretionary", "zh-Hans": "可调整支出合计"},

    # --- next week ---
    "week_h": {"en": "Next 7 days", "zh-Hans": "未来 7 天"},
    "week_sub": {
        "en": "{days} days left in the month ({pct}% gone). Allowances are what is actually left "
              "in each envelope, spread over the days remaining — not a fresh weekly budget. A "
              "category is flagged when it is further through its money than through the month.",
        "zh-Hans": "本月还剩 {days} 天（已过 {pct}%）。这里的额度是各类别预算里真正剩下的钱，"
                   "按剩余天数摊开，不是重新给的一周预算。当某个类别花钱的速度快过时间流逝的速度时，"
                   "就会被标出来。"},
    "week_no_env": {"en": "No envelopes set, so there is no weekly allowance to compute. Run "
                          "<code>propose-budget</code> first.",
                    "zh-Hans": "还没有设置各类别预算，无法算出每周额度。请先运行 "
                               "<code>propose-budget</code>。"},
    "col_left_month": {"en": "Left this month", "zh-Hans": "本月剩余"},
    "col_next7": {"en": "Next 7 days", "zh-Hans": "未来 7 天"},
    "over_by": {"en": "over by {amount}", "zh-Hans": "已超支 {amount}"},
    "used_ahead": {"en": "{pct}% used, {pts}pts ahead of pace",
                   "zh-Hans": "已用 {pct}%，比进度快 {pts} 个百分点"},
    "used": {"en": "{pct}% used", "zh-Hans": "已用 {pct}%"},
    "spendable_week": {"en": "Spendable this week", "zh-Hans": "本周可花"},
    "already_over": {"en": "Already overspent", "zh-Hans": "已经超支"},

    # --- next month ---
    "month_h": {"en": "Next month’s envelopes", "zh-Hans": "下个月的各类别预算"},
    "month_sub": {"en": "Set these once and the changes above happen by default rather than by "
                        "remembering.",
                  "zh-Hans": "设置一次就好，上面那些调整就会自动生效，不用每次都靠记性。"},
    "freed_per_month": {"en": "Freed per month", "zh-Hans": "每月省出"},
    "new_contribution": {"en": "New monthly contribution", "zh-Hans": "调整后每月存入"},

    # --- effect ---
    "effect_h": {"en": "What that does to {goal}", "zh-Hans": "这对「{goal}」意味着什么"},
    "doing_nothing": {"en": "Doing nothing", "zh-Hans": "什么都不改"},
    "with_changes": {"en": "With these changes", "zh-Hans": "采纳以上调整"},
    "at_rate": {"en": "at {amount}/mo", "zh-Hans": "每月存 {amount}"},
    "months_earlier": {"en": "That is <b>{months} months earlier</b>, against a target of {date}.",
                       "zh-Hans": "比原先<b>提前 {months} 个月</b>，目标日期是 {date}。"},
    "arrives_on_time": {"en": "arrives on time", "zh-Hans": "可按期达成"},
    "still_target": {"en": "target {date}", "zh-Hans": "目标 {date}"},
}


def money(cents: int, currency: str = "USD", sign: bool = False) -> str:
    sym, prefix = CURRENCIES.get(currency, ("$", True))
    body = f"{abs(cents) / 100:,.2f}"
    s = f"{sym}{body}" if prefix else f"{body}{sym}"
    if cents < 0:
        return f"-{s}"
    return f"+{s}" if sign else s


def fmt_date(d: str | date, lang: str) -> str:
    """ISO date -> a natural date string for the language."""
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d)
        except (ValueError, TypeError):
            return str(d)
    if lang == "zh-Hans":
        return f"{d.year}年{d.month}月{d.day}日"
    return d.strftime("%b %d, %Y").replace(" 0", " ")


def period_label(kind: str, start: str, end: str, lang: str) -> str:
    """Label a reporting period without relying on English month names."""
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
    except (ValueError, TypeError):
        return start
    if lang == "zh-Hans":
        if kind == "week":
            return f"{s.year}年{ZH_MONTHS[s.month]}{s.day}日当周"
        if kind == "days":
            return f"最近 {(e - s).days + 1} 天"
        return f"{s.year}年{ZH_MONTHS[s.month]}"
    if kind == "week":
        return f"Week of {s:%b %d, %Y}".replace(" 0", " ")
    if kind == "days":
        return f"Last {(e - s).days + 1} days"
    return f"{s:%B %Y}"


# Category and difficulty names are data values, translated for display only.
CATEGORY_NAMES = {
    "zh-Hans": {
        "Income": "收入", "Housing": "住房", "Utilities": "水电网", "Groceries": "买菜",
        "Dining": "外出就餐", "Transport": "交通", "Health": "医疗健康", "Insurance": "保险",
        "Childcare": "育儿", "Shopping": "购物", "Entertainment": "娱乐", "Travel": "旅行",
        "Education": "教育", "Debt": "债务", "Savings": "储蓄", "Transfer": "转账",
        "Fees": "手续费", "Other": "其他", "Uncategorized": "未分类",
    }
}


class Translator:
    """Bound to one language and currency; used by the renderers."""

    def __init__(self, lang: str = "en", currency: str = "USD"):
        self.lang = lang if lang in LANGS else "en"
        self.currency = currency

    def __call__(self, key: str, **kw) -> str:
        entry = STRINGS.get(key)
        if not entry:
            return key
        template = entry.get(self.lang) or entry["en"]
        try:
            return template.format(**kw)
        except (KeyError, IndexError):
            return template

    def money(self, cents: int, sign: bool = False) -> str:
        return money(cents, self.currency, sign)

    def date(self, d) -> str:
        return fmt_date(d, self.lang)

    def period(self, period: dict) -> str:
        return period_label(period.get("kind", "month"), period.get("start", ""),
                            period.get("end", ""), self.lang)

    def category(self, name: str) -> str:
        return CATEGORY_NAMES.get(self.lang, {}).get(name, name)

    @property
    def is_cjk(self) -> bool:
        return self.lang.startswith("zh")
