# budget-manager

Household spending analysis. A pooled, multi-person household: every account
merges into one ledger, no per-person split.

## The division of labor

**Python computes. The agent judges.** This is the rule the whole design rests
on. Every total, variance, pace and projection comes from `budget/analyze.py`;
the agent reads that output and decides what it means. An agent that does
arithmetic in its head will disagree with the dashboard, and the user will not
know which to believe.

## Layout

```
budget/
  schema.py       Transaction, integer-cents money, merchant normalization
  parse.py        CSV schema sniffing + per-bank detection
  categorize.py   rule engine + learned merchant mappings
  ledger.py       SQLite store, idempotent upsert-by-fingerprint
  analyze.py      budget variance, savings pacing, anomalies, trends
  optimize.py     optimization candidates, gap closure, next week/month plans
  report_html.py  self-contained HTML dashboard
  recommend_html.py  the what-to-do-next page
  i18n.py         string table, money/date/period formatting per language
  cli.py          `python3 -m budget ...`
  ui.py/.html     local input UI on 127.0.0.1 (`python3 -m budget ui`)
config/
  income.json           net pay per source, effective-dated
  fixed_expenses.json   mortgage, car loan, daycare, utilities
  goals.json            savings goals, priority-ordered
  budget.json           discretionary envelopes + settings
  rules.json            seed + learned categorization rules
  *.example.json        tracked templates; the real files are gitignored
data/
  inbox/          drop bank CSVs here
  ledger.db       SQLite ledger (gitignored)
reports/          generated dashboards
.claude/
  skills/         the harness: ingest-transactions, analyze-spending, manage-budget
  agents/         budget-analyst
```

## The recurring routine

What the household actually does every week or two:

```bash
# 1. drop new exports into data/inbox/, then
python3 -m budget ingest --dry-run              # verify account, dates, signs
python3 -m budget ingest --account <label> --archive   # one call per file
python3 -m budget recategorize                  # apply rules to stored rows
python3 -m budget uncategorized --json          # resolve what is left, by merchant
python3 -m budget report --period week
python3 -m budget dashboard --period week
```

Raise `settings.analysis_start` only when a new card with no history joins.

## Conventions that matter

- **Money is integer cents everywhere.** Floats never touch a balance.
- **Sign convention: outflow negative, inflow positive**, always, regardless of
  what the bank's file did. `parse.py` normalizes this and reports what it
  inferred.
- **Transaction identity** is `sha256(account, date, amount, normalized
  merchant)`. It deliberately excludes category and posted date, so re-importing
  an overlapping range never duplicates and never loses a manual recategorization.
- **`Transfer`, `Savings`, `Retirement` and `Income` are not spending.**
  Counting a card payment as spending double-counts every purchase on that card.
  `Retirement` is separate from `Savings` on purpose: an IRA contribution is
  real money leaving but is not progress against a monthly savings rate.
- **`settings.analysis_start` scopes spending only.** Card exports cover a short
  window while checking goes back years; averaging across that boundary makes
  every total read low. Savings and income ignore the clamp because they come
  from checking, which is complete. All spending reads go through
  `analyze.window()` so the setting cannot be honoured in one place and
  forgotten in another.
- **Below ~28 days of history the optimizer must say so**, not report zeros.
  `gap.sufficient_history` gates `cut_depth_needed`; concluding "no amount of
  restraint closes it" from an empty baseline is a confident claim built on
  missing data.
- **Account labels are identity.** Two accounts at one bank differ only by their
  last four digits, and two people's exports can share a filename byte for byte.
  Always ingest with an explicit `--account`.
- **Sign conventions are remembered per format signature.** A short export
  inherits the convention proven on a longer one of the same layout; an
  unconfident guess is never stored as precedent.
- **Merchant keys are normalized strings.** Read them from
  `uncategorized --json`; a typed approximation updates 0 rows and still
  reports success.
