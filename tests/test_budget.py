"""Regression tests for the parts that silently corrupt every report if wrong.

Run: python3 -m pytest tests/ -q     (or: python3 tests/test_budget.py)
"""

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from budget import analyze, categorize, ledger, report_html                      # noqa: E402
from budget.parse import sniff                                      # noqa: E402
from budget.schema import Transaction, fmt, normalize_merchant, to_cents  # noqa: E402


# ------------------------------------------------------------------ money

def test_money_parsing():
    assert to_cents("$1,234.56") == 123456
    assert to_cents("(45.00)") == -4500        # accounting negative
    assert to_cents("-12.3") == -1230
    assert to_cents("1.234,56") == 123456      # EU thousands + decimal comma
    assert to_cents("89,50") == 8950           # EU decimal comma
    assert to_cents("$0.99") == 99
    assert to_cents("+900") == 90000


def test_rounding_is_exact():
    # Floats would drift here; integer cents must not.
    assert sum(to_cents("0.10") for _ in range(10)) == 100
    assert to_cents("2.675") == 268            # half-up, not banker's


# ------------------------------------------------------------------ parsing

def _write(tmp, name, text):
    p = Path(tmp) / name
    p.write_text(text)
    return p


def test_parses_signed_with_junk_preamble():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "boa.csv",
                   "Bank export\nDescription,,Summary Amt.\n"
                   "Beginning balance,,\"4,120.55\"\n\n"
                   "Date,Description,Amount,Running Bal.\n"
                   "09/02/2026,SAFEWAY #1234,\"-88.42\",\"4,032.13\"\n"
                   "09/03/2026,PAYROLL DIRECT DEP,\"3,250.00\",\"7,282.13\"\n")
        det, txns = sniff(p)
        assert det.date_format == "%m/%d/%Y"
        assert [t.amount_cents for t in txns] == [-8842, 325000]


def test_parses_debit_credit_pair_with_ddmm_dates():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "amex.csv",
                   "Date,Description,Debit,Credit\n"
                   "15/09/2026,UBER TRIP,24.60,\n"
                   "17/09/2026,PAYMENT THANK YOU,,500.00\n")
        det, txns = sniff(p)
        assert det.amount_style == "debit_credit"
        assert txns[0].amount_cents == -2460     # debit is always outflow
        assert txns[1].amount_cents == 50000     # credit is always inflow


def test_parses_semicolons_and_eu_decimals():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "cu.txt",
                   '"Posting Date";"Details";"Transaction Amount"\n'
                   '"2026-09-10";"WHOLE FOODS";"210,45"\n')
        _, txns = sniff(p)
        assert txns[0].amount_cents in (21045, -21045)


def test_sign_flip_inferred_for_credit_card_convention():
    # A card export where charges are positive must be flipped to negative.
    rows = "\n".join(f"09/{d:02d}/2026,MERCHANT {d},{d * 3}.00" for d in range(1, 20))
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "card.csv", "Date,Description,Amount\n" + rows + "\n")
        det, txns = sniff(p)
        assert det.sign_flipped is True
        assert all(t.amount_cents < 0 for t in txns)


# ------------------------------------------------------------------ identity

def test_short_file_inherits_sign_convention_from_same_format():
    # The real failure: two Discover exports, same columns, different people.
    # The 7-row one was flipped, the 3-row one was not, so one household
    # member's purchases were recorded as income.
    from budget.parse import format_signature
    header = "Trans. Date,Post Date,Description,Amount,Category\n"
    long_rows = "".join(f"09/{d:02d}/2026,09/{d:02d}/2026,MERCHANT {d},{d*7}.00,Restaurants\n"
                        for d in range(1, 12))
    short_rows = ("09/07/2026,09/07/2026,TARGET PLUS,214.99,Merchandise\n"
                  "09/07/2026,09/07/2026,TARGET.COM,96.75,Merchandise\n")
    with tempfile.TemporaryDirectory() as tmp:
        big = _write(tmp, "disc_a.csv", header + long_rows)
        small = _write(tmp, "disc_b.csv", header + short_rows)

        det_big, txns_big = sniff(big, account="disc-a")
        assert det_big.sign_flipped is True and det_big.sign_confident
        assert all(t.amount_cents < 0 for t in txns_big)

        # On its own the short file cannot tell, and must say so.
        det_alone, txns_alone = sniff(small, account="disc-b")
        assert det_alone.sign_confident is False
        assert any("too few" in w for w in det_alone.warnings)

        # Given the convention from the same format, it gets it right.
        known = {det_big.signature: det_big.sign_flipped}
        det, txns = sniff(small, account="disc-b", known_conventions=known)
        assert det.sign_flipped is True
        assert all(t.amount_cents < 0 for t in txns)
        # Same layout, different account -> same signature.
        assert format_signature(header.strip().split(",")) == det.signature


def test_unconfident_sign_detection_is_not_remembered():
    # An unsettled guess must never become the precedent for later files.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BUDGET_DB"] = str(Path(tmp) / "t.db")
        conn = ledger.connect(Path(tmp) / "t.db")
        p = _write(tmp, "tiny.csv",
                   "Date,Description,Amount\n09/07/2026,TARGET,214.99\n")
        det, _ = sniff(p, account="x")
        assert det.sign_confident is False
        if det.sign_confident:
            ledger.remember_format(conn, det.signature, det.sign_flipped, p.name)
        assert ledger.sign_conventions(conn) == {}


def test_explicit_flip_overrides_a_remembered_convention():
    header = "Date,Description,Amount\n"
    rows = "".join(f"09/{d:02d}/2026,M{d},{d*5}.00\n" for d in range(1, 10))
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "c.csv", header + rows)
        det, _ = sniff(p, account="x")
        known = {det.signature: det.sign_flipped}
        # The user's explicit flag always wins over both memory and heuristic.
        _, txns = sniff(p, account="x", sign_flipped=False, known_conventions=known)
        assert all(t.amount_cents > 0 for t in txns)


def test_archiving_never_overwrites_a_same_named_export():
    # Banks reuse filenames: two household members both download
    # "Card-RecentActivity-20260920.csv". A plain move destroys the first.
    import budget.cli as cli
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "archive"
        archive.mkdir()
        original = cli.ARCHIVE
        try:
            cli.ARCHIVE = archive
            name = "Card-RecentActivity-20260920.csv"
            (archive / name).write_text("first")
            dest = cli._archive_name(Path(tmp) / name, "card-b")
            assert dest != archive / name
            dest.write_text("second")
            assert (archive / name).read_text() == "first"
            # A third file with the same name and account still gets its own slot.
            third = cli._archive_name(Path(tmp) / name, "card-b")
            assert third != dest and not third.exists()
        finally:
            cli.ARCHIVE = original


def test_fingerprint_is_stable_across_reimport():
    a = Transaction(date(2026, 9, 1), -1000, "SQ *CAFE #123 OAKLAND CA", "visa")
    b = Transaction(date(2026, 9, 1), -1000, "SQ *CAFE #999 OAKLAND CA", "visa")
    assert a.id == b.id          # store number is noise, not identity
    c = Transaction(date(2026, 9, 1), -1000, "SQ *CAFE #123 OAKLAND CA", "amex")
    assert a.id != c.id          # different account is a different transaction


def test_repeated_identical_transactions_are_all_kept():
    # Real case: two $15 wire fees on one day, and two checks to the same payee
    # whose check numbers the merchant normalizer strips as noise. Without an
    # occurrence index the second of each is silently swallowed as a duplicate.
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "chk.csv",
                   "Details,Posting Date,Description,Amount\n"
                   "DEBIT,04/03/2026,DOMESTIC INCOMING WIRE FEE,-15.00\n"
                   "DEBIT,04/03/2026,DOMESTIC INCOMING WIRE FEE,-15.00\n"
                   "DEBIT,11/24/2025,CHECK # 6924 PASSPORTSERVICES PAYMENT,-100.00\n"
                   "DEBIT,11/24/2025,CHECK # 6922 PASSPORTSERVICES PAYMENT,-100.00\n")
        _, txns = sniff(p, account="chk")
        assert len(txns) == 4
        assert len({t.id for t in txns}) == 4
        # Re-parsing must produce the same identities, or re-import duplicates.
        _, again = sniff(p, account="chk")
        assert {t.id for t in txns} == {t.id for t in again}


def test_sequence_zero_keeps_the_original_fingerprint():
    # seq 0 must hash exactly as before, so transactions already stored keep
    # their ids and a re-ingest does not duplicate the whole ledger.
    a = Transaction(date(2026, 9, 1), -1500, "WIRE FEE", "chk")
    b = Transaction(date(2026, 9, 1), -1500, "WIRE FEE", "chk", seq=0)
    c = Transaction(date(2026, 9, 1), -1500, "WIRE FEE", "chk", seq=1)
    assert a.id == b.id
    assert c.id != a.id


def test_column_mapping_prefers_the_better_alias_not_the_first_column():
    # Chase checking exports carry a 'Details' column holding only DEBIT/CREDIT
    # plus a real 'Description'. Picking the earlier column put DEBIT in every
    # merchant field and left the entire statement uncategorized.
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "chase.csv",
                   "Details,Posting Date,Description,Amount,Type,Balance\n"
                   "CREDIT,09/18/2026,NORTHWIND PAYROLL,3005.97,ACH_CREDIT,4677.91\n")
        det, txns = sniff(p, account="chk")
        assert det.columns["description"] == "Description"
        assert "payroll" in txns[0].merchant


def test_account_label_keeps_the_account_number():
    # Two accounts at one bank differ only by their last four digits; stripping
    # every long number collapsed a checking account and a card into one label.
    from budget.parse import _account_from_filename as acct
    assert acct(Path("Bank1234_Activity_20260920.csv")) == "bank1234"
    assert acct(Path("Bank5678_Activity_20260920.csv")) == "bank5678"
    assert acct(Path("Card-RecentActivity-20260920.csv")) == "card"
    # A name with no letters left identifies nothing - make the caller name it.
    assert acct(Path("2026-09-20_transaction_download.csv")) == "unknown"


