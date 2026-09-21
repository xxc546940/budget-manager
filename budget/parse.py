"""Bank CSV parsing: sniff the schema, or use a pinned per-bank adapter.

Real bank exports disagree on everything: column names, date formats, whether
spending is negative or positive, and whether debits/credits live in one column
or two. This module detects all of that and reports what it inferred so a human
can confirm before the rows hit the ledger.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .schema import Transaction, to_cents

# Column-name candidates, matched case/space/punctuation-insensitively.
FIELD_ALIASES = {
    "date": [
        "transaction date", "trans date", "date", "post date", "posted date",
        "posting date", "activity date", "effective date", "booking date",
    ],
    "posted_date": ["post date", "posted date", "posting date", "settlement date"],
    # "merchant" first: exports that carry both give a cleaned merchant name
    # and a raw description full of store addresses and reference numbers.
    "description": [
        "merchant", "description", "payee", "name", "memo", "details",
        "transaction description", "original description", "reference",
    ],
    "amount": ["amount", "transaction amount", "amt", "value"],
    "debit": ["debit", "withdrawal", "withdrawals", "money out", "paid out", "charges"],
    "credit": ["credit", "deposit", "deposits", "money in", "paid in", "payments"],
    "type": ["type", "transaction type", "debit/credit", "dc", "cr/dr"],
    "category": ["category", "bank category"],
}

# Transaction-type values whose direction is unambiguous. "Payment" is absent
# on purpose: it means money INTO a credit card but OUT of a checking account,
# so trusting it would invert one of the two.
DEBIT_TYPES = {"debit", "dr", "withdrawal", "purchase", "sale", "charge"}
CREDIT_TYPES = {"credit", "cr", "deposit"}

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y",
    "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%m-%d-%Y", "%d-%b-%Y",
    "%Y%m%d", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (name or "").strip().lower()).strip()


class ParseError(Exception):
    pass


@dataclass
class Detection:
    """What the sniffer concluded about a file. Shown to the user at ingest."""
    account: str
    columns: dict
    signature: str          # canonical field -> actual header
    date_format: str
    amount_style: str      # "signed" | "debit_credit" | "type_column"
    sign_flipped: bool     # True when the file makes spending POSITIVE
    row_count: int
    date_range: tuple
    warnings: list
    sign_confident: bool = True

    def summary(self) -> str:
        lines = [
            f"  account:      {self.account}",
            f"  rows:         {self.row_count}  ({self.date_range[0]} .. {self.date_range[1]})",
            f"  date format:  {self.date_format}",
            f"  amount style: {self.amount_style}"
            + ("  [SIGN FLIPPED: file lists spending as positive]" if self.sign_flipped else ""),
            f"  columns:      " + ", ".join(f"{k}={v!r}" for k, v in self.columns.items()),
        ]
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


def _find_header(rows: list[list[str]]) -> int:
    """Locate the header row. Banks love prepending junk/disclaimer lines."""
    best, best_score = 0, -1
    for i, row in enumerate(rows[:20]):
        cells = [_norm(c) for c in row if c and c.strip()]
        if len(cells) < 2:
            continue
        score = 0
        for field, aliases in FIELD_ALIASES.items():
            if any(c in aliases for c in cells):
                score += 2
            elif any(any(a in c for a in aliases) for c in cells):
                score += 1
        if score > best_score:
            best, best_score = i, score
    if best_score < 2:
        raise ParseError(
            "could not find a header row with recognizable columns "
            "(need at least a date and an amount/description)"
        )
    return best


def _map_columns(header: list[str]) -> dict:
    """Map canonical field names to actual header strings.

    Aliases are tried in list order, not column order. Chase checking exports
    carry both a 'Details' column (just DEBIT/CREDIT) and a real 'Description';
    picking whichever appeared first in the file put DEBIT in every merchant
    field and left the whole statement uncategorized.
    """
    normalized = [(i, _norm(h)) for i, h in enumerate(header)]
    mapping = {}
    for field, aliases in FIELD_ALIASES.items():
        hit = None
        # Exact matches, best alias first.
        for alias in aliases:
            hit = next((i for i, h in normalized if h == alias), None)
            if hit is not None:
                break
        if hit is None:
            for alias in aliases:
                hit = next((i for i, h in normalized if h and alias in h), None)
                if hit is not None:
                    break
        if hit is not None and header[hit] not in mapping.values():
            mapping[field] = header[hit]
    # 'date' and 'posted_date' can collide on files with only one date column.
    if mapping.get("date") == mapping.get("posted_date"):
        mapping.pop("posted_date", None)
    return mapping


def _detect_date_format(samples: list[str]) -> str:
    """Pick the format that parses every sample. Prefers unambiguous ones."""
    candidates = []
    for fmt in DATE_FORMATS:
        try:
            parsed = [datetime.strptime(s.strip(), fmt) for s in samples if s and s.strip()]
        except (ValueError, TypeError):
            continue
        if parsed:
            candidates.append((fmt, parsed))
    if not candidates:
        raise ParseError(f"unrecognized date format, e.g. {samples[:3]}")
    # If both %m/%d and %d/%m parse, disambiguate by looking for a >12 day value.
    if len(candidates) > 1:
        for fmt, _ in candidates:
            if "%d/%m" in fmt and any(
                int(s.split("/")[0]) > 12 for s in samples
                if re.match(r"^\d{1,2}/\d{1,2}/", s.strip() or "x")
            ):
                return fmt
    return candidates[0][0]


def _parse_date(s: str, fmt: str) -> date:
    return datetime.strptime(s.strip(), fmt).date()


def format_signature(header: list[str]) -> str:
    """Identifies a bank's export layout, so its quirks can be remembered.

    Two files from the same bank have the same columns even when they are
    different accounts belonging to different people - which is what lets a
    three-row export inherit a sign convention proven on a longer one.
    """
    return "|".join(sorted(_norm(h) for h in header if h and h.strip()))


def sniff(path: Path, account: str | None = None, sign_flipped: bool | None = None,
          known_conventions: dict | None = None) -> tuple[Detection, list[Transaction]]:
    """Parse a bank CSV, inferring its schema. Returns (detection, transactions).

    `known_conventions` maps a format signature to a previously resolved
    sign_flipped value; it settles files too short to infer one on their own.
    """
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError(f"cannot decode {path.name}")

    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ParseError(f"{path.name} has no data rows")

    h = _find_header(rows)
    header = [c.strip() for c in rows[h]]
    cols = _map_columns(header)
    warnings = []

    if "date" not in cols:
        raise ParseError(f"no date column found in {header}")
    has_signed = "amount" in cols
    has_pair = "debit" in cols and "credit" in cols
    if not has_signed and not has_pair:
        raise ParseError(f"no amount column(s) found in {header}")
    if "description" not in cols:
        warnings.append("no description column; merchant matching will be weak")

    idx = {f: header.index(c) for f, c in cols.items()}
    data_rows = rows[h + 1:]

    def cell(row, field):
        i = idx.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    date_fmt = _detect_date_format([cell(r, "date") for r in data_rows[:40]])

    # --- Decide the sign convention -------------------------------------
    amount_style = "debit_credit" if has_pair else ("type_column" if "type" in cols and not has_signed else "signed")
    if has_pair:
        amount_style = "debit_credit"
    elif "type" in cols:
        types = {cell(r, "type").lower() for r in data_rows[:60]}
        if types & (DEBIT_TYPES | CREDIT_TYPES):
            amount_style = "type_column"

    signature = format_signature(header)
    auto_flip = False
    confident = True
    if amount_style == "signed":
        vals = []
        for r in data_rows:
            try:
                vals.append(to_cents(cell(r, "amount")))
            except (ValueError, KeyError):
                pass
        if not vals:
            raise ParseError("amount column present but no values parsed")
        negatives = sum(1 for v in vals if v < 0)
        positives = sum(1 for v in vals if v > 0)
        prior = (known_conventions or {}).get(signature)

        if prior is not None:
            # A file of the same shape has already been resolved; trust that
            # over a fresh guess. A three-row export cannot out-vote it.
            auto_flip = prior
            if positives and not negatives and not prior:
                warnings.append("every amount is positive but this format was previously "
                                "read as already-negative; check with --flip if wrong")
            else:
                warnings.append(
                    f"sign convention taken from a previous file of the same format "
                    f"({'spending positive' if prior else 'spending negative'})")
        elif positives > negatives * 2 and positives > 3:
            # A normal statement is mostly spending. If positives dominate, this
            # export uses the credit-card convention (charges positive).
            auto_flip = True
            warnings.append(
                f"{positives} positive vs {negatives} negative amounts -> inferred that "
                "this file lists spending as POSITIVE; flipping signs. "
                "Verify with --no-flip if wrong.")
        elif positives and not negatives:
            # Too few rows to be sure, and nothing to compare against.
            confident = False
            warnings.append(
                f"all {positives} amounts are positive but that is too few to infer the "
                "sign convention. If these are purchases, re-run with --flip.")
    flip = auto_flip if sign_flipped is None else sign_flipped

    acct = account or _account_from_filename(path)

    # --- Build transactions ---------------------------------------------
    txns, bad = [], 0
    for r in data_rows:
        try:
            d = _parse_date(cell(r, "date"), date_fmt)
            if amount_style == "debit_credit":
                deb, cred = cell(r, "debit"), cell(r, "credit")
                if deb:
                    cents = -abs(to_cents(deb))
                elif cred:
                    cents = abs(to_cents(cred))
                else:
                    continue  # zero-value row
            else:
                cents = to_cents(cell(r, "amount"))
                if amount_style == "type_column":
                    ttype = cell(r, "type").lower()
                    if ttype in DEBIT_TYPES:
                        cents = -abs(cents)
                    elif ttype in CREDIT_TYPES:
                        cents = abs(cents)
                    elif flip:
                        cents = -cents
                elif flip:
                    cents = -cents
            if cents == 0:
                continue
            posted = None
            if "posted_date" in cols and cell(r, "posted_date"):
                try:
                    posted = _parse_date(cell(r, "posted_date"), date_fmt)
                except ValueError:
                    pass
            txns.append(Transaction(
                date=d,
                amount_cents=cents,
                description=cell(r, "description") or cell(r, "category") or "(no description)",
                account=acct,
                posted_date=posted,
                source_file=path.name,
            ))
        except (ValueError, ParseError):
            bad += 1
    if bad:
        warnings.append(f"skipped {bad} unparseable row(s)")
    if not txns:
        raise ParseError(f"no usable rows parsed from {path.name}")

    # Number repeated identical transactions so none is lost to dedupe. Rows
    # that collide are identical in every hashed field, so their order cannot
    # change the set of ids produced - re-importing stays idempotent.
    counts: dict[str, int] = {}
    repeated = 0
    for t in txns:
        base = t.fingerprint()
        n = counts.get(base, 0)
        counts[base] = n + 1
        if n:
            t.seq = n
            t.id = t.fingerprint()
            repeated += 1
    if repeated:
        warnings.append(f"{repeated} repeated identical transaction(s) kept "
                        "(same day, amount and merchant)")

    dates = [t.date for t in txns]
    det = Detection(
        account=acct,
        columns=cols,
        signature=signature,
        date_format=date_fmt,
        amount_style=amount_style,
        sign_flipped=flip,
        row_count=len(txns),
        date_range=(min(dates).isoformat(), max(dates).isoformat()),
        warnings=warnings,
        sign_confident=confident,
    )
    return det, txns


# Words banks put in export filenames that say nothing about which account it is.
_FILENAME_NOISE = {
    "recentactivity", "recent", "activity", "transaction", "transactions",
    "export", "download", "statement", "history", "details", "data", "csv",
    "report", "account", "accounts", "all",
}
# A token that is a date fragment rather than part of an account name: a year,
# a packed YYYYMMDD, or a bare day/month number.
_DATE_TOKEN = re.compile(r"^(?:19|20)\d{2}$|^\d{8}$|^\d{1,2}$")


def _account_from_filename(path: Path) -> str:
    """Guess an account label, e.g. Bank1234_Activity_20260920.csv -> bank1234.

    The last four digits are the only thing distinguishing two accounts at the
    same bank, so they must survive - stripping every long digit run collapsed a
    checking account and a credit card into a single 'chase'.
    """
    tokens = [t for t in re.split(r"[_\-\s]+", path.stem.lower()) if t]
    kept = [t for t in tokens
            if t not in _FILENAME_NOISE and not _DATE_TOKEN.match(t)]
    label = "-".join(kept)
    # A label with no letters identifies nothing; make the caller name it.
    if not label or not re.search(r"[a-z]", label):
        return "unknown"
    return label
