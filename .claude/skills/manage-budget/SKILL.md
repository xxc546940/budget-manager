---
name: manage-budget
description: Set or revise the household's income, fixed expenses, budget envelopes, and savings goals. Use when the user wants to change their budget, add a mortgage or car loan, set a savings target, says they got a raise, asks what a realistic budget would be, or asks what it would take to hit a goal.
---

# Manage the inputs

Four JSON files under `config/`, each one thing:

| File | Holds | Changes when |
|---|---|---|
| `income.json` | net pay per source, effective-dated | a raise or job change |
| `fixed_expenses.json` | mortgage, car loan, daycare, utilities, insurance | you sign something |
| `goals.json` | savings goals, priority-ordered | rarely; matters most |
| `budget.json` | discretionary envelopes + household settings | as habits change |

**Offer the UI first.** `python3 -m budget ui` opens a local form at
127.0.0.1:8765 that writes these same files, with live totals as they type. For
anything more than a one-field change, that beats a string of CLI flags.

## Income

The configured figure is the basis for the entire spending ceiling, so it must
be correct. It is not something to report on week to week - but it must be
**established properly once, with the household, before it is trusted.**

### Never accept a round monthly number

A figure like "$8,200/month" is a guess until the ledger agrees with it. Derive
it instead:

```bash
python3 -m budget income-audit
```

This groups deposits by employer, works out the pay cadence from the gaps
between them, sets one-offs aside, marks former employers inactive, and shows
the implied monthly figure against what is configured.

**Then show the household the derivation and ask them to confirm it, before
writing anything.** Three things make the automatic answer wrong often enough
that it must not be applied silently:

- **Biweekly and semimonthly look identical at a glance and differ by 8%.**
  26 payslips a year is not 24, and the spending ceiling moves with the error.
- **A job change makes a long average meaningless.** Only `active` streams count.
  Confirm the household has not just changed or added a job.
- **A signing bonus or back-payment inflates any mean.** The audit sets them
  aside as `one_offs`; ask whether each really was a one-off.

Present it plainly - "your deposits show $3,250 twice a month, which is
$6,500/month, not the $7,000 configured; is that right?" - and apply only after
they say yes:

```bash
python3 -m budget set-income 6500 --name second_salary --cadence semimonthly
```

Pass `--cadence` on updates too; without it the existing label is kept, and a
wrong label misleads the next person to read the file.

### Afterwards, leave it alone

Once established, the analyzer checks it in the background and raises a config
warning only when deposits drift more than 10% from the configured figure over
the trailing 3 months. If no warning appears, do not mention income at all.

**That background check will not catch a per-person error**, because it compares
household totals - two errors in opposite directions cancel. Only
`income-audit` looks per earner, so run it when income is first set up, when
anyone changes job, and if a household ever asks why a figure looks wrong.

Do not "reconcile" observed deposits against the configured figure in a report,
and do not track account balances. Neither is the household's question.

### When pay changes, use `--replace`

```bash
python3 -m budget set-income 3800 --name "Salary - Member B" --replace --since 2026-07-01
```

This closes the old entry the day before and opens a new one, so re-running an
older month still uses the pay they had then. Editing the amount in place
silently rewrites history. The UI's "Replace" button does the same.

### Income that never arrives as a deposit

A pre-tax benefit - a dependent-care FSA - is real spendable money deducted
before the paycheck, so it never appears as a deposit:

```bash
python3 -m budget set-income 356.35 --name dependent_care_fsa --not-deposited
```

`--not-deposited` keeps it out of the deposit comparison; without it every audit
reports a permanent shortfall that no re-export can fix. Use the **after-tax**
value: if contributions exceed a limit, the excess is taxable and the benefit is
worth less than its face amount.

## Fixed expenses

```bash
python3 -m budget add-fixed "Mortgage" 2850 --category Housing --due-day 1 --match "sunset apartments"
python3 -m budget add-fixed "Electric" 142 --category Utilities --due-day 5 --match "pg&e" --variable
```

Two things to get right:

- **`--match`** is how a declared commitment is tied to the real transaction.
  Use distinctive text from the bank description, not the friendly name. Check
  it worked with `python3 -m budget commitments --period last-month`.
- **`--variable`** for bills that move every month (utilities). Without it, a
  normal seasonal swing gets flagged as unexpected drift every single month, and
  the household learns to ignore the warnings.

Declaring these does **not** add them to spending — they already arrive in the
checking CSV. It buys three things: confirmation each one posted, a flag when an
amount changes, and an honest free-to-spend figure.

### Removing a commitment

One that turns out to be a one-off inflates the fixed total and understates
free-to-spend for every future month:

```bash
python3 -m budget remove-fixed "Naperville utilities"
```

It prints the new monthly total and free-to-spend figure, and lists what is
declared if the name does not match. Watch for this whenever a "recurring"
charge has only been seen once or twice - the cadence was a guess.

## Savings goals

```bash
python3 -m budget set-goal "House down payment" --target 120000 --by 2029-06-01 \
  --current 38500 --as-of 2026-09-01 --funded-from vanguard --priority 1
```