def test_merchant_normalization():
    assert normalize_merchant("SQ *BLUE BOTTLE #1234 OAKLAND CA").startswith("blue bottle")
    assert "trader joes" in normalize_merchant("POS DEBIT TRADER JOES 0456 XXXX1234")


# ------------------------------------------------------------------ rules

def test_named_destination_beats_generic_verb():
    # The bug this guards: "transfer to" is longer than "vanguard", so a naive
    # longest-match files a savings contribution as an internal transfer and
    # savings tracking silently reads zero.
    rules = categorize.default_rules()
    t = Transaction(date(2026, 9, 1), -140000, "TRANSFER TO VANGUARD BROKERAGE", "chk")
    categorize.categorize(t, rules)
    assert t.category == "Savings"


def test_longer_match_wins_at_equal_priority():
    rules = categorize.default_rules()
    t = Transaction(date(2026, 9, 1), -2300, "UBER EATS HELP.UBER.COM", "visa")
    categorize.categorize(t, rules)
    assert (t.category, t.subcategory) == ("Dining", "Delivery")


def test_unmatched_stays_blank_for_the_agent():
    rules = categorize.default_rules()
    t = Transaction(date(2026, 9, 1), -5000, "ZZZQQ UNKNOWN VENDOR", "visa")
    categorize.categorize(t, rules)
    assert t.category == ""


# ------------------------------------------------------------------ ledger

def _seeded_db(tmp):
    os.environ["BUDGET_DB"] = str(Path(tmp) / "t.db")
    conn = ledger.connect(Path(tmp) / "t.db")
    return conn


def test_reingest_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        txns = [Transaction(date(2026, 9, 1), -1000, "CAFE", "visa")]
        assert ledger.insert(conn, txns) == (1, 0)
        assert ledger.insert(conn, txns) == (0, 1)   # no duplicate


def test_manual_category_survives_reingest():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        t = Transaction(date(2026, 9, 1), -1000, "CAFE", "visa")
        ledger.insert(conn, [t])
        ledger.set_category(conn, t.id, "Dining", "Coffee")
        ledger.insert(conn, [Transaction(date(2026, 9, 1), -1000, "CAFE", "visa")])
        assert ledger.fetch(conn)[0].category == "Dining"


# ------------------------------------------------------------------ analysis

def test_transfers_and_savings_excluded_from_spend():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 1), -5000, "GROCERY", "visa", category="Groceries"),
            Transaction(date(2026, 9, 1), -100000, "CARD PAYMENT", "chk", category="Transfer"),
            Transaction(date(2026, 9, 1), -140000, "VANGUARD", "chk", category="Savings"),
            Transaction(date(2026, 9, 1), 400000, "PAYROLL", "chk", category="Income"),
        ])
        rows = ledger.fetch(conn)
        assert sum(abs(t.amount_cents) for t in analyze.spend_only(rows)) == 5000
        assert sum(abs(t.amount_cents) for t in analyze.savings_only(rows)) == 140000


def _cfg(envelopes=None, goals=(), fixed=(), income=(), savings_model="transactions"):
    """A config in the assembled shape config.load() returns.

    Tests default to the transactions model so each one states which measure it
    is exercising; the application default is "residual".
    """
    return {
        "household": {"name": "T"},
        "settings": {"exclude_accounts": [], "large_transaction_cents": 20000,
                     "savings_model": savings_model},
        "budget": {"period": "monthly", "envelopes_cents": envelopes or {}},
        "income": {"sources": list(income)},
        "fixed": {"expenses": list(fixed)},
        "goals": {"goals": list(goals)},
    }


def test_updating_an_income_source_applies_cadence_and_keeps_it_otherwise():
    # An update that silently ignores --cadence leaves a wrong label nobody
    # notices; one that overwrites it when the flag is absent is just as bad.
    # argparse cannot tell "not given" from "given the default", so the default
    # is None and resolved at use.
    import budget.cli as cli
    import budget.config as cfgmod
    with tempfile.TemporaryDirectory() as tmp:
        # CONFIG_DIR is resolved at import time, so the env var is too late.
        original = cfgmod.CONFIG_DIR
        cfgmod.CONFIG_DIR = Path(tmp)
        try:
            cli.main(["set-income", "5000", "--name", "pay", "--cadence", "biweekly"])
            src = cfgmod.read("income")["sources"][0]
            assert src["cadence"] == "biweekly" and src["net_monthly_cents"] == 500000

            cli.main(["set-income", "6000", "--name", "pay", "--cadence", "semimonthly"])
            src = cfgmod.read("income")["sources"][0]
            assert src["cadence"] == "semimonthly" and src["net_monthly_cents"] == 600000

            # No --cadence: the amount changes, the label does not.
            cli.main(["set-income", "7000", "--name", "pay"])
            src = cfgmod.read("income")["sources"][0]
            assert src["cadence"] == "semimonthly" and src["net_monthly_cents"] == 700000
            assert src["basis"] == "net"
        finally:
            cfgmod.CONFIG_DIR = original


def test_config_writes_are_blocked_during_tests():
    # This guard exists because a test once wrote a $5,000 phantom salary into
    # the real income.json, silently inflating the household's income.
    import budget.config as cfgmod
    original = cfgmod.CONFIG_DIR
    try:
        cfgmod.CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
        try:
            cfgmod.write("income", {"sources": []})
            assert False, "write to the real config was not blocked"
        except RuntimeError as exc:
            assert "refusing to write real config" in str(exc)
        # A temp directory is fine.
        with tempfile.TemporaryDirectory() as tmp:
            cfgmod.CONFIG_DIR = Path(tmp)
            cfgmod.write("income", {"sources": []})
            assert cfgmod.read("income")["sources"] == []
    finally:
        cfgmod.CONFIG_DIR = original


def test_non_deposited_income_counts_but_is_not_compared_to_deposits():
    # A pre-tax dependent-care FSA is real spendable money that never appears as
    # a payroll deposit. Counting it in the deposit comparison would report a
    # permanent shortfall that no re-export could ever fix.
    import budget.config as cfgmod
    from budget import analyze as A
    cfg = _cfg(income=[
        {"name": "salary", "net_monthly_cents": 800000},
        {"name": "fsa", "net_monthly_cents": 41667, "in_deposits": False}])
    assert cfgmod.monthly_income(cfg) == 841667          # spendable total
    assert sum(s["net_monthly_cents"] for s in cfgmod.deposit_sources(cfg, date(2026, 9, 21))) == 800000

    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # One employer, so the deposits form a single stream the audit can read.
        for m in (5, 6, 7, 8, 9):
            for d in (1, 15):
                ledger.insert(conn, [Transaction(date(2026, m, d), 400000, "ACME PAYROLL",
                                                 "chk", category="Income")])
        chk = A.income_check(conn, cfg, date(2026, 9, 21))
        assert chk["ok"] is True          # deposits match the deposit half exactly
        a = A.income_audit(conn, cfg, date(2026, 9, 21))
        assert a["agrees"] is True
        assert a["non_deposit_monthly_cents"] == 41667
        assert a["total_monthly_cents"] == 841667


def test_audit_separates_biweekly_from_semimonthly():
    # The error that cost $445/month: 26 payslips a year vs 24 is 8% more money,
    # and both land "roughly twice a month". Flat 14-day gaps are biweekly;
    # gaps that wander with month length are semimonthly.
    from budget.analyze import _cadence_from_gaps
    assert _cadence_from_gaps([14, 14, 14, 14])[0] == "biweekly"
    assert _cadence_from_gaps([14, 17, 15, 14, 16])[0] == "semimonthly"
    assert _cadence_from_gaps([15, 16, 15, 15])[0] == "semimonthly"
    assert _cadence_from_gaps([7, 7, 7])[0] == "weekly"
    assert _cadence_from_gaps([30, 31, 30])[0] == "monthly"