- **Rule priority beats rule length.** A named destination (`vanguard`) must win
  over a generic verb (`transfer to`), or savings contributions get filed as
  internal transfers and savings tracking silently reads zero.
- **Declared fixed expenses are never added to spending.** They already arrive
  in the checking CSV; declaring them is for verification and commitment math.
  Adding them would double-count the mortgage every month.
- **Income and fixed expenses are effective-dated.** Re-running an old month
  must use that month's pay, so config changes close the old entry rather than
  overwrite it.
- **The data layer emits no prose.** `analyze.py` and `optimize.py` produce
  numbers plus a `facts` dict; the renderer composes every sentence through
  `i18n.Translator`. English titles on candidates exist only for the CLI and the
  agent - a renderer that formatted them into a page would leak English into a
  translated one.
- **Language and currency are independent settings.** A zh-Hans page with USD
  amounts is normal; never infer one from the other.
- **Optimization savings must never double count.** Subscriptions are extracted
  before category targets are computed on the variable remainder, and a habit
  inside a category already being cut is dropped. `next_month`'s envelope cuts
  must reconcile exactly with `gap.identified_cents` - there is a test for it.
- **A weekly allowance is pace-aware.** 80% of an envelope spent is fine on the
  25th and alarming on the 8th, so status compares spend against elapsed days,
  not against an absolute threshold.
- **When the gap cannot be closed, say so.** `cut_depth_needed.achievable` false
  means no amount of discretionary restraint reaches the goal. Assembling a list
  of small cuts to look responsive is the failure mode to avoid.
- **Goals claim contributions in priority order.** A goal with `account_match`
  takes only its own; an unmatched goal takes the remainder. Without this, two
  goals both count the same transfer.
- **Income must be derived, then confirmed - never assumed.**
  `python3 -m budget income-audit` (`analyze.income_audit()`) groups deposits by employer, reads the cadence from
  the gaps, excludes one-offs and former employers, and gives the implied
  monthly figure. Biweekly (26/yr) and semimonthly (24/yr) differ by 8% and look
  alike; misreading one overstated an earner by $445/month here. Always show the
  derivation and ask before writing it to `income.json`.
- **Income is a configured figure, not a tracked one.** The ceiling is derived
  from `income.json`, so the number must be right, but observed deposits are not
  a weekly metric. `analyze.income_check()` compares the two in the background
  over the trailing 3 months and adds a config warning only when they diverge by
  more than 10%. It compares household *totals*, so it cannot see a per-person
  error whose halves cancel - that is what `income_audit()` is for. Three months on purpose: over a longer window a job change
  makes an accurate figure look wrong.
- **All income is net (after tax).** `monthly_income()` skips any source whose
  `basis` is not `"net"`. Percentage-based goal contributions are of net, so a
  gross figure would commit money that never arrives.
- **The dashboard opens with "Needs doing".** `config/reminders.json` holds what
  the household asked to remember (`budget remind`); `analyze.spending_actions()`
  derives the rest from this month's budget and names the merchant driving each
  breach. Generated actions are never stored.
- **Track calendar months, 1st to end.** `month` is the default period for
  `report` and `dashboard`. Envelopes and commitments are monthly, so a week or
  a rolling window compares against something the household never set.
- **Missing data must be named, not inferred as zero.** `analyze.coverage()`
  lists every account with its newest transaction; `stale` means the latest
  statement is probably not uploaded, `absent` means nothing at all in the
  period. Both surface in the dashboard's "Needs attention".
- **Uploads must overlap.** `cli._coverage_gap()` compares a file's first date
  against what is stored for that account and warns at ingest, because a gap is
  undetectable afterwards - the missing days look like days without spending.
  Duplicates are free; gaps are permanent.
- **The headline is the calendar month, not the report period.** The budget is
  monthly, so `month_to_date` scopes the KPI row and the free-to-spend item list
  to the month regardless of what period was asked for. Both must quote the same
  allowance - two different ones on a page is how a report loses trust.
