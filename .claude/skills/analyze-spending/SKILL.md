---
name: analyze-spending
description: Analyze household spending for a week or any period, judge progress against the budget and savings goal, and publish the HTML dashboard. Use when the user asks about spending, their budget, "how did we do", where money went, whether they are on track to save, or asks for the weekly review.
---

# Analyze spending

You are the household's budget analyst. The Python layer does every calculation;
you do the judgment. **Never compute a total, variance, or pace yourself — read
it from `report --json`.** Arithmetic you do by hand will disagree with the
dashboard, and the user will trust the wrong one.

## Run this sequence

### 0. The period is the calendar month

**Track months, 1st to end of month.** The budget is monthly, the envelopes are
monthly, and the commitments fall on fixed days, so a week or a rolling 30 days
compares against something the household never agreed to. `month` is the default
for `report` and `dashboard`; use another period only when explicitly asked.

The one exception is the opening stretch, where `analysis_start` sits mid-month
because card coverage began then. Say so - "September, from the 7th" - and treat
the first complete month as the first real comparison.

### 0b. Check the analysis window

```bash
python3 -m budget status
```

If it prints `analysis from: <date>`, **every number is scoped to that window**
and earlier rows are stored but deliberately excluded. It exists because card
exports cover a short recent period while checking goes back years; averaging
across that boundary makes every category total and trailing median read low.

Two consequences you must respect:

- **Say the window out loud** when reporting. "Spent $5,739" means nothing
  without "over 12 days".
- **A short window cannot support trailing comparisons.** Below ~28 days,
  `gap.sufficient_history` is false, `cut_depth_needed` is null, and the
  optimizer has no baseline. Report category totals, which are real, and say
  the trade-off figures need about a month. **Never conclude "no amount of
  restraint closes the gap" from a zero baseline** - that is a confident claim
  built on missing data.

Savings and income deliberately ignore the clamp: they come from checking,
which is complete. Only spending is scoped.

### 0c. Check every account is actually represented

```bash
python3 -m budget report --json    # read the `coverage` block
```

**A statement that was never uploaded does not look like missing data - it looks
like a month where that card was not used.** Totals come out low and nothing
says why. So before reporting any figure:

- `coverage.missing` - accounts with no transactions in the period at all.
- `coverage.stale` - accounts whose newest transaction predates the period end
  by more than a week; the latest statement probably has not been uploaded.

**Name them.** "Spending was $2,030, but card-b has nothing since the 7th,
so this is a floor" is useful; "$2,030" alone is misleading. Ask the household to
export the missing ones before drawing conclusions about a month.

### 1. Ingest anything waiting

```bash
python3 -m budget status --json
```

If `inbox_files` is non-empty, run the **ingest-transactions** skill first, then
come back. If `transactions` is 0, there is nothing to analyze — tell the user to
drop bank CSVs into `data/inbox/` and stop.

### 2. Clear the uncategorized queue

```bash
python3 -m budget recategorize          # re-apply rules to stored rows first
python3 -m budget uncategorized --json
```

Uncategorized transactions silently distort every number below them, so resolve
them before analyzing. For each merchant, decide the category from
`sample_description` and the amount, using the list in `budget/schema.py`
(`CATEGORIES`). Then:

```bash
python3 -m budget categorize Dining --merchant "<exact key from --json>" --subcategory Restaurant --learn
```

**Copy the merchant key from the JSON output.** It is a normalized string, and
typing an approximation updates 0 rows while still printing success.

Three categories are easy to confuse and all three are excluded from spending:

| | meaning |
|---|---|
| `Transfer` | money between the household's own accounts, card payments, HSA/FSA reimbursements |
| `Savings` | explicit transfers to savings; only used by the `"transactions"` model |
| `Retirement` | IRA/401k - real money leaving, but **not** progress against a monthly savings rate |

A yearly IRA contribution filed as `Savings` would flatter one month and starve
eleven. If a goal genuinely receives a lumpy contribution, set `measure_months`
on it (12 for annual) and `contribution_cadence` so the plan amortizes.

`--learn` writes the mapping to `config/rules.json` so the merchant never
reaches you again. Always pass it when you are confident.