def test_audit_derives_monthly_pay_from_real_deposits():
    from budget import analyze as A
    cfg = _cfg(income=[{"name": "guess", "net_monthly_cents": 900000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        rows = []
        # Biweekly: every 14 days.
        d = date(2026, 3, 20)
        while d <= date(2026, 9, 18):
            rows.append(Transaction(d, 300597, "ACME PAYROLL", "chk", category="Income"))
            d += timedelta(days=14)
        # Semimonthly: the 15th and the last day.
        for m in range(4, 10):
            rows.append(Transaction(date(2026, m, 15), 387766, "OTHERCO PAYROLL",
                                    "chk2", category="Income"))
            last = (date(2026, m, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            rows.append(Transaction(last, 387766, "OTHERCO PAYROLL", "chk2", category="Income"))
        ledger.insert(conn, rows)

        a = A.income_audit(conn, cfg, date(2026, 9, 18))
        by = {r["employer"].split()[0]: r for r in a["streams"]}
        assert by["acme"]["cadence"] == "biweekly"
        assert by["acme"]["periods_per_year"] == 26
        assert by["acme"]["implied_monthly_cents"] == round(300597 * 26 / 12)
        assert by["otherco"]["cadence"] == "semimonthly"
        assert by["otherco"]["periods_per_year"] == 24
        assert by["otherco"]["implied_monthly_cents"] == round(387766 * 24 / 12)
        # The configured guess is contradicted, and by how much.
        assert a["agrees"] is False
        assert a["difference_cents"] == 900000 - a["implied_monthly_cents"]


def test_audit_excludes_signing_bonuses_and_former_employers():
    from budget import analyze as A
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 651294}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        rows = [Transaction(date(2026, 3, 20), 2151837, "NEWCO PAYROLL", "chk",
                            category="Income")]          # signing bonus
        d = date(2026, 4, 3)
        while d <= date(2026, 9, 18):
            rows.append(Transaction(d, 300597, "NEWCO PAYROLL", "chk", category="Income"))
            d += timedelta(days=14)
        # A job that ended in January.
        for m in (10, 11, 12):
            rows.append(Transaction(date(2025, m, 15), 500000, "OLDCO PAYROLL",
                                    "chk", category="Income"))
        ledger.insert(conn, rows)

        a = A.income_audit(conn, cfg, date(2026, 9, 18))
        new = next(r for r in a["streams"] if r["employer"].startswith("newco"))
        old = next(r for r in a["streams"] if r["employer"].startswith("oldco"))
        assert new["active"] is True and old["active"] is False
        assert len(new["one_offs"]) == 1                  # the bonus, set aside
        assert new["typical_cents"] == 300597             # not dragged upward
        # Only active streams count toward the implied figure.
        assert a["implied_monthly_cents"] == new["implied_monthly_cents"]
        assert a["agrees"] is True


def test_income_check_stays_quiet_when_the_figure_is_right():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8, 9):
            ledger.insert(conn, [Transaction(date(2026, m, 1), 1000000, f"PAYROLL{m}",
                                             "chk", category="Income")])
        chk = analyze.income_check(conn, cfg, date(2026, 9, 18))
        assert chk["ok"] is True
        rep = analyze.build_report(conn, cfg, "month", date(2026, 9, 18))
        assert not [w for w in rep["config_warnings"] if "Configured income" in w]


def test_income_check_flags_a_stale_figure():
    # The ceiling is derived from configured income, so a wrong figure moves it.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8, 9):
            ledger.insert(conn, [Transaction(date(2026, m, 1), 1400000, f"PAYROLL{m}",
                                             "chk", category="Income")])
        chk = analyze.income_check(conn, cfg, date(2026, 9, 18))
        assert chk["ok"] is False
        assert chk["drift_pct"] > 10
        rep = analyze.build_report(conn, cfg, "month", date(2026, 9, 18))
        assert any("Configured income" in w for w in rep["config_warnings"])


def test_income_check_needs_evidence_before_speaking():
    # One deposit is not a basis for contradicting the configured figure.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 1), 100, "PAYROLL",
                                         "chk", category="Income")])
        assert analyze.income_check(conn, cfg, date(2026, 9, 18)) is None


def test_income_check_uses_a_window_short_enough_to_survive_a_job_change():
    # Over 12 months an accurate figure looks wrong once employers change; the
    # check deliberately looks at the trailing 3.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (1, 2, 3):            # old, much larger employer
            ledger.insert(conn, [Transaction(date(2026, m, 1), 2500000, f"OLD{m}",
                                             "chk", category="Income")])
        for m in (7, 8, 9):            # current employer, matches config
            ledger.insert(conn, [Transaction(date(2026, m, 1), 1000000, f"NEW{m}",
                                             "chk", category="Income")])
        assert analyze.income_check(conn, cfg, date(2026, 9, 18))["ok"] is True


def test_overspending_the_free_allowance_eats_the_savings_target():
    # The top of the dashboard tracks the decidable money, so the figures behind
    # it must reconcile: overspend comes straight out of the period's target.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               fixed=[{"id": "r", "name": "Rent", "category": "Housing",
                       "amount_cents": 400000, "cadence": "monthly", "due_day": 1,
                       "match": "rent", "effective_from": "2026-01-01"}],
               goals=[{"id": "g", "name": "Overall", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}],
               savings_model="residual")
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # free = 10,000 - 4,000 rent - 1,000 target = 5,000/mo
        ledger.insert(conn, [Transaction(date(2026, 8, 10), -600000, "SHOP",
                                         "visa", category="Shopping")])
        cf = analyze.cashflow(conn, cfg, date(2026, 8, 1), date(2026, 8, 31),
                              date(2026, 8, 31))
        per = cf["period"]
        assert cf["monthly"]["free_cents"] == 500000
        assert per["overspend_cents"] == max(
            per["discretionary_spent_cents"] - per["free_budget_cents"], 0)
        # Whatever is overspent is exactly what the target loses.
        assert (per["savings_remaining_cents"]
                == per["savings_target_cents"] - per["overspend_cents"])
        assert per["savings_remaining_cents"] < per["savings_target_cents"]


def test_savings_target_survives_when_inside_the_allowance():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "Overall", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}],
               savings_model="residual")
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 8, 10), -100000, "SHOP",
                                         "visa", category="Shopping")])
        per = analyze.cashflow(conn, cfg, date(2026, 8, 1), date(2026, 8, 31),
                               date(2026, 8, 31))["period"]
        assert per["overspend_cents"] == 0
        assert per["savings_remaining_cents"] == per["savings_target_cents"]


def test_residual_is_the_default_savings_model():
    import budget.config as cfgmod
    assert cfgmod.savings_model({"settings": {}}) == "residual"
    assert cfgmod.savings_model({"settings": {"savings_model": "transactions"}}) == "transactions"
    assert cfgmod.savings_model({"settings": {"savings_model": "nonsense"}}) == "residual"


def test_savings_is_income_minus_spending_not_a_transaction():
    # Most households never make a savings transfer; what is not spent simply
    # stays put. Measuring from Savings rows would report 0% forever.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "Overall", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}],
               savings_model="residual")
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # $8,000/month spent against $10,000/month income, across the whole
        # 3-month measurement window: $2,000/month kept.
        for m in (6, 7, 8):
            for d in (5, 15, 25):
                ledger.insert(conn, [Transaction(date(2026, m, d), -266667, f"SHOP{m}{d}",
                                                 "visa", category="Shopping")])
        g = analyze.goals_status(conn, cfg, date(2026, 8, 31))[0]
        assert g["savings_model"] == "residual"
        assert g["required_monthly_cents"] == 100000          # 10% of 10,000
        assert g["spending_ceiling_cents"] == 900000          # income - target
        # No Savings-category rows exist at all, yet the goal is measurable.
        assert analyze.savings_only(ledger.fetch(conn)) == []
        assert g["observed_monthly_cents"] > 0
        assert g["on_track"] is True
        assert g["overspend_monthly_cents"] == 0


def test_overspending_eats_into_the_target_and_is_reported():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "Overall", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}],
               savings_model="residual")
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # $9,600/month against a $9,000/month ceiling, across the window.
        for m in (6, 7, 8):
            for d in (5, 15, 25):
                ledger.insert(conn, [Transaction(date(2026, m, d), -320000, f"SHOP{m}{d}",
                                                 "visa", category="Shopping")])
        g = analyze.goals_status(conn, cfg, date(2026, 8, 31))[0]
        assert g["on_track"] is False
        assert g["overspend_monthly_cents"] > 0
        # Spending past the ceiling is exactly what eats the target.
        assert g["observed_monthly_cents"] < g["required_monthly_cents"]


def test_residual_is_shared_between_rate_goals_not_double_counted():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "a", "name": "A", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 6},
                      {"id": "b", "name": "B", "goal_type": "rate", "active": True,
                       "priority": 2, "contribution_type": "percent",
                       "percent_of_net_income": 4}],
               savings_model="residual")
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (6, 7, 8):
            ledger.insert(conn, [Transaction(date(2026, m, 10), -800000, f"SHOP{m}",
                                             "visa", category="Shopping")])
        a, b = analyze.goals_status(conn, cfg, date(2026, 8, 31))
        res = analyze.residual_savings(conn, cfg, date(2026, 8, 31))
        # 60/40 split of one residual, not the residual counted twice.
        assert abs((a["observed_monthly_cents"] + b["observed_monthly_cents"])
                   - res["monthly_residual_cents"]) <= 2
        assert a["observed_monthly_cents"] > b["observed_monthly_cents"]


def test_retirement_is_neither_spending_nor_goal_savings():
    # A yearly IRA contribution is real money leaving, but counting it as
    # spending would invent a huge month, and counting it toward a monthly
    # savings rate would flatter one month and starve the other eleven.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "Monthly savings", "goal_type": "rate",
                       "active": True, "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 5}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 3), -750000, "BROKERAGE SVC LLC", "chk", category="Retirement"),
            Transaction(date(2026, 9, 2), -5000, "TJ", "visa", category="Groceries"),
        ])
        rows = ledger.fetch(conn)
        assert sum(abs(t.amount_cents) for t in analyze.spend_only(rows)) == 5000
        assert analyze.savings_only(rows) == []
        assert sum(abs(t.amount_cents) for t in analyze.retirement_only(rows)) == 750000
        g = analyze.goals_status(conn, cfg, date(2026, 9, 18))[0]
        assert g["observed_monthly_cents"] == 0     # IRA does not count toward it

        rep = analyze.build_report(conn, cfg, "month", date(2026, 9, 18))
        assert rep["totals"]["retirement_cents"] == 750000
        # ...but the money did leave, so net must reflect it.
        t = rep["totals"]
        assert t["net_cents"] == (t["expected_income_cents"] - t["spend_cents"]
                                  - t["saved_cents"] - t["retirement_cents"])


def test_annual_contribution_is_amortized_to_monthly():
    import budget.config as cfgmod
    g = {"id": "ira", "name": "IRA", "goal_type": "rate", "active": True, "priority": 1,
         "contribution_type": "fixed", "contribution_fixed_cents": 750000,
         "contribution_cadence": "annual"}
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}], goals=[g])
    assert cfgmod.planned_monthly(cfg, g) == 62500      # $7,500/yr -> $625/mo
    g["contribution_cadence"] = "monthly"
    assert cfgmod.planned_monthly(cfg, g) == 750000