- **`pct_month_observed` guards the percentage.** A window starting mid-month
  makes the spend figure a floor, so "50% of budget used" is reported alongside
  "40% of the month observed" and flagged when it runs ahead of that.
- **The dashboard leads with the decidable money.** Commitments are already
  spoken for, so the KPI row tracks the free-to-spend allowance, what was spent
  of it, and how much of the period's savings target the overspend consumed -
  not total spending, which the household cannot move.
- **`monthly_history` shows complete months only.** A month counts when the
  analysis window covers all of it and it has ended. A partial month beside
  whole ones reads as a fall in spending that never happened, so it is excluded
  rather than shown with a caveat; the empty state names when the first whole
  month will arrive.
- **`commitment_tracker` is the standing view**, distinct from
  `verify_commitments` (occurrences inside a reporting period). It always lists
  every declared commitment with last payment and next due, reading full
  history, so one quietly ceasing to be paid is visible.
- **Savings is a residual, not a transaction** (`settings.savings_model`,
  default `"residual"`). Most households never transfer money to savings; what
  is not spent stays put, so measuring from `Savings`-category rows reports 0%
  forever. The goal restates as a **spending ceiling**: income minus the target
  is the most that can be spent without eating into it. `"transactions"` keeps
  the old behaviour for households that really do sweep money across.
- **With several rate goals the single residual is apportioned** by each goal's
  share of the total target, so it is never counted twice.
- **Goals come in two kinds.** `goal_type` is `"rate"` (save a share of income
  every month; no target amount or date, success is behavioral) or `"target"`
  (a sum by a date). `config.goal_type()` infers it from the shape when absent,
  so older goals keep working. A rate goal must never be given a projected
  completion date - it has no finish line.
- **The gap is measured against observed savings, not planned.** For a rate goal
  planned == required, so `required - planned` is always zero and a household
  that saved nothing would be reported on track.
- **required / planned / observed are three different numbers.** Required is
  what the target and date demand; planned is `contribution_type` (`percent` of
  net income, `fixed`, or `auto`); observed is what the ledger saw. Cashflow's
  `free_cents` subtracts *planned* — that is what leaves the account — while
  `plan_shortfall_cents` reports whether the plan can reach the goal at all.
  Collapsing them hides a household that follows its plan and still misses.

## No dependencies

Standard library only — `sqlite3`, `csv`, `decimal`, `statistics`. It runs on a
bare `python3` with no install step. Keep it that way; this thing has to still
run in two years with no maintenance.

## Testing

```bash
python3 tests/test_budget.py        # no pytest needed
```

Point `BUDGET_DB`, `BUDGET_CONFIG_DIR`, `BUDGET_RULES`, `BUDGET_DATA_DIR` and
`BUDGET_REPORTS_DIR` at temp paths to work against a throwaway ledger.

## Reports and email

`dashboard` and `recommend --html` write to `reports/latest-<kind>.html`, moving
any previous copy into `reports/archive/`. The fixed filename is what lets
`scripts/send_report.py` always pick up the current report without guessing.
`--out` still writes wherever you point it and skips archiving.

TLS: a python.org install has no CA bundle until "Install Certificates.command"
has been run, so `ssl.create_default_context()` alone fails with
CERTIFICATE_VERIFY_FAILED. `ssl_context()` checks the default verify paths and
falls back to certifi, and the error handler names both fixes rather than
surfacing a raw SSL error.

The mailer is run by the user, never automatically. The Gmail app password is
read from a file path given with `--password-file`; never accept it as an
argument or store it in config, because arguments are visible in shell history
and in `ps`.

## Privacy

Transaction data is private and stays local. Never send it to a web search, an
external API, or any tool outside this repo.

`.gitignore` excludes every file that holds real figures: `config/*.json` (bar
the `.example.json` templates), all of `data/`, and `reports/`. Before adding a
new file that holds personal data, add it there first. The UI binds to
127.0.0.1 only and requires a per-session token for writes.
