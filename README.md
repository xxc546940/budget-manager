# budget-manager

A Claude Code agent harness that reviews your household's spending — weekly, or
whenever you ask — and tells you whether you're still on track for your savings
goal.

Point it at the CSVs your bank lets you download. It parses them, categorizes
the transactions, compares the result to your budget, and publishes an HTML
dashboard with a written read on the week.

## Setup

No install step — standard library only.

```bash
python3 -m budget ui
```

Opens a local page at `http://127.0.0.1:8765` with four tabs — income, fixed
expenses, savings goals, envelopes — plus drag-and-drop for your CSVs. It writes
to `config/*.json`, which is also where the CLI and the agent read from. Nothing
leaves the machine; the server binds to localhost only.

Prefer the command line:

```bash
# Income, effective-dated so old months stay accurate
python3 -m budget set-income 4120 --name "Salary - Member A" --cadence semimonthly
python3 -m budget set-income 3800 --name "Salary - Member B" --replace --since 2026-07-01

# Commitments you have already made
python3 -m budget add-fixed "Mortgage" 2850 --category Housing --due-day 1 --match "sunset apartments"
python3 -m budget add-fixed "Car loan" 480 --category Debt --due-day 5 --match "toyota financial"
python3 -m budget add-fixed "Daycare" 1850 --category Childcare --due-day 12 --match daycare
python3 -m budget add-fixed "Electric" 142 --category Utilities --due-day 5 --match "pg&e" --variable

# A savings goal. Usually this is all you need:
python3 -m budget set-goal "Monthly savings" --rate 20      # save 20% of after-tax income

# Or a specific sum by a specific date, if you have one:
python3 -m budget set-goal "House down payment" --target 120000 --by 2029-06-01 \
    --current 38500 --as-of 2026-09-01 --funded-from vanguard --percent 15

# Transactions
python3 -m budget ingest --dry-run      # check what it detected
python3 -m budget ingest --archive

# Envelopes from your own actuals
python3 -m budget propose-budget --months 3
python3 -m budget set-budget Dining 600
```

## Your inputs

| File | Holds |
|---|---|
| `config/income.json` | net pay per source, effective-dated |
| `config/fixed_expenses.json` | mortgage, car loan, daycare, utilities, insurance |
| `config/goals.json` | savings goals, priority-ordered |
| `config/budget.json` | discretionary envelopes, household settings |
| `data/inbox/` | bank CSV exports |

**All of these are gitignored.** The repo tracks `*.example.json` templates
instead, and a fresh clone seeds the real files from them on first run. Your
income, mortgage amount, balances, transactions and reports never enter git
history.

### The date fields on income are optional