**Ask the user, do not guess, when:**
- the merchant is ambiguous between a personal and a household category, or
- the amount is over $500 and the category changes the budget picture, or
- it could be a transfer between their own accounts (that would wrongly count as
  spending — check `find_internal_transfers` output or just ask).

Batch your questions into one message. Do not ask about a $12 charge.

### 3. Pull the numbers

```bash
python3 -m budget report --period week --json
```

Periods: `week`, `last-week`, `month`, `last-month`, `YYYY-MM`, `N-days`.
Match the period to what the user asked for; default to `week`.

### 3b. Income needs no reporting

**Unless it has never been established.** If `income.json` holds round numbers
($6,500, $8,200) rather than figures derived from real deposits, the spending
ceiling is built on a guess. Run `python3 -m budget income-audit`, show the
household the derivation, and confirm before trusting any ceiling figure. The
manage-budget skill has the procedure.


Income is configured, not tracked. `report --json` carries an `income_check`
block; if `ok` is true, say nothing about income. If it is false, the ceiling is
built on a wrong number - surface that once and point at `budget ui`.

Never present observed deposits as a metric, and never report an account
balance. The household's question is whether spending stayed under the ceiling.

### 3c. Month-over-month needs whole months

`monthly_history.months` is empty until a complete month sits inside the
analysis window. When it is empty, say so and name
`first_complete_month` - do not reach for partial data to fill the gap.

### 4. Read the report like an analyst

Work through it in this order, because this is the order that matters to the
household:

1. **The monthly budget** (`month_to_date`): `free_monthly_cents`,
   `spent_cents`, `remaining_cents` and `pct_used`. Always quote `pct_used`
   together with `pct_month_observed` - when the window starts mid-month the
   spend figure is a floor and the percentage flatters. Then the period view
   (`cashflow.period`). This is the headline:
   `free_budget_cents` for the period, `discretionary_spent_cents` against it,
   and `savings_remaining_cents` - how much of the period's savings target
   survived the overspend. Report total spending only as context; the household
   cannot move its mortgage. `cashflow.monthly.free_cents` is the same idea per
   month. **If it is
   negative, that is the story** — no amount of cutting groceries fixes a
   household whose commitments and goals exceed its income, and every other
   finding is noise next to it. Say it first and name the three levers: move a
   goal date, lower a target, or cut a commitment.
2. **The savings goals** (`goals`, and `savings` for the primary). Under the
   default residual model savings is **income minus spending**, so there are no
   contributions to look for. Lead with the ceiling:
   `spending_ceiling_cents` vs `actual_spend_monthly_cents`, and
   `overspend_monthly_cents` when they are over. Never report "saved $0" - if
   nothing was transferred that is the normal case, not a failure. For a
   transactions-model goal, read three fields, not one: `required_monthly_cents` (what the date demands),
   `planned_monthly_cents` (what they committed to), `observed_monthly_cents`
   (what moved). `following_plan: true` with `plan_covers_goal: false` means
   they are doing exactly what they promised and will still miss — say that the
   *plan* is wrong, never that they are overspending. `projected_at_plan` is
   when they arrive if they keep following it.
3. **Commitments** - two views. `commitment_tracker` is the standing list:
   every declared commitment with its last payment, next due date and a status
   of `on_track` / `overdue` / `drift` / `never_seen`. Lead with anything that
   is not `on_track`; an overdue semiannual insurance bill is easy to miss and
   costs real money. `commitments` is the narrower per-period check. A `missing` row means a
   fixed expense never posted — a real problem worth surfacing immediately. A
   `drift` row means the amount changed; say by how much and annualize it.
4. **What is unusual** (`anomalies`), not what is large. Rent is the biggest
   line every month and is never news. A `category_spike` at 2× with a
   `ratio` well above 1 is news.
5. **Budget variance** (`budget`). Report `status: "over"` rows. Distinguish a
   category that is over because of one purchase from one that is over because
   of a habit — look at `txn_count` and the merchants behind it. Categories
   covered by a declared commitment are already excluded here.
6. **Recurring charges** (`recurring`). `annualized_cents` is the number that
   changes minds: "$53/mo" is easy to ignore, "$636/year" is not.
7. **Where a recommendation can land.** Fixed commitments are hard to move this
   month; `cashflow.committed_categories` names them. Dining, Shopping,
   Entertainment and Travel are where advice can actually be acted on.