def test_savings_measurement_ignores_the_analysis_clamp():
    # The clamp exists because CARD exports are short; savings transfers come
    # from checking, which is complete. Clamping them would discard a year of
    # data and make a lumpy contribution unmeasurable.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "fixed",
                       "contribution_fixed_cents": 50000, "measure_months": 12}])
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (3, 6, 9):
            ledger.insert(conn, [Transaction(date(2026, m, 1), -200000, f"VG{m}",
                                             "chk", category="Savings")])
        g = analyze.goals_status(conn, cfg, date(2026, 9, 18))[0]
        # All three contributions counted despite predating the clamp.
        assert g["observed_monthly_cents"] == round(600000 / 12)
        assert g["measure_months"] == 12
        # Spending analysis is still clamped.
        assert analyze.window(conn, cfg, date(2026, 1, 1), date(2026, 9, 18)) == []


def test_savings_pace_flags_behind():
    cfg = _cfg(goals=[{"id": "g", "name": "G", "target_cents": 10000000,
                       "current_balance_cents": 1000000, "balance_as_of": "2026-06-01",
                       "target_date": "2027-09-20", "priority": 1}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # $500/mo for 3 months against a goal needing far more.
        for m, d in ((7, 1), (8, 1), (9, 1)):
            ledger.insert(conn, [Transaction(date(2026, m, d), -50000, f"VG{m}",
                                             "chk", category="Savings")])
        s = analyze.savings_status(conn, cfg, date(2026, 9, 20))
        assert s["on_track"] is False
        assert s["observed_monthly_cents"] == 50000
        assert s["required_monthly_cents"] > s["observed_monthly_cents"]
        assert s["monthly_gap_cents"] < 0


def test_budget_compares_against_the_full_monthly_envelope():
    cfg = _cfg(envelopes={"Groceries": 60000})
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 15), -10000, "TJ",
                                         "visa", category="Groceries")])
        row = next(r for r in analyze.budget_status(conn, cfg, date(2026, 9, 14),
                                                    date(2026, 9, 20))
                   if r["category"] == "Groceries")
        # Compared against the whole $600 envelope, not a 7-day slice of it.
        assert row["budget_monthly_cents"] == 60000
        assert row["pct_used"] == round(10000 / 60000 * 100, 1)
        assert row["status"] == "ok"
        assert row["days_observed"] <= row["days_in_month"]


def test_lumpy_category_is_amortized_not_medianed():
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # One $2,400 travel month out of six must not become a $2,400 budget.
        ledger.insert(conn, [Transaction(date(2026, 7, 11), -240000, "AIRLINE",
                                         "amex", category="Travel")])
        for m in (4, 5, 6, 8):
            ledger.insert(conn, [Transaction(date(2026, m, 5), -30000, f"TJ{m}",
                                             "visa", category="Groceries")])
        prop = analyze.propose_budget(conn, cfg, date(2026, 9, 20), months=6)
        assert prop["Travel"] < 60000
        assert prop["Groceries"] > 0


def test_effective_dated_income_switches_on_the_raise():
    import budget.config as cfgmod
    cfg = _cfg(income=[
        {"name": "old", "net_monthly_cents": 500000,
         "effective_from": "2026-01-01", "effective_to": "2026-06-30"},
        {"name": "new", "net_monthly_cents": 700000, "effective_from": "2026-07-01"},
    ])
    assert cfgmod.monthly_income(cfg, date(2026, 5, 1)) == 500000
    assert cfgmod.monthly_income(cfg, date(2026, 8, 1)) == 700000
    # A month that straddles the change is integrated, not snapped to one rate.
    june = cfgmod.expected_income(cfg, date(2026, 6, 1), date(2026, 6, 30))
    july = cfgmod.expected_income(cfg, date(2026, 7, 1), date(2026, 7, 31))
    assert june < july


def test_income_without_dates_is_always_in_effect():
    # The common case: steady pay, both date fields left blank. It must apply to
    # every period, past and future, with no dates ever entered.
    import budget.config as cfgmod
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 792000,
                        "effective_from": None, "effective_to": None}])
    for d in (date(2020, 1, 1), date(2026, 5, 1), date(2031, 12, 1)):
        assert cfgmod.monthly_income(cfg, d) == 792000
    # And a missing key behaves the same as an explicit None.
    cfg2 = _cfg(income=[{"name": "pay", "net_monthly_cents": 792000}])
    assert cfgmod.monthly_income(cfg2, date(2026, 5, 1)) == 792000


def test_two_goals_do_not_double_count_one_contribution():
    cfg = _cfg(goals=[
        {"id": "a", "name": "House", "target_cents": 10000000, "target_date": "2029-06-01",
         "current_balance_cents": 0, "balance_as_of": "2026-06-01",
         "account_match": "vanguard", "priority": 1},
        {"id": "b", "name": "Emergency", "target_cents": 2000000, "target_date": "2028-01-01",
         "current_balance_cents": 0, "balance_as_of": "2026-06-01",
         "account_match": "ally", "priority": 2},
    ])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8, 9):
            ledger.insert(conn, [
                Transaction(date(2026, m, 1), -100000, "TRANSFER TO VANGUARD", "chk", category="Savings"),
                Transaction(date(2026, m, 2), -20000, "TRANSFER TO ALLY BANK", "chk", category="Savings"),
            ])
        house, emerg = analyze.goals_status(conn, cfg, date(2026, 9, 20))
        assert house["observed_monthly_cents"] == 100000
        assert emerg["observed_monthly_cents"] == 20000


def test_percent_contribution_is_of_after_tax_income():
    import budget.config as cfgmod
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000, "basis": "net"}],
               goals=[{"id": "g", "name": "G", "active": True, "priority": 1,
                       "contribution_type": "percent", "percent_of_net_income": 15}])
    assert cfgmod.planned_monthly(cfg, cfg["goals"]["goals"][0]) == 120000   # 15% of 8000
    # A raise scales the contribution without touching the goal.
    cfg["income"]["sources"][0]["net_monthly_cents"] = 1000000
    assert cfgmod.planned_monthly(cfg, cfg["goals"]["goals"][0]) == 150000


def test_gross_income_is_excluded_not_silently_spent():
    import budget.config as cfgmod
    cfg = _cfg(income=[{"name": "net pay", "net_monthly_cents": 800000, "basis": "net"},
                       {"name": "gross pay", "net_monthly_cents": 1200000, "basis": "gross"}])
    # A percentage plan applied to gross would commit money that never arrives.
    assert cfgmod.monthly_income(cfg) == 800000
    assert any("basis" in w for w in cfgmod.validate(cfg))


def test_fixed_and_auto_contribution_types():
    import budget.config as cfgmod
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "f", "name": "F", "active": True, "priority": 1,
                       "contribution_type": "fixed", "contribution_fixed_cents": 45000},
                      {"id": "a", "name": "A", "active": True, "priority": 2,
                       "contribution_type": "auto"}])
    f, a = cfg["goals"]["goals"]
    assert cfgmod.planned_monthly(cfg, f) == 45000
    assert cfgmod.planned_monthly(cfg, a) is None      # None means "no plan", not zero
    assert cfgmod.planned_total(cfg) == 45000


def test_plan_below_required_is_flagged():
    # The failure this catches: a plan that is followed perfectly and still
    # misses the goal. "On plan" and "on track" are different questions.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "House", "target_cents": 10000000,
                       "target_date": "2027-09-20", "current_balance_cents": 0,
                       "balance_as_of": "2026-09-01", "priority": 1, "active": True,
                       "contribution_type": "percent", "percent_of_net_income": 10}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8, 9):
            ledger.insert(conn, [Transaction(date(2026, m, 1), -80000, f"VG{m}",
                                             "chk", category="Savings")])
        g = analyze.goals_status(conn, cfg, date(2026, 9, 20))[0]
        assert g["planned_monthly_cents"] == 80000        # 10% of 8000
        assert g["required_monthly_cents"] > 80000
        assert g["plan_covers_goal"] is False             # plan cannot reach the target
        assert g["following_plan"] is True                # but they ARE saving the plan
        assert g["projected_at_plan"] > g["target_date"]


def test_cashflow_uses_planned_not_required():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               fixed=[{"id": "m", "name": "Rent", "category": "Housing",
                       "amount_cents": 200000, "cadence": "monthly", "due_day": 1,
                       "match": "rent", "effective_from": "2026-01-01"}],
               goals=[{"id": "g", "name": "G", "target_cents": 10000000,
                       "target_date": "2027-09-20", "current_balance_cents": 0,
                       "balance_as_of": "2026-09-01", "priority": 1, "active": True,
                       "contribution_type": "percent", "percent_of_net_income": 10}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        m = analyze.cashflow(conn, cfg, date(2026, 9, 1), date(2026, 9, 30),
                             date(2026, 9, 20))["monthly"]
        assert m["goal_planned_cents"] == 80000
        assert m["goal_required_cents"] > 80000
        # Free money reflects what actually leaves the account: the plan.
        assert m["free_cents"] == 800000 - 200000 - 80000
        assert m["plan_shortfall_cents"] < 0     # plan is short of the goal dates
        assert m["savings_rate_pct"] == 10.0


def test_commitment_verified_missing_and_drifted():
    fixed = [
        {"id": "m", "name": "Mortgage", "category": "Housing", "amount_cents": 285000,
         "cadence": "monthly", "due_day": 1, "match": "mortgage", "effective_from": "2026-01-01"},
        {"id": "c", "name": "Car loan", "category": "Debt", "amount_cents": 48000,
         "cadence": "monthly", "due_day": 5, "match": "car loan", "effective_from": "2026-01-01"},
        {"id": "u", "name": "Electric", "category": "Utilities", "amount_cents": 14000,
         "cadence": "monthly", "due_day": 8, "match": "pg&e", "variable": True,
         "effective_from": "2026-01-01"},
    ]
    cfg = _cfg(fixed=fixed)
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 8, 1), -285000, "MORTGAGE PAYMENT", "chk", category="Housing"),
            # Car loan never posted this month.
            Transaction(date(2026, 8, 8), -21500, "PG&E ONLINE", "chk", category="Utilities"),
        ])
        rows = {r["name"]: r for r in
                analyze.verify_commitments(conn, cfg, date(2026, 8, 1), date(2026, 8, 31))}
        assert rows["Mortgage"]["status"] == "paid"
        assert rows["Car loan"]["status"] == "missing"
        # A variable bill is never flagged for drift, however far it moves.
        assert rows["Electric"]["status"] == "paid"
        assert rows["Electric"]["actual_cents"] == 21500


