"""Rule-based categorization, with a learning path for the agent.

Deterministic rules run first and handle the long tail of repeat merchants.
Whatever they can't match is left blank for the budget-analyst agent, which
classifies it and writes the answer back as a learned rule so the same merchant
is free next week. The LLM does judgment, never arithmetic.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .schema import Transaction, normalize_merchant

RULES_PATH = Path(os.environ.get(
    "BUDGET_RULES", Path(__file__).resolve().parent.parent / "config" / "rules.json"))

# Seed rules: (substring matched against merchant+description, category, subcategory)
# Generic verbs like "transfer to" describe the mechanism, not the destination.
# A named institution ("vanguard") tells you far more, so these must lose to it
# even though they are the longer string - otherwise a savings contribution gets
# filed as an internal transfer and drops out of savings tracking entirely.
GENERIC = {
    "transfer to", "transfer from", "online payment", "autopay",
    "payment thank you", "loan payment", "insurance", "school", "restaurant",
    "parking", "pharmacy", "medical", "hospital", "dental", "gym", "fitness",
    "hotel", "airlines", "cafe", "pizza", "sushi", "bar ",
}

SEED_RULES = [
    # Income
    ("payroll", "Income", "Salary"), ("direct dep", "Income", "Salary"),
    ("dir dep", "Income", "Salary"), ("irs treas", "Income", "Tax refund"),
    ("interest paid", "Income", "Interest"), ("dividend", "Income", "Dividend"),
    # Card payments, by issuer. Matched specifically rather than on the word
    # "payment", because ComEd, the gas company and the insurer all use it too
    # and those are real spending.
    ("crcardpmt", "Transfer", "Card payment"),
    ("applecard", "Transfer", "Card payment"),
    ("chase credit crd", "Transfer", "Card payment"),
    ("citi autopay", "Transfer", "Card payment"),
    ("auto-pmt", "Transfer", "Card payment"),
    ("capital one autopay", "Transfer", "Card payment"),
    # Real bills that happen to say "payment"
    ("comed", "Utilities", "Electric"),
    ("north shore gas", "Utilities", "Gas"),
    ("liberty mutual", "Insurance", "General"),
    ("nicor", "Utilities", "Gas"),
    ("xfinity mobile", "Utilities", "Phone"),
    # Transfers / payments between own accounts
    ("payment thank you", "Transfer", "Card payment"),
    ("online payment", "Transfer", "Card payment"),
    ("autopay", "Transfer", "Card payment"),
    ("transfer to", "Transfer", "Internal"), ("transfer from", "Transfer", "Internal"),
    ("zelle", "Transfer", "Person"), ("venmo", "Transfer", "Person"),
    ("cash app", "Transfer", "Person"),
    # Retirement: not spending, and deliberately not the monthly savings goal
    ("ira contribution", "Retirement", "IRA"), ("roth ira", "Retirement", "IRA"),
    ("fid bkg svc", "Retirement", "IRA"), ("401k", "Retirement", "401k"),
    ("vanguard ira", "Retirement", "IRA"),
    # Savings / investing
    ("vanguard", "Savings", "Brokerage"), ("fidelity", "Savings", "Brokerage"),
    ("schwab", "Savings", "Brokerage"), ("betterment", "Savings", "Brokerage"),
    ("wealthfront", "Savings", "Brokerage"), ("acorns", "Savings", "Brokerage"),
    ("ally bank", "Savings", "High-yield"),
    # Housing
    ("rent", "Housing", "Rent"), ("mortgage", "Housing", "Mortgage"),
    ("hoa", "Housing", "HOA"), ("home depot", "Housing", "Maintenance"),
    ("lowes", "Housing", "Maintenance"),
    # Utilities
    ("pg&e", "Utilities", "Electric/Gas"), ("pge", "Utilities", "Electric/Gas"),
    ("comcast", "Utilities", "Internet"), ("xfinity", "Utilities", "Internet"),
    ("at&t", "Utilities", "Phone"), ("verizon", "Utilities", "Phone"),
    ("t-mobile", "Utilities", "Phone"), ("water district", "Utilities", "Water"),
    ("waste management", "Utilities", "Trash"),
    # Groceries
    ("trader joe", "Groceries", "Supermarket"), ("whole foods", "Groceries", "Supermarket"),
    ("safeway", "Groceries", "Supermarket"), ("costco", "Groceries", "Warehouse"),
    ("kroger", "Groceries", "Supermarket"), ("ralphs", "Groceries", "Supermarket"),
    ("albertsons", "Groceries", "Supermarket"), ("sprouts", "Groceries", "Supermarket"),
    ("h mart", "Groceries", "Supermarket"), ("99 ranch", "Groceries", "Supermarket"),
    ("aldi", "Groceries", "Supermarket"), ("publix", "Groceries", "Supermarket"),
    ("wegmans", "Groceries", "Supermarket"), ("instacart", "Groceries", "Delivery"),
    # Dining
    ("starbucks", "Dining", "Coffee"), ("blue bottle", "Dining", "Coffee"),
    ("peet", "Dining", "Coffee"), ("dunkin", "Dining", "Coffee"),
    ("doordash", "Dining", "Delivery"), ("uber eats", "Dining", "Delivery"),
    ("grubhub", "Dining", "Delivery"), ("postmates", "Dining", "Delivery"),
    ("chipotle", "Dining", "Fast food"), ("mcdonald", "Dining", "Fast food"),
    ("subway", "Dining", "Fast food"), ("panera", "Dining", "Fast food"),
    ("chick-fil-a", "Dining", "Fast food"), ("taco bell", "Dining", "Fast food"),
    ("popeyes", "Dining", "Fast food"), ("wendy", "Dining", "Fast food"),
    ("burger king", "Dining", "Fast food"), ("kfc", "Dining", "Fast food"),
    ("restaurant", "Dining", "Restaurant"), ("pizza", "Dining", "Restaurant"),
    ("sushi", "Dining", "Restaurant"), ("cafe", "Dining", "Restaurant"),
    ("bar ", "Dining", "Bar"), ("brewing", "Dining", "Bar"),
    # Transport
    ("uber", "Transport", "Rideshare"), ("lyft", "Transport", "Rideshare"),
    ("shell", "Transport", "Gas"), ("chevron", "Transport", "Gas"),
    ("exxon", "Transport", "Gas"), ("arco", "Transport", "Gas"),
    ("76 ", "Transport", "Gas"), ("bp ", "Transport", "Gas"),
    ("parking", "Transport", "Parking"), ("fastrak", "Transport", "Tolls"),
    ("ezpass", "Transport", "Tolls"), ("clipper", "Transport", "Transit"),
    ("bart", "Transport", "Transit"), ("caltrain", "Transport", "Transit"),
    ("mta", "Transport", "Transit"), ("dmv", "Transport", "Registration"),
    ("jiffy lube", "Transport", "Maintenance"), ("tesla superch", "Transport", "Charging"),
    # Health
    ("pharmacy", "Health", "Pharmacy"), ("cvs", "Health", "Pharmacy"),
    ("walgreens", "Health", "Pharmacy"), ("rite aid", "Health", "Pharmacy"),
    ("dental", "Health", "Dental"), ("dentist", "Health", "Dental"),
    ("medical", "Health", "Doctor"), ("kaiser", "Health", "Doctor"),
    ("hospital", "Health", "Doctor"), ("optometry", "Health", "Vision"),
    ("gym", "Health", "Fitness"), ("fitness", "Health", "Fitness"),
    ("life time", "Health", "Fitness"), ("ltfitness", "Health", "Fitness"),
    ("ltf*", "Health", "Fitness"), ("kiehls", "Shopping", "Personal care"),
    ("equinox", "Health", "Fitness"), ("peloton", "Health", "Fitness"),
    # Insurance
    ("geico", "Insurance", "Auto"), ("state farm", "Insurance", "Auto"),
    ("progressive", "Insurance", "Auto"), ("allstate", "Insurance", "Home"),
    ("insurance", "Insurance", "General"),
    # Childcare / Education
    ("daycare", "Childcare", "Daycare"), ("preschool", "Childcare", "Preschool"),
    ("tuition", "Education", "Tuition"), ("school", "Education", "School"),
    ("coursera", "Education", "Courses"), ("udemy", "Education", "Courses"),
    # Shopping
    ("amazon", "Shopping", "Online"), ("amzn", "Shopping", "Online"),
    ("target", "Shopping", "General"), ("walmart", "Shopping", "General"),
    ("wal-mart", "Shopping", "General"),
    ("ikea", "Shopping", "Home goods"), ("etsy", "Shopping", "Online"),
    ("ebay", "Shopping", "Online"), ("nordstrom", "Shopping", "Clothing"),
    ("uniqlo", "Shopping", "Clothing"), ("nike", "Shopping", "Clothing"),
    ("best buy", "Shopping", "Electronics"), ("apple.com", "Shopping", "Electronics"),
    # Entertainment
    ("netflix", "Entertainment", "Streaming"), ("spotify", "Entertainment", "Streaming"),
    ("hulu", "Entertainment", "Streaming"), ("disney", "Entertainment", "Streaming"),
    ("hbo", "Entertainment", "Streaming"), ("youtube premium", "Entertainment", "Streaming"),
    ("audible", "Entertainment", "Streaming"), ("steam", "Entertainment", "Games"),
    ("playstation", "Entertainment", "Games"), ("nintendo", "Entertainment", "Games"),
    ("amc ", "Entertainment", "Movies"), ("cinema", "Entertainment", "Movies"),
    ("ticketmaster", "Entertainment", "Events"), ("eventbrite", "Entertainment", "Events"),
    # Travel
    ("airlines", "Travel", "Flights"), ("united air", "Travel", "Flights"),
    ("southwest", "Travel", "Flights"), ("delta air", "Travel", "Flights"),
    ("airbnb", "Travel", "Lodging"), ("hotel", "Travel", "Lodging"),
    ("marriott", "Travel", "Lodging"), ("hilton", "Travel", "Lodging"),
    ("expedia", "Travel", "Booking"), ("hertz", "Travel", "Car rental"),
    # Debt
    ("student loan", "Debt", "Student loan"), ("nelnet", "Debt", "Student loan"),
    ("sallie mae", "Debt", "Student loan"), ("loan payment", "Debt", "Loan"),
    # Fees
    ("overdraft", "Fees", "Overdraft"), ("atm fee", "Fees", "ATM"),
    ("annual fee", "Fees", "Annual fee"), ("late fee", "Fees", "Late fee"),
    ("foreign transaction", "Fees", "FX"), ("service charge", "Fees", "Service"),
]


# Patterns that plain substring matching cannot express. Bank descriptions pad
# fields with runs of spaces, and the merchant normalizer strips the word
# "PAYMENT" as noise, so "DISCOVER         E-PAYMENT" matches neither form.
SEED_REGEX = [
    # An HSA/FSA claim reimbursement is money coming back, not new income and
    # not a contribution. Must outrank the administrator's name: "FIDELITY
    # INVESTM CLAIM REIM" is a refund, not a brokerage deposit.
    (r"claim\s+reim", "Transfer", "HSA/FSA reimbursement"),
    (r"discover\s+e-?\s*payment", "Transfer", "Card payment"),
    (r"\bcap(ital)?\s*one\s+(crcardpmt|autopay)", "Transfer", "Card payment"),
    (r"\bchase\s+credit\s+crd", "Transfer", "Card payment"),
    (r"\bamex\s+epayment\b", "Transfer", "Card payment"),
    (r"\bbk\s*of\s*amer.*(payment|pymt)", "Transfer", "Card payment"),
]


def default_rules() -> dict:
    return {
        "version": 1,
        "rules": [
            {"match": m, "category": c, "subcategory": s, "source": "seed",
             "priority": 10 if m in GENERIC else 100}
            for m, c, s in SEED_RULES
        ] + [
            {"regex": r, "match": "", "category": c, "subcategory": s,
             "source": "seed-regex", "priority": 150}
            for r, c, s in SEED_REGEX
        ],
        "learned": {},
    }


def load_rules(path: Path = RULES_PATH) -> dict:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        rules = default_rules()
        path.write_text(json.dumps(rules, indent=2))
        return rules
    return json.loads(path.read_text())


def save_rules(rules: dict, path: Path = RULES_PATH) -> None:
    path.write_text(json.dumps(rules, indent=2))


def learn(merchant: str, category: str, subcategory: str = "", path: Path = RULES_PATH) -> dict:
    """Persist an agent/human decision so this merchant never needs asking again."""
    rules = load_rules(path)
    rules.setdefault("learned", {})[normalize_merchant(merchant)] = {
        "category": category,
        "subcategory": subcategory,
    }
    save_rules(rules, path)
    return rules


def categorize(txn: Transaction, rules: dict) -> Transaction:
    """Assign a category in place. Leaves it blank when nothing matches."""
    haystack = f"{txn.merchant} {txn.description}".lower()

    # 1. Learned exact-merchant mappings win: they are the most specific signal.
    learned = rules.get("learned", {}).get(txn.merchant)
    if learned:
        txn.category = learned["category"]
        txn.subcategory = learned.get("subcategory", "")
        txn.category_source = "agent"
        return txn

    # 2. Explicit rules: highest priority first, then longest match, so
    #    "uber eats" beats "uber" and "vanguard" beats "transfer to".
    for rule in sorted(rules.get("rules", []),
                       key=lambda r: (-r.get("priority", 100), -len(r.get("match", "")))):
        pattern = rule.get("regex")
        matched = (
            re.search(pattern, haystack, re.I) if pattern
            else rule.get("match", "").lower() in haystack
        )
        if not matched:
            continue
        if rule.get("account") and rule["account"] != txn.account:
            continue
        txn.category = rule["category"]
        txn.subcategory = rule.get("subcategory", "")
        txn.category_source = "rule"
        return txn

    # 3. Positive amounts with no match are far more likely income than a refund.
    if txn.amount_cents > 0 and not txn.category:
        txn.category = ""  # leave for the agent; guessing here corrupts income totals
    return txn


def categorize_all(txns: list[Transaction], rules: dict | None = None) -> list[Transaction]:
    rules = rules or load_rules()
    return [categorize(t, rules) for t in txns]


def find_internal_transfers(txns: list[Transaction], window_days: int = 4) -> list[tuple[str, str]]:
    """Pair equal-and-opposite amounts across different accounts.

    A card payment leaves the checking account and arrives at the card. Both
    rows are real, but counting either as spending would inflate the household's
    outflow, so they get matched and marked Transfer.
    """
    pairs, used = [], set()
    by_amount: dict[int, list[Transaction]] = {}
    for t in txns:
        by_amount.setdefault(abs(t.amount_cents), []).append(t)
    for amount, group in by_amount.items():
        if amount == 0 or len(group) < 2:
            continue
        outs = [t for t in group if t.amount_cents < 0]
        ins = [t for t in group if t.amount_cents > 0]
        for o in outs:
            if o.id in used:
                continue
            for i in ins:
                if i.id in used or i.account == o.account:
                    continue
                if abs((i.date - o.date).days) <= window_days:
                    pairs.append((o.id, i.id))
                    used.update({o.id, i.id})
                    break
    return pairs