### 5. Pull the optimization candidates

```bash
python3 -m budget recommend --period month --json
```

This is the deterministic answer to "what can be optimized". Read it as:

- **`gap.gap_cents`** — how much more per month the goals need.
- **`candidates`** — specific, evidenced changes, each with `saving_monthly_cents`,
  `difficulty` and the `evidence` behind it. A candidate with
  `needs_confirmation` (a gym filed under Health) must be asked about, not asserted.
- **`gap.cut_depth_needed`** — if named candidates cannot close the gap, how deep
  an across-the-board discretionary cut would have to go. It is `null` when
  there is not enough history; check `gap.sufficient_history` before quoting
  anything from it. **When `achievable` is false, say plainly that no amount of
  spending restraint closes the gap and the date or target has to move.** Do not
  assemble a list of small cuts to look responsive.
- **`levers`** — the trade-off menu: what 10/25/40% off each category is worth.
  Use this when there are no anomalies to cut, which is the common case for a
  household already living at its own normal.
- **`next_week`** — per-category allowances for the coming 7 days, and which
  categories are `tight` (further through their money than through the month).
- **`next_month`** — envelope changes that deliver the identified savings.

Two rules when writing this up:

- **Never invent a saving.** Every number comes from this payload.
- **Separate "cancel a subscription" from "eat out less".** The first is one
  decision that holds forever; the second is an ongoing act of willpower. Ranking
  them together as equivalent line items is how budget advice loses credibility.

### 6. Write the narrative

Write to `/tmp/narrative.json`:

```json
{
  "summary": "2-4 sentences. What actually happened and what it means for the goal.",
  "recommendations": [
    {"action": "Short imperative", "rationale": "Why, with the number behind it", "impact_cents": 6798}
  ]
}
```

Rules for the narrative:
- **Separate the one-off from the pattern.** A $1,180 laptop is not a spending
  problem; buying $300 of takeout every week is. Say which one you are seeing.
- **Every claim carries its number**, and the number comes from the JSON.
- **At most 3 recommendations**, ordered by `impact_cents`. Three things a
  household might do beats ten things they will not.
- Set `impact_cents` only when you can source it (a subscription's
  `typical_cents`, the amount a category is over). Use `0` when the
  recommendation is a decision rather than a saving.
- **No moralizing.** Report what the money did. They know eating out is
  expensive; they need to know it was $340 this week against a $150 envelope.
- If they are on track, say so plainly and keep it short. A good week does not
  need three paragraphs.

### 6b. Keep the reminders honest

The dashboard opens with **Needs doing**: reminders the household asked to keep,
plus spending actions derived from this month's own budget.

```bash
python3 -m budget remind                      # list
python3 -m budget remind "..." --tag tax --due 2026-11-15 --detail "..."
python3 -m budget remind --done fsa-limit     # clear it
```

Add one when something needs acting on later - a tax exposure, an election to
change, a statement to re-export. Clear it once done; a stale reminder trains
the household to ignore the block. Spending actions are generated, not stored,
so never add one by hand.

### 7. Publish the dashboard

```bash
python3 -m budget dashboard --period week --narrative /tmp/narrative.json
python3 -m budget recommend --period month --html      # the what-to-do-next page
```

Both print their path. Tell the user where they are and give the headline in two
or three lines of chat — do not paste the whole report back.

## Guardrails

- If `config_warnings` is non-empty, surface it once, and point at
  `python3 -m budget ui` as the way to fix it. A household with no income or no
  savings goal set cannot be told whether it is on track, and pretending
  otherwise is the worst failure this tool has.
- Fixed expenses are never added to spending — they already arrive in the
  checking CSV. If a total looks doubled, suspect a commitment being counted
  twice and check `commitments` against the ledger.
- Never invent a number that is not in the JSON. If the user asks something the
  report does not answer, query the ledger directly with `report --period` for
  another window rather than estimating.
- Transaction data is private. Never send it to a web search, an external API,
  or any tool outside this repo. **Generated reports contain the full financial
  picture** - write them to `reports/` (gitignored) and give the user the path.
  Do not publish them to a hosted link unless the user asks for that explicitly.
- Report the window with every figure, and name what is missing. A total that
  excludes a card with no statement is not wrong, but presenting it without
  saying so is.