def test_commitments_due_before_the_window_are_not_called_missing():
    # The bill did post; we simply excluded that week from analysis. Reporting
    # it as MISSING invents a problem and trains the user to ignore the flag.
    cfg = _cfg(fixed=[{"id": "m", "name": "Mortgage", "category": "Housing",
                       "amount_cents": 607000, "cadence": "monthly", "due_day": 1,
                       "match": "loanservicer", "effective_from": "2026-01-01"}])
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 1), -605741, "LOANSERVICER PMT MTGE",
                                         "chk", category="Housing")])
        rows = analyze.verify_commitments(conn, cfg, date(2026, 9, 1), date(2026, 9, 30))
        assert rows == []          # due Sep 1, before the window: not reported at all
        # Without the clamp it is checked normally and found.
        cfg["settings"].pop("analysis_start")
        rows = analyze.verify_commitments(conn, cfg, date(2026, 9, 1), date(2026, 9, 30))
        assert rows and rows[0]["status"] == "paid"


def test_free_items_are_split_by_account_and_totals_reconcile():
    from budget.report_html import free_items_block
    items = [
        {"date": "2026-09-08", "merchant": "amazon", "description": "AMZN",
         "category": "Shopping", "account": "card-a", "amount_cents": 19336},
        {"date": "2026-09-10", "merchant": "whole foods", "description": "WF",
         "category": "Groceries", "account": "card-a", "amount_cents": 16454},
        {"date": "2026-09-16", "merchant": "costco", "description": "COSTCO",
         "category": "Groceries", "account": "card-c", "amount_cents": 40796},
    ]
    mtd = {"free_monthly_cents": 402083, "spent_cents": 76586,
           "remaining_cents": 325497, "month": "September 2026"}
    html = free_items_block(items, mtd, {})
    # Each account appears with its own subtotal.
    assert "card-a" in html and "card-c" in html
    assert fmt(19336 + 16454) in html      # card-a subtotal
    assert fmt(40796) in html              # card-c subtotal
    # Per-account totals must add up to the figure in the summary line.
    assert fmt(76586) in html
    # The long list stays folded by default.
    assert 'details class="fold"' in html and "<details open" not in html


def test_delete_account_undoes_a_mislabelled_ingest():
    # The account label is part of each transaction's identity, so a wrong one
    # cannot be corrected in place: the rows go and the file is re-read.
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 1), -5000, "A", "wrong-label"),
            Transaction(date(2026, 9, 2), -6000, "B", "wrong-label"),
            Transaction(date(2026, 9, 3), -7000, "C", "keep-me")])
        assert ledger.delete_account(conn, "wrong-label") == 2
        remaining = ledger.fetch(conn)
        assert len(remaining) == 1 and remaining[0].account == "keep-me"
        # Deleting an account that does not exist is a no-op, not an error.
        assert ledger.delete_account(conn, "never-existed") == 0
        # Re-ingesting under the right label produces new, distinct rows.
        ledger.insert(conn, [Transaction(date(2026, 9, 1), -5000, "A", "right-label")])
        assert len(ledger.fetch(conn)) == 2


def test_removing_a_commitment_raises_free_to_spend():
    import budget.config as cfgmod
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               fixed=[{"id": "a", "name": "Keep", "category": "Housing",
                       "amount_cents": 100000, "cadence": "monthly", "due_day": 1,
                       "match": "keep", "effective_from": "2026-01-01"},
                      {"id": "b", "name": "One-off", "category": "Utilities",
                       "amount_cents": 33600, "cadence": "monthly", "due_day": 14,
                       "match": "oneoff", "effective_from": "2026-01-01"}])
    assert cfgmod.fixed_monthly_total(cfg) == 133600
    cfg["fixed"]["expenses"] = [x for x in cfg["fixed"]["expenses"] if x["id"] != "b"]
    assert cfgmod.fixed_monthly_total(cfg) == 100000


def test_month_to_date_is_scoped_to_the_calendar_month():
    # The budget is monthly, so the headline must be the month - not whatever
    # period the report happens to cover.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 8, 28), -50000, "LASTMONTH", "visa", category="Shopping"),
            Transaction(date(2026, 9, 3), -30000, "THISMONTH", "visa", category="Shopping")])
        m = analyze.month_to_date(conn, cfg, date(2026, 9, 18))
        assert m["month"] == "September 2026"
        assert m["spent_cents"] == 30000          # August is not counted
        assert m["free_monthly_cents"] == 900000  # 10,000 income - 1,000 target
        assert m["remaining_cents"] == 870000
        assert m["pct_used"] == round(30000 / 900000 * 100, 1)
        assert m["days_in_month"] == 30 and m["days_left"] == 12


def test_month_to_date_reports_how_much_of_the_month_it_can_see():
    # A window starting mid-month makes the spend figure a floor. Saying "50% of
    # budget used" without saying only 40% of the month is observed reads better
    # than the truth.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}])
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 3), -99999, "BEFORE", "visa", category="Shopping"),
            Transaction(date(2026, 9, 10), -30000, "INSIDE", "visa", category="Shopping")])
        m = analyze.month_to_date(conn, cfg, date(2026, 9, 18))
        assert m["spent_cents"] == 30000       # the pre-window purchase is excluded
        assert m["days_observed"] == 12
        assert m["days_elapsed"] == 18
        assert m["partial"] is True
        assert m["pct_month_observed"] == 40


def test_month_to_date_and_the_item_list_use_the_same_budget():
    # Two different allowances on one page is how a report loses trust.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 3), -30000, "SHOP",
                                         "visa", category="Shopping")])
        rep = analyze.build_report(conn, cfg, "week", date(2026, 9, 18))
        html = report_html.render(rep)
        mtd = rep["month_to_date"]
        # The figure in the KPI row is the one the item list measures against.
        assert html.count(fmt(mtd["free_monthly_cents"])) >= 2


def test_monthly_history_excludes_partial_months():
    # A half month plotted beside whole ones reads as a fall in spending that
    # never happened, so partial months are left out rather than annotated.
    cfg = _cfg()
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 10), -5000, "TJ", "visa",
                                         category="Groceries")])
        h = analyze.monthly_history(conn, cfg, date(2026, 9, 18))
        assert h["months"] == []           # September is partial and still running
        assert h["first_complete_month"] == "October 2026"


def test_monthly_history_returns_whole_months_once_they_exist():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 10}])
    cfg["settings"]["analysis_start"] = "2026-06-01"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (6, 7, 8):
            ledger.insert(conn, [Transaction(date(2026, m, 10), -300000, f"SHOP{m}",
                                             "visa", category="Shopping")])
        h = analyze.monthly_history(conn, cfg, date(2026, 9, 18))
        labels = [m["month"] for m in h["months"]]
        assert labels == ["2026-06", "2026-07", "2026-08"]   # oldest first
        assert "2026-09" not in labels                        # current month excluded
        for m in h["months"]:
            assert m["discretionary_cents"] == 300000
            assert m["free_budget_cents"] > 0


def test_monthly_history_skips_months_the_window_only_partly_covers():
    # analysis_start mid-month means that month was never fully observed.
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1000000}])
    cfg["settings"]["analysis_start"] = "2026-07-15"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8):
            ledger.insert(conn, [Transaction(date(2026, m, 20), -100000, f"S{m}",
                                             "visa", category="Shopping")])
        h = analyze.monthly_history(conn, cfg, date(2026, 9, 18))
        assert [m["month"] for m in h["months"]] == ["2026-08"]


def test_free_spend_items_exclude_committed_categories():
    cfg = _cfg(fixed=[{"id": "m", "name": "Mortgage", "category": "Housing",
                       "amount_cents": 400000, "cadence": "monthly", "due_day": 1,
                       "match": "rent", "effective_from": "2026-01-01"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 2), -400000, "RENT", "chk", category="Housing"),
            Transaction(date(2026, 9, 3), -5000, "TJ", "visa", category="Groceries"),
            Transaction(date(2026, 9, 4), -9000, "AMZN", "visa", category="Shopping")])
        rep = analyze.build_report(conn, cfg, "month", date(2026, 9, 18))
        items = rep["free_spend_items"]
        assert {i["category"] for i in items} == {"Groceries", "Shopping"}
        # Largest first, so the biggest decision is at the top.
        assert [i["amount_cents"] for i in items] == [9000, 5000]


def test_reminders_sort_by_due_and_mark_overdue():
    import budget.config as cfgmod
    cfg = _cfg()
    cfg["reminders"] = {"reminders": [
        {"id": "a", "text": "later", "tag": "admin", "due": "2026-12-01", "active": True},
        {"id": "b", "text": "past", "tag": "tax", "due": "2026-08-01", "active": True},
        {"id": "c", "text": "undated", "tag": "goal", "active": True},
        {"id": "d", "text": "done", "tag": "admin", "due": "2026-09-01", "active": False},
    ]}
    out = cfgmod.reminders(cfg, date(2026, 9, 21))
    assert [r["id"] for r in out] == ["b", "a", "c"]   # soonest first, undated last
    assert out[0]["overdue"] is True
    assert out[1]["overdue"] is False and out[1]["days_until"] == 71
    assert out[2]["days_until"] is None
    assert "d" not in [r["id"] for r in out]           # cleared ones are hidden