With more than one goal, set `--funded-from` on each (text matching the account
or transfer description). Otherwise the first goal claims every savings transfer
and the second reads $0/month forever.

### How savings is measured

`settings.savings_model` is `"residual"` by default: **savings is income minus
spending**, not a transfer. The household need never move money anywhere; the
goal is simply not to spend it.

State the goal as a ceiling, because that is the actionable form:

```
spending ceiling = after-tax income - target savings
```

At $10,000/mo income and a 5% target that is **$9,500/mo**. Under it, the goal
is met; over it, the overspend is exactly what has eaten the target. Report
`spending_ceiling_cents`, `actual_spend_monthly_cents` and
`overspend_monthly_cents` rather than talking about contributions.

Switch to `"transactions"` only for a household that genuinely does sweep money
into a separate account and wants that tracked instead.

### Two kinds of goal

**Default to a rate goal.** Most households do not have a dated target; they
want to save a share of what they earn:

```bash
python3 -m budget set-goal "Monthly savings" --rate 20
```

No target amount, no date. Success is whether the money moved, so
`on_track` compares `observed_monthly_cents` against
`required_monthly_cents` (which for a rate goal is just the percentage of net
income). Never quote a projected completion date for one — there is no finish
line, and the field is deliberately `None`.

Only use a target goal when the user names a specific sum **and** a date. Do not
invent either to make a goal "complete"; a rate goal is complete as it stands.

### Contribution plans

Each goal gets one of three plans:

```bash
python3 -m budget set-goal "House down payment" --percent 15   # % of AFTER-TAX income
python3 -m budget set-goal "Emergency fund" --contribute 300   # flat dollars per month
python3 -m budget set-goal "New car" --auto-contribute         # whatever the date requires
```

**Prefer `--percent` when the household wants saving to scale with income** — it
adjusts itself on a raise without anyone remembering to change it. Prefer
`--contribute` when the amount is genuinely fixed (an automatic transfer they
have already set up).

Percentages are always of **net, after-tax** income. Never apply one to a gross
figure, and never record gross income: `monthly_income()` ignores any source
whose `basis` is not `"net"`, and `set-income --gross` is refused.

### Three numbers, kept apart

- `required_monthly_cents` — what the target and date demand
- `planned_monthly_cents` — what they committed to contribute
- `observed_monthly_cents` — what actually left the account

Report the right failure. `following_plan: true` with `plan_covers_goal: false`
means they are doing exactly what they said and will still miss — the plan is
wrong, not their behavior, and telling them to "try harder" would be wrong.
`following_plan: false` is the opposite problem.

## Setting envelopes

Never invent amounts. Derive them:

```bash
python3 -m budget propose-budget --months 3
```

The current partial month is excluded and lumpy categories are amortized, so the
numbers are usable as-is. Categories already covered by a fixed expense are left
out — a mortgage is not a weekly envelope.

Present the proposal and ask which they want to *change*, not ratify. A budget
identical to last quarter's spending is a description, not a plan.

## When they ask "can we afford this?"

```bash
python3 -m budget commitments --period month
```

The last line is the whole answer: `after-tax income − fixed − planned savings =
free`. Two distinct failures, and they need different advice:

- **`free_cents` negative** — the plan does not fit inside their income. Something
  has to shrink now.
- **`plan_shortfall_cents` negative** — the plan fits, but following it perfectly
  still misses the goal dates.

Saying which one plainly is the single most valuable thing this tool does. Lay
out the three levers with the numbers attached:

1. **Move a date** — `projected_completion` per goal is when they actually arrive.
2. **Raise the contribution** — name where it comes from, using over-budget
   categories and `recurring` subscriptions. A recommendation without a source
   is a wish.
3. **Lower a target**, or deprioritize the second goal until the first lands.

Give them the arithmetic, not encouragement.

## The analysis window

`settings.analysis_start` in `config/budget.json` scopes all spending analysis.
Set it to the date from which the household's card coverage is comparable -
usually the latest "first transaction" date across the card accounts:

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
import sqlite3; from budget.ledger import DB_PATH
c = sqlite3.connect(DB_PATH)
print(max(r[0] for r in c.execute(
  \"SELECT MIN(date) FROM transactions WHERE account NOT LIKE '%checking%' GROUP BY account\")))"
```

Raise it when a new card with no history joins; lower it as exports backfill.
Spending is clamped to it; savings and income are not, because they come from
checking which is complete.

## Lumpy contributions

A goal can receive money on a cadence other than monthly:

- `contribution_cadence: "annual"` amortizes a $7,500 IRA contribution to
  $625/month in the plan, instead of one huge month and eleven empty ones.
- `measure_months: 12` widens the observed-savings lookback to match, so the
  same lump is not read as three empty months.

## Guardrails

- Changing config mid-analysis moves the numbers under the user. Finish the
  analysis, then adjust.
- Propose config changes; don't apply them unasked.
- After any change, re-run `python3 -m budget report` so they see the effect.
