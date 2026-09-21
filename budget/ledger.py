"""SQLite-backed transaction ledger with idempotent ingest.

Re-importing an overlapping date range is the normal case (you download
"last 90 days" every week), so insert is upsert-by-fingerprint and never
duplicates. Manual category edits survive re-ingest.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .schema import Transaction

# BUDGET_DB lets tests and demos run against a throwaway ledger.
DB_PATH = Path(os.environ.get(
    "BUDGET_DB", Path(__file__).resolve().parent.parent / "data" / "ledger.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id             TEXT PRIMARY KEY,
    date           TEXT NOT NULL,
    posted_date    TEXT,
    amount_cents   INTEGER NOT NULL,
    description    TEXT NOT NULL,
    merchant       TEXT NOT NULL,
    account        TEXT NOT NULL,
    category       TEXT DEFAULT '',
    subcategory    TEXT DEFAULT '',
    category_source TEXT DEFAULT '',
    note           TEXT DEFAULT '',
    source_file    TEXT DEFAULT '',
    ingested_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_txn_merchant ON transactions(merchant);

CREATE TABLE IF NOT EXISTS ingests (
    file        TEXT,
    account     TEXT,
    rows_seen   INTEGER,
    rows_new    INTEGER,
    detection   TEXT,
    ingested_at TEXT
);

-- How each bank's export layout was resolved, so a later file of the same
-- shape inherits it instead of re-guessing from too few rows.
CREATE TABLE IF NOT EXISTS formats (
    signature    TEXT PRIMARY KEY,
    sign_flipped INTEGER NOT NULL,
    example_file TEXT,
    confirmed_at TEXT
);
"""


def connect(db: Path = DB_PATH) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert(conn: sqlite3.Connection, txns: list[Transaction]) -> tuple[int, int]:
    """Insert transactions. Returns (new, duplicates_skipped)."""
    now = datetime.now().isoformat(timespec="seconds")
    new = 0
    for t in txns:
        cur = conn.execute(
            """INSERT INTO transactions
               (id, date, posted_date, amount_cents, description, merchant, account,
                category, subcategory, category_source, note, source_file, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO NOTHING""",
            (t.id, t.date.isoformat(),
             t.posted_date.isoformat() if t.posted_date else None,
             t.amount_cents, t.description, t.merchant, t.account,
             t.category, t.subcategory, t.category_source, t.note,
             t.source_file, now),
        )
        new += cur.rowcount
    conn.commit()
    return new, len(txns) - new


def sign_conventions(conn) -> dict:
    """Format signature -> whether that layout lists spending as positive."""
    return {r["signature"]: bool(r["sign_flipped"])
            for r in conn.execute("SELECT signature, sign_flipped FROM formats")}


def remember_format(conn, signature: str, sign_flipped: bool, file: str) -> None:
    """Record a resolved sign convention. Only confident results are stored."""
    if not signature:
        return
    conn.execute(
        """INSERT INTO formats (signature, sign_flipped, example_file, confirmed_at)
           VALUES (?,?,?,?)
           ON CONFLICT(signature) DO UPDATE SET
             sign_flipped=excluded.sign_flipped,
             example_file=excluded.example_file,
             confirmed_at=excluded.confirmed_at""",
        (signature, 1 if sign_flipped else 0, file,
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()


def record_ingest(conn, file: str, account: str, seen: int, new: int, detection: str) -> None:
    conn.execute(
        "INSERT INTO ingests (file, account, rows_seen, rows_new, detection, ingested_at) VALUES (?,?,?,?,?,?)",
        (file, account, seen, new, detection, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def _row_to_txn(r: sqlite3.Row) -> Transaction:
    return Transaction(
        id=r["id"],
        date=date.fromisoformat(r["date"]),
        posted_date=date.fromisoformat(r["posted_date"]) if r["posted_date"] else None,
        amount_cents=r["amount_cents"],
        description=r["description"],
        merchant=r["merchant"],
        account=r["account"],
        category=r["category"] or "",
        subcategory=r["subcategory"] or "",
        category_source=r["category_source"] or "",
        note=r["note"] or "",
        source_file=r["source_file"] or "",
    )


def fetch(conn, start: date | None = None, end: date | None = None,
          category: str | None = None, uncategorized: bool = False) -> list[Transaction]:
    sql = "SELECT * FROM transactions WHERE 1=1"
    args: list = []
    if start:
        sql += " AND date >= ?"; args.append(start.isoformat())
    if end:
        sql += " AND date <= ?"; args.append(end.isoformat())
    if category:
        sql += " AND category = ?"; args.append(category)
    if uncategorized:
        sql += " AND (category IS NULL OR category = '')"
    sql += " ORDER BY date DESC, amount_cents ASC"
    return [_row_to_txn(r) for r in conn.execute(sql, args)]


def set_category(conn, txn_id: str, category: str, subcategory: str = "",
                 source: str = "agent") -> int:
    cur = conn.execute(
        "UPDATE transactions SET category=?, subcategory=?, category_source=? WHERE id=?",
        (category, subcategory, source, txn_id),
    )
    conn.commit()
    return cur.rowcount


def set_category_by_merchant(conn, merchant: str, category: str, subcategory: str = "",
                             only_uncategorized: bool = True) -> int:
    sql = "UPDATE transactions SET category=?, subcategory=?, category_source='agent' WHERE merchant=?"
    if only_uncategorized:
        sql += " AND (category IS NULL OR category = '')"
    cur = conn.execute(sql, (category, subcategory, merchant))
    conn.commit()
    return cur.rowcount


def delete_account(conn, account: str) -> int:
    """Remove every transaction under one account label.

    For undoing a mislabelled ingest. The label is part of each transaction's
    identity, so a wrong one cannot be corrected in place - the rows have to go
    and the file be re-read under the right name.
    """
    cur = conn.execute("DELETE FROM transactions WHERE account = ?", (account,))
    conn.execute("DELETE FROM ingests WHERE account = ?", (account,))
    conn.commit()
    return cur.rowcount


def account_span(conn, account: str) -> tuple[date | None, date | None]:
    """First and last transaction date already stored for one account."""
    r = conn.execute("SELECT MIN(date) a, MAX(date) b FROM transactions WHERE account=?",
                     (account,)).fetchone()
    if not r or not r["a"]:
        return None, None
    return date.fromisoformat(r["a"]), date.fromisoformat(r["b"])


def span(conn) -> tuple[date | None, date | None]:
    r = conn.execute("SELECT MIN(date) a, MAX(date) b FROM transactions").fetchone()
    if not r or not r["a"]:
        return None, None
    return date.fromisoformat(r["a"]), date.fromisoformat(r["b"])


def stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"]
    uncat = conn.execute(
        "SELECT COUNT(*) c FROM transactions WHERE category IS NULL OR category=''"
    ).fetchone()["c"]
    accounts = [r["account"] for r in conn.execute(
        "SELECT DISTINCT account FROM transactions ORDER BY account")]
    a, b = span(conn)
    return {"transactions": total, "uncategorized": uncat, "accounts": accounts,
            "first_date": a.isoformat() if a else None,
            "last_date": b.isoformat() if b else None}