def test_spending_actions_only_flag_real_problems_and_name_the_driver():
    from budget import analyze as A
    cfg = _cfg(envelopes={"Shopping": 75000, "Dining": 50000, "Transport": 27000},
               income=[{"name": "pay", "net_monthly_cents": 1500000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        rows = [Transaction(date(2026, 9, d), -12000, f"AMAZON MKTPL {d}", "visa",
                            category="Shopping") for d in range(1, 8)]      # $840, over
        rows.append(Transaction(date(2026, 9, 3), -5000, "CAFE", "visa", category="Dining"))
        ledger.insert(conn, rows)
        rep = A.build_report(conn, cfg, "month", date(2026, 9, 21))
        acts = {a["category"]: a for a in rep["spending_actions"]}
        # Only the breached category is raised; Dining and Transport are fine.
        assert set(acts) == {"Shopping"}
        a = acts["Shopping"]
        assert a["status"] == "over"
        assert a["over_cents"] == 84000 - 75000
        assert a["driver"]["merchant"] == "amazon" and a["driver"]["count"] == 7
        assert a["days_left"] == 9


def test_coverage_flags_an_account_with_no_recent_data():
    # A statement that was never uploaded reads as a month without spending,
    # which silently understates the total. It has to be named.
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 18), -5000, "FRESH", "current-card", category="Dining"),
            Transaction(date(2026, 9, 2), -6000, "OLD", "stale-card", category="Dining"),
            Transaction(date(2026, 7, 5), -7000, "ANCIENT", "absent-card", category="Dining"),
        ])
        cov = analyze.coverage(conn, cfg, date(2026, 9, 1), date(2026, 9, 18))
        by = {r["account"]: r for r in cov["accounts"]}
        assert by["current-card"]["stale"] is False
        assert by["stale-card"]["stale"] is True       # 16 days behind
        assert by["absent-card"]["absent"] is True     # nothing in the period
        assert set(cov["stale"]) >= {"stale-card", "absent-card"}
        assert cov["complete"] is False


def test_coverage_is_complete_when_every_account_is_current():
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 17), -5000, "A", "card-a", category="Dining"),
            Transaction(date(2026, 9, 18), -6000, "B", "card-b", category="Dining")])
        cov = analyze.coverage(conn, cfg, date(2026, 9, 1), date(2026, 9, 18))
        assert cov["complete"] is True and cov["stale"] == [] and cov["missing"] == []


def test_ingest_detects_a_non_overlapping_upload():
    # Exports default to a short recent window; downloading "last 7 days" a
    # fortnight later leaves a hole nothing else will ever reveal.
    import budget.cli as cli
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 7), -5000, "OLD", "visa")])

        contiguous = [Transaction(date(2026, 9, 8), -1000, "NEW", "visa")]
        assert cli._coverage_gap(conn, "visa", contiguous) is None

        overlapping = [Transaction(date(2026, 9, 5), -1000, "NEW", "visa")]
        assert cli._coverage_gap(conn, "visa", overlapping) is None

        gapped = [Transaction(date(2026, 9, 17), -1000, "NEW", "visa")]
        gap = cli._coverage_gap(conn, "visa", gapped)
        assert gap is not None and gap["missing_days"] == 9
        assert gap["stored_through"] == "2026-09-07"

        # A brand-new account cannot have a gap.
        assert cli._coverage_gap(conn, "never-seen", gapped) is None


def test_tracker_lists_every_commitment_even_outside_the_window():
    # The standing view must always show all of them, or one quietly stopping
    # being paid goes unnoticed. It reads full history because commitments come
    # from checking, which is complete.
    cfg = _cfg(fixed=[
        {"id": "m", "name": "Mortgage", "category": "Housing", "amount_cents": 607000,
         "cadence": "monthly", "due_day": 1, "match": "loanservicer",
         "effective_from": "2026-01-01"},
        {"id": "i", "name": "Insurance", "category": "Insurance", "amount_cents": 86500,
         "cadence": "semiannual", "due_day": 6, "match": "liberty",
         "effective_from": "2026-01-01"},
        {"id": "z", "name": "Never paid", "category": "Utilities", "amount_cents": 5000,
         "cadence": "monthly", "due_day": 1, "match": "nothing-matches-this",
         "effective_from": "2026-01-01"}])
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 1), -605741, "LOANSERVICER PMT MTGE", "chk"),
            Transaction(date(2026, 3, 6), -86500, "LIBERTY MUTUAL PAYMENT", "chk"),
        ])
        rows = {r["name"]: r for r in analyze.commitment_tracker(conn, cfg, date(2026, 9, 18))}
        assert set(rows) == {"Mortgage", "Insurance", "Never paid"}
        # Paid Sep 1, before the analysis window, yet still seen.
        assert rows["Mortgage"]["last_paid"] == "2026-09-01"
        assert rows["Mortgage"]["status"] == "on_track"
        # Semiannual from March is due Sep 5 and has not arrived.
        assert rows["Insurance"]["status"] == "overdue"
        assert rows["Insurance"]["days_overdue"] > 5
        assert rows["Never paid"]["status"] == "never_seen"
        assert rows["Never paid"]["last_paid"] is None


def test_tracker_sorts_problems_first():
    cfg = _cfg(fixed=[
        {"id": "a", "name": "Big fine one", "category": "Housing", "amount_cents": 500000,
         "cadence": "monthly", "due_day": 1, "match": "rent", "effective_from": "2026-01-01"},
        {"id": "b", "name": "Small broken one", "category": "Utilities", "amount_cents": 2000,
         "cadence": "monthly", "due_day": 1, "match": "gas", "effective_from": "2026-01-01"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 1), -500000, "RENT", "chk"),
            Transaction(date(2026, 5, 1), -2000, "GAS CO", "chk")])
        rows = analyze.commitment_tracker(conn, cfg, date(2026, 9, 18))
        # A small overdue item outranks a large healthy one.
        assert rows[0]["name"] == "Small broken one"


def test_tracker_does_not_flag_drift_on_a_variable_bill():
    cfg = _cfg(fixed=[{"id": "e", "name": "Electric", "category": "Utilities",
                       "amount_cents": 19500, "cadence": "monthly", "due_day": 28,
                       "match": "comed", "variable": True,
                       "effective_from": "2026-01-01"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 14), -30391, "ComEd PAYMENTS", "chk")])
        r = analyze.commitment_tracker(conn, cfg, date(2026, 9, 18))[0]
        assert r["status"] == "on_track"      # a seasonal swing is not a fault
        assert r["drift_cents"] == 0


def test_commitment_flags_amount_drift():
    cfg = _cfg(fixed=[{"id": "i", "name": "Insurance", "category": "Insurance",
                       "amount_cents": 16500, "cadence": "monthly", "due_day": 1,
                       "match": "geico", "effective_from": "2026-01-01"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 8, 1), -18300, "GEICO PREMIUM",
                                         "chk", category="Insurance")])
        r = analyze.verify_commitments(conn, cfg, date(2026, 8, 1), date(2026, 8, 31))[0]
        assert r["status"] == "drift"
        assert r["drift_cents"] == 1800


def test_committed_categories_are_not_discretionary_envelopes():
    cfg = _cfg(envelopes={"Groceries": 60000},
               fixed=[{"id": "m", "name": "Mortgage", "category": "Housing",
                       "amount_cents": 285000, "cadence": "monthly", "due_day": 1,
                       "match": "mortgage", "effective_from": "2026-01-01"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 9, 1), -285000, "MORTGAGE", "chk", category="Housing"),
            Transaction(date(2026, 9, 2), -10000, "TJ", "visa", category="Groceries"),
        ])
        cats = [r["category"] for r in
                analyze.budget_status(conn, cfg, date(2026, 9, 1), date(2026, 9, 30))]
        assert "Housing" not in cats      # a mortgage is not a weekly envelope
        assert "Groceries" in cats


