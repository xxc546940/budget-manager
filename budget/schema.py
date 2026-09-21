"""Canonical transaction schema and money handling.

Money is stored as integer cents everywhere. Floats never touch a balance.
Sign convention: outflow (spending) is NEGATIVE, inflow (income) is POSITIVE.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# Top-level categories. Subcategories are free-form strings.
CATEGORIES = [
    "Income",
    "Housing",
    "Utilities",
    "Groceries",
    "Dining",
    "Transport",
    "Health",
    "Insurance",
    "Childcare",
    "Shopping",
    "Entertainment",
    "Travel",
    "Education",
    "Debt",
    "Savings",
    "Retirement",
    "Transfer",
    "Fees",
    "Other",
]

# Categories excluded from "spending" totals: moving money between own accounts
# is not consumption, and counting it would double-count every paycheck sweep.
# Retirement is separate from Savings on purpose: a yearly IRA contribution is
# real money leaving, but it is not progress against a monthly savings rate, so
# counting it there would flatter the rate in one month and starve eleven.
NON_SPEND = {"Transfer", "Savings", "Income", "Retirement"}


def to_cents(value) -> int:
    """Parse a money-ish value into integer cents."""
    if value is None:
        raise ValueError("no amount")
    if isinstance(value, int):
        return value * 100
    if isinstance(value, Decimal):
        return int(value.quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)
    s = str(value).strip()
    if not s:
        raise ValueError("empty amount")
    negative = False
    # (123.45) is accounting notation for negative
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    if s.startswith("-"):
        negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    s = re.sub(r"[^\d.,]", "", s)  # strip $, USD, spaces, nbsp
    if not s:
        raise ValueError(f"unparseable amount: {value!r}")
    # Disambiguate 1.234,56 (EU) from 1,234.56 (US)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # A single comma with exactly 2 trailing digits is a decimal separator.
        if re.fullmatch(r"\d+,\d{2}", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    cents = int((Decimal(s) * 100).quantize(Decimal("1"), ROUND_HALF_UP))
    return -cents if negative else cents


def fmt(cents: int, sign: bool = False) -> str:
    """Format cents as a dollar string."""
    s = f"${abs(cents) / 100:,.2f}"
    if cents < 0:
        return f"-{s}" if not sign else f"-{s}"
    return f"+{s}" if sign else s


_NOISE = [
    (re.compile(r"\b(?:POS|ACH|DEBIT|CREDIT|PURCHASE|PAYMENT|RECURRING)\b", re.I), " "),
    (re.compile(r"\bX{2,}\d+\b|\b\d{4,}\b", re.I), " "),          # card/ref numbers
    (re.compile(r"#\s*\d+"), " "),                                  # store numbers
    (re.compile(r"\b\d{2}/\d{2}(?:/\d{2,4})?\b"), " "),            # embedded dates
    (re.compile(r"\b[A-Z]{2}\b(?=\s*$)"), " "),                    # trailing state code
    (re.compile(r"\b(?:SQ|TST|PY|PAYPAL|SP|IC)\s*\*", re.I), " "),  # processor prefixes
    (re.compile(r"[^A-Za-z0-9&'\- ]+"), " "),
]


def normalize_merchant(description: str) -> str:
    """Collapse a raw bank description into a stable merchant key.

    'SQ *BLUE BOTTLE COFFEE #1234 OAKLAND CA' -> 'blue bottle coffee'
    """
    s = description or ""
    for pattern, repl in _NOISE:
        s = pattern.sub(repl, s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


@dataclass
class Transaction:
    date: date                    # transaction date (not posted date)
    amount_cents: int             # negative = spend, positive = income
    description: str              # raw text from the bank
    account: str                  # e.g. "chase-sapphire"
    merchant: str = ""            # normalized key
    category: str = ""            # top-level, from CATEGORIES
    subcategory: str = ""
    category_source: str = ""     # "rule" | "agent" | "manual"
    posted_date: date | None = None
    source_file: str = ""
    note: str = ""
    seq: int = 0            # nth identical transaction on the same day
    id: str = field(default="")

    def __post_init__(self):
        if not self.merchant:
            self.merchant = normalize_merchant(self.description)
        if not self.id:
            self.id = self.fingerprint()

    def fingerprint(self) -> str:
        """Stable identity for dedupe across overlapping CSV exports.

        Deliberately excludes category and posted_date so re-importing an
        overlapping date range, or re-categorizing, never creates a duplicate.

        `seq` distinguishes genuinely repeated transactions: two $15 wire fees on
        one day, or two checks to the same payee whose numbers the merchant
        normalizer strips as noise. Without it the second one is silently
        swallowed as a duplicate. seq 0 hashes exactly as before, so identities
        already in the ledger are unchanged.
        """
        parts = [
            self.account.strip().lower(),
            self.date.isoformat(),
            str(self.amount_cents),
            normalize_merchant(self.description),
        ]
        if self.seq:
            parts.append(f"#{self.seq}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def is_spend(self) -> bool:
        return self.amount_cents < 0 and self.category not in NON_SPEND

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["posted_date"] = self.posted_date.isoformat() if self.posted_date else None
        return d
