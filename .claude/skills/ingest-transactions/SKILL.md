---
name: ingest-transactions
description: Load bank transaction CSVs into the ledger, verifying account labels, date formats and debit/credit sign conventions before anything is stored. Use when the user has downloaded new statements, mentions new CSVs, drops files in data/inbox, or asks to import or refresh transactions.
---

# Ingest transactions

This is the routine the household runs every week or two: download exports, drop
them in `data/inbox/`, load them. Ingest is idempotent, so overlapping downloads
are safe.

## 1. Always dry-run first

```bash
python3 -m budget ingest --dry-run
```

With no paths it reads everything in `data/inbox/`. Check three things per file
before loading anything.

## 2. Set `--account` explicitly. Every time.

**Never rely on the filename-derived label.** Two things have already gone wrong
here on real data:

- Two accounts at one bank, a checking account and a card, both reduced to the
  bank's name alone because the filename heuristic stripped their last-four
  digits - merging two unrelated accounts into one.
- Two household members' Discover exports had **byte-identical filenames**
  with identical bank-generated names, so one would have
  overwritten the other's account.

The account label is part of each transaction's fingerprint. Changing it later
re-imports the whole file as new rows, so it has to be right the first time.
Use stable, readable labels tied to the real account, not the filename:

```bash
python3 -m budget ingest data/inbox/Bank1234_Activity_20260920.csv --account bank-checking
python3 -m budget ingest "data/inbox/Statement closed Sep 17, 2026.CSV" --account card-b
```

Check existing labels first so a re-download lands in the same account:

```bash
python3 -m budget status          # lists every account already in the ledger
```

## 3. Verify the sign convention

**Purchases must be negative, income positive.** Credit-card exports often list
charges as positive.

The parser remembers each layout. A format signature (its column set) is stored
with the resolved convention, so a later file from the same bank inherits it -
this is how a 3-row Discover export gets the right signs from a 7-row one. When
a file is too short to infer and has no precedent, it says so rather than
guessing, and that unconfident guess is **not** remembered.

Override with `--flip` (file lists spending as positive) or `--no-flip`. The
explicit flag always wins. **If you cannot tell, show the user two sample rows
and ask which one was money leaving the account.** Guessing here inverts a
household member's entire statement.

## 3b. Every upload must overlap the last one

Bank exports default to a short recent window - "last 7 days", "recent
activity". Downloading one a fortnight after the previous leaves a hole, and
**that hole is invisible afterwards: the missing days simply look like days
without spending.**

The dry run compares the file's first date against what is already stored for
that account and prints a `GAP` line when they do not meet:

```
! GAP: card-b is stored through 2026-09-07 but this file starts 2026-09-17
  9 day(s) in between will be missing for good. Re-export with an overlapping start date.
```

**Stop and ask for a re-export when this appears.** Do not ingest the file and
move on - the gap cannot be detected later, and re-importing an overlapping
range is free because duplicates are recognised and skipped.

Tell the household to always choose a start date at or before the last one they
downloaded. Overlap costs nothing; a gap is permanent.

## 4. Load and archive

```bash
python3 -m budget ingest --archive
```

`--archive` moves processed files to `data/archive/`, disambiguating names that
collide. Passing an explicit path still archives correctly.

Watch for `N repeated identical transaction(s) kept` - that is the parser
preserving genuinely repeated charges (two identical wire fees on one day, two
checks to the same payee) that would otherwise be swallowed as duplicates.

## 5. Categorize what is new

```bash
python3 -m budget recategorize     # re-applies rules to stored rows
python3 -m budget uncategorized --json
```

Run `recategorize` after any rule change; rules normally only run at ingest.

**Get merchant keys from the JSON. Never type them from memory** - they are
normalized forms (`brokerage svc llc moneyline dczp0 web id`), and a guessed key
silently updates 0 rows while reporting success.

```bash
python3 -m budget categorize Dining --merchant "<exact key from --json>" --subcategory Cafe --learn
```

`--learn` writes it to `config/rules.json` so the merchant never asks again.

**Ask the user, do not guess, when** the merchant is over ~$500 and the category
changes the picture, or when it could be a transfer between their own accounts.
Batch the questions into one message. On this household that surfaced a daycare,
a second car loan and an HVAC purchase that no amount of string-matching would
have resolved.

## 5b. Undoing a mislabelled ingest

The account label is part of every transaction's fingerprint, so a wrong one
cannot be corrected in place - the rows have to go and the file be re-read:

```bash
python3 -m budget remove-account wrong-label          # shows what it would delete
python3 -m budget remove-account wrong-label --yes    # actually deletes
python3 -m budget ingest "data/archive/<file>" --account right-label
```

It refuses to delete without `--yes` and leaves the source CSV in
`data/archive/`, so re-ingesting under the right name is one command. Do this as
soon as the mistake is spotted - it is cheap with a handful of rows and painful
once months of history share the wrong label.

## 6. Report back

Per file: account, rows, date range, new vs duplicate, uncategorized count, and
any `GAP` warning.

Then check nothing was forgotten: `python3 -m budget status` lists every account
in the ledger. If one of them has no new data this round, say so - an account
that stops being uploaded silently drains its spending out of every future
report.
Then hand off to **analyze-spending** if they asked for analysis.

## Watch for

- **Not every "PAYMENT" is a card payment.** ComEd, the gas company and the
  insurer all use the word. Card payments are matched per issuer; utility and
  insurance payments are real spending.
- **A missing card statement is invisible, not zero.** If checking autopays a
  card you have no export for, that spending simply does not exist in the
  ledger. Say so explicitly rather than letting totals look small.