def test_free_to_spend_subtracts_commitments_and_goals():
    cfg = _cfg(
        income=[{"name": "pay", "net_monthly_cents": 800000, "effective_from": "2026-01-01"}],
        fixed=[{"id": "m", "name": "Mortgage", "category": "Housing", "amount_cents": 285000,
                "cadence": "monthly", "due_day": 1, "match": "mortgage",
                "effective_from": "2026-01-01"},
               {"id": "a", "name": "Annual fee", "category": "Fees", "amount_cents": 60000,
                "cadence": "annual", "due_day": 1, "match": "annual",
                "effective_from": "2026-01-01"}],
        goals=[{"id": "g", "name": "G", "target_cents": 1000000, "target_date": "2027-09-20",
                "current_balance_cents": 0, "balance_as_of": "2026-09-01", "priority": 1}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        flow = analyze.cashflow(conn, cfg, date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 20))
        m = flow["monthly"]
        assert m["income_cents"] == 800000
        assert m["fixed_cents"] == 285000 + 5000          # annual fee amortized to $50/mo
        assert m["goal_required_cents"] > 0
        assert m["free_cents"] == m["income_cents"] - m["fixed_cents"] - m["goal_required_cents"]


# ------------------------------------------------------------------ optimize

def _opt_db(tmp):
    """A household with a subscription, a habit, and a category above its norm."""
    conn = _seeded_db(tmp)
    rows = []
    for m in (6, 7, 8):
        rows.append(Transaction(date(2026, m, 8), -2299, "NETFLIX.COM", "amex",
                                category="Entertainment", subcategory="Streaming"))
        rows.append(Transaction(date(2026, m, 3), -285000, "MORTGAGE", "chk", category="Housing"))
        for d in range(1, 9):            # 8 coffees a month at ~$7
            rows.append(Transaction(date(2026, m, d), -700, f"BLUE BOTTLE {m}{d}",
                                    "visa", category="Dining"))
    ledger.insert(conn, rows)
    return conn


def test_subscriptions_are_found_and_annualized():
    from budget import optimize
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        subs = optimize.subscription_candidates(conn, cfg, date(2026, 9, 20))
        netflix = next(c for c in subs if "netflix" in c["merchant"])
        assert netflix["saving_monthly_cents"] == 2299
        assert netflix["annual_cents"] == 2299 * 12
        assert netflix["difficulty"] == "easy"


def test_recommendations_never_target_committed_categories():
    from budget import optimize
    cfg = _cfg(fixed=[{"id": "m", "name": "Mortgage", "category": "Housing",
                       "amount_cents": 285000, "cadence": "monthly", "due_day": 3,
                       "match": "mortgage", "effective_from": "2026-01-01"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        cats = {c["category"] for c in optimize.candidates(conn, cfg, date(2026, 9, 20))}
        # Telling a household to spend less on housing or childcare is not advice.
        assert not (cats & optimize.UNTOUCHABLE - {"Health"})
        levers = optimize.discretionary_levers(conn, cfg, date(2026, 9, 20))
        assert "Housing" not in {l["category"] for l in levers["categories"]}


def test_subscription_savings_are_not_double_counted_in_category_cut():
    # "Cancel Netflix ($23)" plus "cut Entertainment to its median" must not both
    # claim the same dollar; category targets run on the variable remainder only.
    from budget import optimize
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        today = date(2026, 9, 20)
        cands = optimize.candidates(conn, cfg, today)
        ent = [c for c in cands if c["category"] == "Entertainment"]
        total = sum(c["saving_monthly_cents"] for c in ent)
        # Entertainment spend is the subscription and nothing else, so the most
        # that can be claimed from it is the subscription itself.
        assert total <= 2299


def test_weekly_allowance_matches_the_sum_of_its_rows():
    from budget import optimize
    cfg = _cfg(envelopes={"Dining": 20000, "Entertainment": 3000})
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        wk = optimize.next_week(conn, cfg, date(2026, 8, 20))
        assert wk["total_allowance_cents"] == sum(r["week_allowance_cents"]
                                                  for r in wk["categories"])
        # An overspent category contributes zero, never a negative allowance.
        assert all(r["week_allowance_cents"] >= 0 for r in wk["categories"])


def test_weekly_status_is_pace_aware_not_absolute():
    from budget import optimize
    cfg = _cfg(envelopes={"Dining": 10000})
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 8, 2), -8000, "CAFE",
                                         "visa", category="Dining")])
        # 80% spent on the 3rd is alarming...
        early = optimize.next_week(conn, cfg, date(2026, 8, 3))["categories"][0]
        assert early["status"] == "tight"
        # ...and the same 80% on the 28th is simply normal.
        late = optimize.next_week(conn, cfg, date(2026, 8, 28))["categories"][0]
        assert late["status"] == "ok"


def test_envelope_cuts_reconcile_with_identified_savings():
    from budget import optimize
    cfg = _cfg(envelopes={"Dining": 30000, "Entertainment": 5000},
               income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "G", "target_cents": 5000000,
                       "target_date": "2028-01-01", "current_balance_cents": 0,
                       "balance_as_of": "2026-09-01", "priority": 1, "active": True,
                       "contribution_type": "fixed", "contribution_fixed_cents": 10000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        today = date(2026, 9, 20)
        gap = optimize.gap_analysis(conn, cfg, today)
        nm = optimize.next_month(conn, cfg, today)
        # Every dollar claimed as identified must appear as an envelope cut.
        assert nm["total_cut_cents"] == gap["identified_cents"]


def test_short_history_admits_it_instead_of_claiming_zero_discretionary():
    # With a 12-day window the trailing-3-month baseline is entirely out of
    # scope, so every lever reads $0. Concluding "no amount of restraint closes
    # it" from that is a confident claim built on missing data.
    from budget import optimize
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 1470000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 5}])
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        today = date(2026, 9, 18)
        levers = optimize.discretionary_levers(conn, cfg, today)
        assert levers["sufficient_history"] is False
        assert levers["history_days"] == 12
        gap = optimize.gap_analysis(conn, cfg, today)
        assert gap["sufficient_history"] is False
        # No depth claim may be made without a baseline.
        assert gap["cut_depth_needed"] is None

        from budget.i18n import Translator
        from budget.recommend_html import _gap_block
        html = _gap_block(gap, levers, analyze.goals_status(conn, cfg, today),
                          Translator("en", "USD"), 1470000)
        assert "No amount of spending restraint" not in html
        assert "12 days of comparable history" in html


def test_clamped_levers_scale_by_days_seen_not_three_months():
    # analysis_start on Sep 7 leaves 24 days inside "the last 3 complete months".
    # Dividing those 24 days by 3 reported every monthly figure ~4x too low and
    # turned an achievable cut into "no amount of restraint closes it".
    from budget import optimize
    cfg = _cfg()
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = ledger.connect(Path(tmp) / "l.db")
        rows = [Transaction(date(2026, 9, 7) + timedelta(days=i), -10000, f"shop{i}",
                            "visa", category="Shopping") for i in range(35)]
        ledger.insert(conn, rows)
        today = date(2026, 10, 11)
        levers = optimize.discretionary_levers(conn, cfg, today)
        # Too few days in complete months: the window runs through today.
        assert levers["window_start"] == "2026-09-07"
        assert levers["window_end"] == "2026-10-11"
        assert levers["complete_months"] is False
        # $100 a day is about $3,044 a month, not 35 days of it divided by 3.
        assert abs(levers["discretionary_monthly_cents"] - 304400) < 100

        from budget.i18n import Translator
        from budget.recommend_html import _candidates_block
        html = _candidates_block([], {"sufficient_history": True}, Translator(), levers)
        assert "running at its own normal" not in html


def test_enough_history_still_reports_depth():
    from budget import optimize
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "S", "goal_type": "rate", "active": True,
                       "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 50}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        gap = optimize.gap_analysis(conn, cfg, date(2026, 9, 18))
        assert gap["sufficient_history"] is True
        assert gap["cut_depth_needed"] is not None


def test_gap_reports_impossible_when_bigger_than_discretionary():
    from budget import optimize
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "Huge", "target_cents": 50000000,
                       "target_date": "2027-01-01", "current_balance_cents": 0,
                       "balance_as_of": "2026-09-01", "priority": 1, "active": True,
                       "contribution_type": "fixed", "contribution_fixed_cents": 1000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        gap = optimize.gap_analysis(conn, cfg, date(2026, 9, 20))
        assert gap["covers_gap"] is False
        # Must say plainly that no amount of cutting closes it, not invent savings.
        assert gap["cut_depth_needed"]["achievable"] is False
        assert gap["cut_depth_needed"]["required_pct"] > 100