`effective_from` / `effective_to` have nothing to do with how often you're paid
(that's `cadence`). **Leave both blank and the entry is always in effect** —
which is what you want if your pay is steady. You never have to touch them.

They exist for one case: pay *changing*. Declared income is what short periods
are measured against, since a single week doesn't contain a full paycheck. With
one undated entry, re-running an old month applies today's salary retroactively
— roughly an 8% error on a past month's baseline after a typical raise. Closing
the old entry instead keeps history honest.

So when your pay changes, use `--replace` on the CLI or the **Replace** button in
the UI, and it handles the dates for you. Editing the amount in place is the one
thing that silently rewrites history.

### Establishing income: derive it, do not guess it

A round monthly figure is a guess until the ledger agrees with it:

```bash
python3 -m budget income-audit
```

```
  account             employer                    n cadence        per check   per month
  checking-b          northwind payroll           8 semimonthly    $3,250.00   $6,500.00
  checking-a          contoso payroll            13 biweekly       $2,800.00   $6,066.67
                        one-off 2026-03-20  $12,000.00 (excluded)
  checking-a          initech payroll             7 biweekly       $2,600.00   $5,633.33  (ended)

  implied from actual deposits     $12,566.67/month
  configured as deposits           $12,566.67/month
  -> agrees (within $0.00)
```

It reads the cadence from the gaps between deposits, sets one-offs aside, and
marks former employers inactive so they do not pollute the average.

**Biweekly and semimonthly are the trap.** Both pay "roughly twice a month", but
26 payslips a year is 8% more than 24. Getting that wrong can overstate an earner by
several hundred a month — and since the spending ceiling is income minus the
savings target, the ceiling moves with it. Flat 14-day gaps are biweekly; gaps that
wander with month length are semimonthly.

Confirm the derivation before applying it — a bonus, a missed period, or a very
recent job change can all skew the annualization.

### Income is configured, then checked in the background

The spending ceiling is derived from `income.json`, so that figure has to be
right — but observed deposits are not a weekly metric and account balances are
never tracked. The analyzer compares the configured figure against actual
deposits over the trailing 3 months and warns only if they diverge by more than
10%. That check compares household *totals*, so it cannot catch a per-person
error whose halves cancel out — `income-audit` is the one that looks per
earner. Three months rather than twelve, because a job change makes an accurate
figure look wrong over a longer window.

### Income is after-tax, and the tool enforces it

Every income figure is **net (take-home)**. Savings goals can be set as a
percentage of it, so a gross number would commit money that never reaches the
account. A source marked `"basis": "gross"` is excluded from every calculation
and flagged, and `set-income --gross` is refused outright rather than silently
converted.

### Savings goals

Most of the time a goal is just a rate:

```bash
python3 -m budget set-goal "Monthly savings" --rate 20
```

**Save 20% of after-tax income every month.** No target amount, no target date,
no projected completion.

Savings is measured as **income minus spending**, not as a transfer — most
households never move money to a savings account, and measuring transfers would
report 0% forever. So the goal restates as a **spending ceiling**, which is the
actionable form:

```
spending ceiling = after-tax income − target savings

1%   of after-tax income kept, against a 5% goal     ⚠ Overspending $593/mo
     ceiling $13,965/mo · actually spending $14,558/mo · over by $593/mo
```

Staying under the ceiling *is* hitting the goal. Set
`settings.savings_model: "transactions"` if your household genuinely does sweep
money into a separate account and wants that tracked instead.

A percentage **scales automatically with a raise**, which is the reason to
prefer it over a flat figure. `--contribute 300` sets a fixed monthly amount
instead.

**Target goals** are for when you genuinely are saving a specific sum by a
specific date:

```bash
python3 -m budget set-goal "House down payment" --target 120000 --by 2029-06-01 \
    --current 38500 --as-of 2026-09-01 --funded-from vanguard --percent 15
```

These additionally report whether the contribution plan is big enough to arrive
on time, so the tool can say *"you are following your plan exactly, and your
plan still misses the date by three years"* — which a rate goal has no need for.

Both kinds can coexist, and `--funded-from` keeps their contributions separate.

**The shortfall is always measured against money that actually moved**, not
against what you intended. For a rate goal the plan and the requirement are the
same number, so comparing those would read "on track" even in a quarter where
nothing was saved.

### Fixed expenses are not extra spending

Your mortgage already arrives in the checking CSV. Declaring it doesn't add it
again — it lets the analyzer confirm it posted, flag when the amount changes,
and compute what is genuinely free:

```
after-tax income − fixed commitments − planned savings = free to spend
```

Free-to-spend subtracts what you *plan* to save, because that is what actually
leaves the account. Separately, the report says whether that plan is enough to
reach the goals on time. Those are two different failures and they get two
different verdicts:

- **"Short $X/mo"** — the plan does not even fit inside your income.
- **"Plan fits, dates do not"** — you can afford the plan, but following it
  perfectly still misses the goal dates.
- **"Goals fully funded"** — the plan fits and reaches every goal on time.

```bash
python3 -m budget commitments --period last-month
```

## Using it

In Claude Code, just ask:

> how did we do last week?
> are we still on track for the down payment?
> what would it take to hit the goal by 2028?

That routes to the skills in `.claude/skills/`. Or run the pieces yourself:

```bash
python3 -m budget ui                      # input forms (localhost)
python3 -m budget recommend               # what to optimize + next week/month
python3 -m budget recommend --html        # the recommendations page
python3 -m budget status                  # what's in the ledger
python3 -m budget report --period week    # terminal report
python3 -m budget commitments             # did the fixed bills post?
python3 -m budget dashboard --period week # HTML -> reports/
python3 -m budget uncategorized           # merchants needing a category
```

Periods: `week`, `last-week`, `month`, `last-month`, `2026-07`, `30-days`.

## What it handles

**Bank formats.** It sniffs each file rather than requiring a fixed layout:
junk preamble rows, comma/semicolon/tab delimiters, US and EU number formats,
`MM/DD` vs `DD/MM` dates, single signed amount columns, separate debit/credit
columns, and credit-card exports that list charges as positive. It prints what
it inferred so you can catch a wrong guess before it reaches the ledger —
`--flip` / `--no-flip` override the sign detection.

**Re-importing.** Ingest is idempotent. Download "last 90 days" every week and
overlapping rows are recognized and skipped. Manual recategorizations survive.

**Categorization.** ~150 seed rules cover common merchants. Anything unmatched
is left blank for the agent, which classifies it and writes the answer back to
`config/rules.json` — so each unknown merchant costs you one decision, once.

**Transfers.** Card payments and moves between your own accounts are excluded
from spending, so paying off a card doesn't double-count every purchase on it.

## What the report tells you

- **Free to spend** — income minus commitments minus goal contributions. The
  number most budgets never show you.
- **Savings goals** — per goal: what you need per month, what you're actually
  saving, and the date you'll really arrive at the current pace. Goals funded
  from different accounts are tracked separately.
- **Commitment check** — whether each fixed bill actually posted, and whether
  the amount moved.
- **Budget vs actual** — monthly envelopes prorated to the period.
- **Anomalies** — categories running above *their own* trailing norm, large
  charges, first-time merchants. Not just "rent is big."
- **Recurring charges** — detected subscriptions, annualized.
- **Trend** — spending, income and savings over the last 8 weeks.

## The recommendations page

```bash
python3 -m budget recommend --html
```

Answers three questions in one page:

**What can be optimized?** Ranked, evidenced candidates — detected subscriptions
(with the charge history behind them), fees, categories running above their own
trailing median, and frequent-small-purchase habits. Each carries a monthly and
annual figure and a difficulty. Committed categories (housing, childcare,
medical, insurance, debt) are never proposed for cutting; a *subscription* filed
under Health is surfaced but flagged for you to confirm it isn't medical.

**And if that isn't enough?** A trade-off menu showing what 10/25/40% off each
discretionary category is actually worth. When named candidates can't close the
gap, the page states how deep an across-the-board cut would have to go — and
when the gap exceeds your entire discretionary budget, it says plainly that no
amount of restraint closes it and the date or target has to move, rather than
assembling small cuts to look responsive.

**What do I do now?** Per-category allowances for the next 7 days, computed from
what's actually left in each envelope over the days remaining. A category is
flagged when it is further through its money than through the month — 80% spent
is fine on the 25th and alarming on the 8th. Then next month's envelope changes,
and what all of it does to your goal date.

Savings are never double counted: subscriptions are extracted before category
targets are computed, and the envelope cuts reconcile exactly with the
identified total.

## Languages

The recommendations page renders in English or Simplified Chinese:

```bash
python3 -m budget recommend --html --lang zh-Hans
python3 -m budget recommend --html --lang zh-Hans --currency CNY
```

Or set it once in `config/budget.json` under `settings.lang`. Language and
currency are independent — a Chinese-language page with USD amounts is the
normal case for a Chinese-speaking household banking in the US.

Wording lives in `budget/i18n.py` as a string table, so adding a language is a
data change, not a code change. The data layer stays language-free: `optimize.py`
emits numbers and a `facts` dict, and the renderer composes the sentence — which
is why candidate titles like "Cancel or downgrade Netflix" translate properly
instead of being English strings passed through. Merchant names are never
translated; they stay as the bank wrote them.

Two tests guard this: one asserts every string has every language, another that
translations keep the same `{placeholders}` as the English (a dropped
placeholder silently renders a sentence with a number missing).

**Not yet localized:** the dashboard (`report_html.py`) and the input UI. Both
can use the same layer; they just need their strings moved into the table.

## Emailing the report

Reports are written to a stable path so the mailer never has to guess which is
current:

```
reports/latest-dashboard.html          <- always the newest
reports/latest-recommendations.html
reports/archive/dashboard-<timestamp>.html   <- previous copies
```

Generating a report moves the previous `latest-*` into `reports/archive/` rather
than overwriting it.

Set up a Gmail **app password** once (needs 2-Step Verification on the account):

```bash
# https://myaccount.google.com/apppasswords
printf '%s' 'your16charapppw' > ~/.budget-gmail-app-password
chmod 600 ~/.budget-gmail-app-password
```

Then send:

```bash
python3 -m budget dashboard                       # refresh the report
python3 scripts/send_report.py \
    --password-file ~/.budget-gmail-app-password \
    --from you@gmail.com --to you@gmail.com
```

### Several recipients

`--to` repeats, comma-separates, or both, and accepts display names:

```bash
python3 scripts/send_report.py --password-file ~/.budget-gmail-app-password \
    --from you@gmail.com \
    --to "Jun <jun@example.com>" --to "xue@example.com, someone@else.com" \
    --cc accountant@example.com --bcc archive@example.com
```

Addresses are de-duplicated case-insensitively, anyone already in `--to` is
dropped from `--cc`/`--bcc` so nobody gets two copies, and a malformed address
stops the send rather than being silently skipped. `Bcc` is passed in the
envelope only — it never appears in the message headers. With no `--to` at all
it mails you.

In `config/budget.json`, `email_to` / `email_cc` / `email_bcc` each take a
single address or a list:

```json
"email_to": ["jun@example.com", "xue@example.com"]
```

`--dry-run` prints what would be sent without connecting. `--report` picks a
different file, `--attach` adds the HTML as an attachment as well as inline, and
`--subject` overrides the subject (which otherwise comes from the page title).

The password is read from a file, never passed as an argument — arguments show
up in shell history and in `ps` output for any other user on the machine. The
script warns if the file is group- or world-readable, strips the spaces Google
puts in the displayed password, and tells you plainly if Gmail rejects the login.

### If you see CERTIFICATE_VERIFY_FAILED

Python installed from python.org ships without a CA bundle until its
certificate step is run, so every TLS connection fails. The script falls back to
the bundle `certifi` provides and prints which one it used. To fix it for every
Python program, not just this one:

```bash
open "/Applications/Python 3.13/Install Certificates.command"
```

The page is self-contained with no scripts or external assets, so it renders in
an email body. Gmail clips messages over ~102 KB; the dashboard is about 30 KB,
and the script warns if a report grows past that.

## Roadmap

- **Scheduling** — pair with the `/loop` or `/schedule` skill to run the review
  every Sunday automatically.

## Testing

```bash
python3 tests/test_budget.py
```