def test_gap_derivation_adds_up():
    # The page shows its own arithmetic, so the parts must equal the whole or the
    # reader can check it and find it wrong.
    from budget import optimize
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "a", "name": "House", "target_cents": 10000000,
                       "target_date": "2029-06-01", "current_balance_cents": 2000000,
                       "balance_as_of": "2026-09-01", "priority": 1, "active": True,
                       "account_match": "vanguard",
                       "contribution_type": "percent", "percent_of_net_income": 10},
                      {"id": "b", "name": "Emergency", "target_cents": 2000000,
                       "target_date": "2027-12-01", "current_balance_cents": 500000,
                       "balance_as_of": "2026-09-01", "priority": 2, "active": True,
                       "account_match": "ally",
                       "contribution_type": "fixed", "contribution_fixed_cents": 25000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        today = date(2026, 9, 20)
        gap = optimize.gap_analysis(conn, cfg, today)
        statuses = analyze.goals_status(conn, cfg, today)
        # Per-goal required must sum to the total the page prints.
        assert sum(g["required_monthly_cents"] for g in statuses) == gap["goal_required_cents"]
        # Per-goal planned must sum to the planned total.
        assert sum(g["planned_monthly_cents"] for g in statuses) == gap["currently_planned_cents"]
        # The shortfall is measured against money that actually moved, not intent:
        # for a rate goal, plan == required, so comparing those would always be 0.
        observed = sum(g["observed_monthly_cents"] for g in statuses)
        assert gap["currently_saving_cents"] == observed
        assert gap["gap_cents"] == max(gap["goal_required_cents"] - observed, 0)
        # Found + uncovered must equal the gap.
        assert gap["identified_cents"] + gap["uncovered_cents"] >= gap["gap_cents"]


def test_gap_block_never_claims_on_track_without_goals():
    from budget.i18n import Translator
    from budget.recommend_html import _gap_block
    t = Translator("en", "USD")
    levers = {"discretionary_monthly_cents": 300000}
    # No goals at all is not an all-clear.
    assert "No goals set" in _gap_block({"gap_cents": 0}, levers, [], t)
    # Goals with no target date cannot have a pace, so no verdict either.
    html = _gap_block({"gap_cents": 0}, levers, [{"name": "X", "required_monthly_cents": None}], t)
    assert "No target dates" in html
    # A genuinely funded plan does say yes.
    ok = _gap_block({"gap_cents": 0}, levers,
                    [{"name": "X", "required_monthly_cents": 1000}], t)
    assert ">Yes<" in ok


# ------------------------------------------------------------------ i18n

def test_every_string_has_every_language():
    from budget.i18n import LANGS, STRINGS
    missing = {k: [l for l in LANGS if l not in v] for k, v in STRINGS.items()}
    assert not {k: v for k, v in missing.items() if v}


def test_translations_keep_their_placeholders():
    # A dropped placeholder silently renders a sentence with a number missing.
    import re
    from budget.i18n import LANGS, STRINGS
    for key, entry in STRINGS.items():
        want = set(re.findall(r"\{(\w+)\}", entry["en"]))
        for lang in LANGS:
            got = set(re.findall(r"\{(\w+)\}", entry[lang]))
            assert got == want, f"{key} [{lang}]: {got} != {want}"


def test_currency_symbol_follows_config():
    from budget.i18n import Translator
    assert Translator("en", "USD").money(123456) == "$1,234.56"
    assert Translator("zh-Hans", "CNY").money(123456) == "\u00a51,234.56"
    assert Translator("en", "USD").money(-5000) == "-$50.00"
    assert Translator("en", "USD").money(5000, sign=True) == "+$50.00"


def test_period_labels_are_localized():
    from budget.i18n import period_label
    assert period_label("month", "2026-09-01", "2026-09-30", "en") == "September 2026"
    assert period_label("month", "2026-09-01", "2026-09-30", "zh-Hans") == "2026\u5e749\u6708"
    assert "\u5f53\u5468" in period_label("week", "2026-09-14", "2026-09-20", "zh-Hans")


def test_chinese_page_has_no_leftover_english_prose():
    # The page must not mix languages: every sentence comes from i18n, and the
    # data layer's English titles must never reach the rendered Chinese page.
    from budget import optimize
    from budget.recommend_html import render
    cfg = _cfg(envelopes={"Dining": 30000, "Entertainment": 5000},
               income=[{"name": "\u5de5\u8d44", "net_monthly_cents": 800000}],
               goals=[{"id": "g", "name": "\u623f\u5b50\u9996\u4ed8",
                       "target_cents": 10000000, "target_date": "2029-06-01",
                       "current_balance_cents": 2000000, "balance_as_of": "2026-09-01",
                       "priority": 1, "active": True,
                       "contribution_type": "percent", "percent_of_net_income": 10}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)
        data = optimize.build(conn, cfg, date(2026, 9, 20), "month")
        html = render(data, lang="zh-Hans", currency="CNY")
        assert 'lang="zh-Hans"' in html
        for phrase in ("Cancel or downgrade", "Bring ", "charged in each of",
                       "Are you on track", "Where it can come from", "Next 7 days",
                       "still to save", "visits a month"):
            assert phrase not in html, f"untranslated English in zh page: {phrase!r}"
        assert "\u00a5" in html and "$" not in html


# ------------------------------------------------------------------ rate goals

def test_rate_goal_needs_no_target_or_date():
    import budget.config as cfgmod
    g = {"id": "s", "name": "Monthly savings", "goal_type": "rate", "active": True,
         "priority": 1, "contribution_type": "percent", "percent_of_net_income": 20}
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}], goals=[g])
    assert cfgmod.goal_type(g) == "rate"
    assert cfgmod.planned_monthly(cfg, g) == 160000        # 20% of 8000
    # A rate goal must not be nagged about a missing target amount or date.
    warnings = " ".join(cfgmod.validate(cfg))
    assert "target amount" not in warnings and "target date" not in warnings


def test_goal_type_inferred_from_shape():
    import budget.config as cfgmod
    assert cfgmod.goal_type({"target_cents": 100000}) == "target"
    assert cfgmod.goal_type({"contribution_type": "percent"}) == "rate"
    # An explicit declaration always wins over the inference.
    assert cfgmod.goal_type({"goal_type": "rate", "target_cents": 100000}) == "rate"


def test_rate_goal_is_judged_on_money_actually_moved():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "s", "name": "Monthly savings", "goal_type": "rate",
                       "active": True, "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 20}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        # Saving $1,200/mo against a $1,600/mo goal.
        for m in (7, 8, 9):
            ledger.insert(conn, [Transaction(date(2026, m, 1), -120000, f"VG{m}",
                                             "chk", category="Savings")])
        g = analyze.goals_status(conn, cfg, date(2026, 9, 20))[0]
        assert g["goal_type"] == "rate"
        assert g["required_monthly_cents"] == 160000
        assert g["observed_monthly_cents"] == 120000
        assert g["on_track"] is False
        assert g["monthly_gap_cents"] == -40000
        assert g["actual_percent_of_income"] == 15.0
        assert g["target_percent_of_income"] == 20
        # No finish line exists, so no completion date may be claimed.
        assert g["projected_completion"] is None
        assert g["months_remaining"] is None


def test_rate_goal_saving_nothing_is_not_on_track():
    # The bug this guards: with plan == required, a gap computed as
    # required - planned is always zero, so a household that saved nothing all
    # quarter would be reported as on track.
    from budget import optimize
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "s", "name": "Monthly savings", "goal_type": "rate",
                       "active": True, "priority": 1, "contribution_type": "percent",
                       "percent_of_net_income": 20}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _opt_db(tmp)           # spending, but no Savings transactions
        today = date(2026, 9, 20)
        g = analyze.goals_status(conn, cfg, today)[0]
        assert g["observed_monthly_cents"] == 0
        assert g["on_track"] is False
        gap = optimize.gap_analysis(conn, cfg, today)
        assert gap["gap_cents"] == 160000


def test_rate_goal_met_reports_on_track():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "s", "name": "Monthly savings", "goal_type": "rate",
                       "active": True, "priority": 1, "contribution_type": "fixed",
                       "contribution_fixed_cents": 100000}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8, 9):
            ledger.insert(conn, [Transaction(date(2026, m, 1), -110000, f"VG{m}",
                                             "chk", category="Savings")])
        g = analyze.goals_status(conn, cfg, date(2026, 9, 20))[0]
        assert g["on_track"] is True
        assert g["monthly_gap_cents"] == 10000
        from budget import optimize
        assert optimize.gap_analysis(conn, cfg, date(2026, 9, 20))["gap_cents"] == 0


def test_rate_and_target_goals_coexist():
    cfg = _cfg(income=[{"name": "pay", "net_monthly_cents": 800000}],
               goals=[{"id": "r", "name": "Monthly savings", "goal_type": "rate",
                       "active": True, "priority": 1, "account_match": "ally",
                       "contribution_type": "percent", "percent_of_net_income": 10},
                      {"id": "t", "name": "House", "target_cents": 5000000,
                       "target_date": "2029-01-01", "current_balance_cents": 0,
                       "balance_as_of": "2026-09-01", "active": True, "priority": 2,
                       "account_match": "vanguard", "contribution_type": "auto"}])
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        for m in (7, 8, 9):
            ledger.insert(conn, [
                Transaction(date(2026, m, 1), -50000, f"ALLY{m}", "chk", category="Savings"),
                Transaction(date(2026, m, 2), -90000, f"VANGUARD{m}", "chk", category="Savings")])
        rate, target = analyze.goals_status(conn, cfg, date(2026, 9, 20))
        assert rate["goal_type"] == "rate" and target["goal_type"] == "target"
        assert rate["required_monthly_cents"] == 80000       # 10% of 8000
        assert rate["observed_monthly_cents"] == 50000       # ally only
        assert target["observed_monthly_cents"] == 90000     # vanguard only
        assert target["months_remaining"] is not None


def test_analysis_start_clamps_the_reported_period():
    # Reporting "last 30 days" while only 12 are in scope makes prorated budgets
    # and the daily burn rate wrong by the ratio between the two.
    cfg = _cfg()
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [
            Transaction(date(2026, 8, 25), -5000, "OLD", "visa", category="Dining"),
            Transaction(date(2026, 9, 10), -3000, "NEW", "visa", category="Dining"),
        ])
        rep = analyze.build_report(conn, cfg, "30-days", date(2026, 9, 18))
        assert rep["period"]["start"] == "2026-09-07"
        assert rep["period"]["days"] == 12
        assert rep["period"]["clamped_to_analysis_start"] is True
        assert "from 2026-09-07" in rep["period"]["label"]
        # The pre-window transaction must not be counted.
        assert rep["totals"]["spend_cents"] == 3000


def test_analysis_start_hides_earlier_rows_everywhere():
    cfg = _cfg()
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 5, 1), -9999, "OLD", "visa",
                                         category="Dining")])
        assert analyze.window(conn, cfg, date(2024, 1, 1), date(2026, 9, 20)) == []
        # Rows are still stored, just not analysed.
        assert len(ledger.fetch(conn)) == 1


def test_trend_omits_periods_outside_the_analysis_window():
    # A flat zero line reads as "spent nothing that week", not "no data".
    cfg = _cfg()
    cfg["settings"]["analysis_start"] = "2026-09-07"
    with tempfile.TemporaryDirectory() as tmp:
        conn = _seeded_db(tmp)
        ledger.insert(conn, [Transaction(date(2026, 9, 10), -5000, "TJ", "visa",
                                         category="Groceries")])
        pts = analyze.trend(conn, cfg, date(2026, 9, 18), periods=8, unit="week")
        assert all(p["end"] >= "2026-09-07" for p in pts)
        assert len(pts) < 8
        # Without a clamp the full run of periods is returned.
        cfg["settings"].pop("analysis_start")
        assert len(analyze.trend(conn, cfg, date(2026, 9, 18), periods=8, unit="week")) == 8


def test_period_resolution():
    t = date(2026, 9, 20)   # a Sunday
    assert analyze.resolve_period("week", t)[:2] == (date(2026, 9, 14), date(2026, 9, 20))
    assert analyze.resolve_period("last-week", t)[:2] == (date(2026, 9, 7), date(2026, 9, 13))
    assert analyze.resolve_period("last-month", t)[:2] == (date(2026, 8, 1), date(2026, 8, 31))
    assert analyze.resolve_period("2026-02", t)[:2] == (date(2026, 2, 1), date(2026, 2, 28))


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:
                fails += 1
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if fails else 'ALL PASSED'} ({fails} failure(s))")
    sys.exit(1 if fails else 0)
