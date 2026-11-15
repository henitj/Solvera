# Solvra — a ledger-backed financial workspace with account-grounded chat and voice.
# Runs locally or in Google Colab without paid APIs. Uses a fictional demo account.
import calendar
import copy
import datetime as dt
import html
import math
import os
import random
import re
import sys
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from solvra_speech import speech_text  # noqa: F401 - compatibility re-export

# Keep a single module instance when launched as a script (UI modules import it).
if __name__ == "__main__":
    sys.modules.setdefault("solvra_app", sys.modules[__name__])

# ----------------------------- data_models ---------------------------------
AS_OF = dt.date(2026, 11, 14)
DISCLAIMER = "This project is a prototype and is not financial advice."
RNG_SEED = 271828


@dataclass
class Bill:
    bill_id: str
    name: str
    provider: str
    category: str
    amount: float
    due_date: dt.date
    minimum_payment: float = 0.0
    late_fee: float = 0.0
    apr: float = 0.0
    grace_days: int = 0
    consequence: str = "Late payment may incur a fee."
    critical_risk: float = 0.0  # Prioritization points, not a forecast dollar loss.
    risk_after_days: int = 7
    confirmed_extension: bool = False
    extension_date: dt.date | None = None
    partial_allowed: bool = True
    status: str = "Upcoming"

    @property
    def effective_due(self) -> dt.date:
        if self.confirmed_extension and self.extension_date:
            return self.extension_date
        return self.due_date


@dataclass
class IncomeEvent:
    amount: float
    date: dt.date
    label: str = "Expected income"
    confirmed: bool = False


@dataclass
class Scenario:
    available_cash: float
    as_of: dt.date
    bills: list[Bill]
    incomes: list[IncomeEvent] = field(default_factory=list)
    reserve: float = 0.0
    horizon_days: int = 35


@dataclass
class PlanResult:
    payments: list[dict[str, Any]]  # one row per payment: bill_id, bill, date, amount
    harm: dict[str, float]  # Fees/interest in dollars; risk/composite harm are weighted scores.
    total_allocated: float
    unpaid: float


# ----------------------------- synthetic_data ------------------------------
def _date(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _month_iter(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def generate_demo_records() -> dict[str, Any]:
    """Build a deterministic, ledger-backed fictional 24-month household history."""
    rng = random.Random(RNG_SEED)
    start, cutoff = dt.date(2024, 11, 15), AS_OF
    opening = {"Checking": 1350.0, "Savings": 2450.0}
    initial_debt = {"Credit Card": 2140.0, "Auto Loan": 11800.0, "Student Loan": 6450.0}
    events: list[dict[str, Any]] = []
    bill_rows: list[dict[str, Any]] = []
    incomes: list[dict[str, Any]] = []

    def add_event(date, kind, amount, category, merchant, description, **extra):
        events.append(
            dict(
                date=date,
                kind=kind,
                amount=amount,
                category=category,
                merchant=merchant,
                description=description,
                **extra,
            )
        )

    bill_specs = [
        (
            "Rent",
            "Northside Property Group",
            "Housing",
            1325,
            1,
            0,
            0,
            0.0,
            0,
            "Housing stability risk",
            1050,
            5,
            False,
        ),
        (
            "Electricity",
            "ComEd",
            "Utilities",
            112,
            16,
            25,
            18,
            0.18,
            5,
            "Possible service interruption; provider terms vary",
            360,
            9,
            True,
        ),
        (
            "Natural Gas",
            "Peoples Gas",
            "Utilities",
            49,
            19,
            20,
            15,
            0.18,
            5,
            "Possible service interruption; provider terms vary",
            260,
            12,
            True,
        ),
        (
            "Internet",
            "Astound Broadband",
            "Utilities",
            72,
            20,
            25,
            10,
            0.24,
            3,
            "Service may be restricted after provider notice",
            100,
            14,
            True,
        ),
        (
            "Mobile Phone",
            "T-Mobile",
            "Utilities",
            64,
            22,
            25,
            10,
            0.24,
            3,
            "Service may be interrupted after provider notice",
            180,
            12,
            True,
        ),
        (
            "Auto Loan",
            "Lakeview Credit Union",
            "Debt payments",
            318,
            23,
            318,
            28,
            0.089,
            10,
            "Credit and repossession risk depends on account and law",
            650,
            24,
            False,
        ),
        (
            "Auto Insurance",
            "Midwest Mutual",
            "Insurance",
            164,
            24,
            0,
            20,
            0.0,
            5,
            "Coverage lapse risk; contact insurer to confirm terms",
            700,
            12,
            True,
        ),
        (
            "Credit Card Minimum",
            "Harbor Bank Card",
            "Debt payments",
            112,
            18,
            45,
            35,
            0.249,
            21,
            "Interest and credit reporting risk; issuer terms apply",
            220,
            35,
            True,
        ),
        (
            "Student Loan",
            "Federal Student Aid Servicer",
            "Debt payments",
            125,
            25,
            125,
            0,
            0.052,
            15,
            "Program-specific consequences; confirm servicer terms",
            130,
            40,
            False,
        ),
        (
            "Streaming & Apps",
            "Subscription Bundle",
            "Subscriptions",
            42,
            27,
            0,
            0,
            0.0,
            0,
            "Usually cancellable; service may stop",
            0,
            30,
            True,
        ),
    ]
    month_names = list(_month_iter(start, cutoff))
    # Payroll: two semi-monthly deposits, with a documented temporary reduction and delay.
    for y, m in month_names:
        for day in (5, 20):
            paydate = _date(y, m, day)
            if paydate < start or paydate > cutoff:
                continue
            base = 2180 + (105 if (y, m) >= (2025, 12) else 0)
            if (y, m) in [(2026, 2), (2026, 3)]:
                base *= 0.82  # temporary reduced hours
            amt = round(base * rng.uniform(0.975, 1.035), 2)
            actual_date = (
                paydate + dt.timedelta(days=4) if (y, m, day) == (2026, 10, 20) else paydate
            )
            if actual_date <= cutoff:
                add_event(
                    actual_date,
                    "income",
                    amt,
                    "Income",
                    "Lakeshore Design Studio",
                    "Net semi-monthly paycheck",
                )
                incomes.append(
                    {
                        "date": actual_date,
                        "amount": amt,
                        "source": "Employment",
                        "type": "Regular paycheck",
                        "scheduled_date": paydate,
                        "delayed": actual_date != paydate,
                    }
                )
        if (y, m) in [(2025, 6), (2026, 7)]:
            bonus_date = _date(y, m, 28)
            if bonus_date <= cutoff:
                bonus = round(rng.uniform(180, 360), 2)
                add_event(
                    bonus_date,
                    "income",
                    bonus,
                    "Income",
                    "Lakeshore Design Studio",
                    "Occasional overtime",
                )
                incomes.append(
                    {
                        "date": bonus_date,
                        "amount": bonus,
                        "source": "Employment",
                        "type": "Overtime",
                        "scheduled_date": bonus_date,
                        "delayed": False,
                    }
                )

    # Recurring bill history. November 2026 obligations after the as-of date remain open.
    for y, m in month_names:
        for spec in bill_specs:
            (
                name,
                provider,
                category,
                base,
                due_day,
                minimum,
                late_fee,
                apr,
                grace,
                consequence,
                risk,
                riskdays,
                partial,
            ) = spec
            amount = float(base)
            if name == "Rent" and (y, m) >= (2025, 12):
                amount = 1425.0
            elif name == "Electricity":
                amount = max(72, rng.gauss(118, 19))
            elif name == "Natural Gas":
                amount = max(28, rng.gauss(53, 13))
            elif name == "Internet":
                amount = max(65, rng.gauss(73, 3))
            elif name == "Mobile Phone":
                amount = max(58, rng.gauss(65, 3))
            elif name == "Auto Insurance":
                amount = max(151, rng.gauss(165, 5))
            elif name == "Credit Card Minimum":
                amount = max(45, rng.gauss(118, 18))
            elif name == "Streaming & Apps" and (y, m) >= (2026, 7):
                amount = 19.99  # unused service canceled
            if name == "Electricity" and (y, m) == (2025, 8):
                amount = 298.40
            amount = round(amount, 2)
            due = _date(y, m, due_day)
            if due < start:
                continue
            # A few late and installment outcomes make the ledger's setbacks visible.
            late = (
                (name == "Electricity" and (y, m) == (2025, 8))
                or (name == "Credit Card Minimum" and (y, m) in [(2025, 5), (2026, 10)])
                or (name == "Auto Insurance" and (y, m) == (2025, 5))
            )
            partial_month = name == "Electricity" and (y, m) == (2025, 8)
            pay_date = due + dt.timedelta(days=(8 if late else rng.choice([0, 0, 1, 2])))
            paid = round(amount * (0.68 if partial_month else 1.0), 2)
            if pay_date <= cutoff:
                add_event(
                    pay_date,
                    "bill",
                    paid,
                    category,
                    provider,
                    f"{name} payment",
                    bill_name=name,
                )
                if partial_month:
                    catch_up_date = pay_date + dt.timedelta(days=11)
                    add_event(
                        catch_up_date,
                        "bill",
                        round(amount - paid, 2),
                        category,
                        provider,
                        f"{name} remaining balance catch-up",
                        bill_name=name,
                    )
                if late and late_fee:
                    add_event(
                        pay_date,
                        "fee",
                        float(late_fee),
                        "Fees",
                        provider,
                        f"Historical late fee for {name}",
                    )
            settlement_date = pay_date + dt.timedelta(days=11) if partial_month else pay_date
            settled = settlement_date <= cutoff
            status = (
                "Upcoming"
                if due > cutoff
                else (
                    "Paid late (installments)"
                    if late and partial_month and settled
                    else (
                        "Paid late"
                        if late
                        else ("Partial" if partial_month and not settled else "Paid on time")
                    )
                )
            )
            bill_rows.append(
                {
                    "bill_id": f"H-{y}{m:02d}-{name.lower().replace(' ', '-')}",
                    "provider": provider,
                    "bill_name": name,
                    "category": category,
                    "original_amount": amount,
                    "due_date": due,
                    "payment_date": (settlement_date if settled else None),
                    "amount_paid": (amount if settled else (paid if pay_date <= cutoff else 0.0)),
                    "status": status,
                    "late_fee_paid": (float(late_fee) if late and pay_date <= cutoff else 0.0),
                    "minimum_payment": float(minimum),
                    "late_fee_terms": float(late_fee),
                    "interest_rate_apr": float(apr),
                    "grace_period_days": int(grace),
                    "consequence": consequence,
                    "modeled_consequence_weight": float(risk),
                    "risk_deadline_days": int(riskdays),
                    "partial_allowed": bool(partial),
                    "confirmed_arrangement": bool(late and name == "Credit Card Minimum"),
                    "extension_days": (5 if late and name == "Credit Card Minimum" else 0),
                    "extension_terms": (
                        "Synthetic five-day card payment arrangement"
                        if late and name == "Credit Card Minimum"
                        else ""
                    ),
                    "partial_payment": bool(partial_month),
                }
            )

    # Variable daily life: 18-25 ordinary purchases each full month; lower number for partial months.
    groceries = ["Jewel-Osco", "Aldi", "Trader Joe's", "Target Grocery"]
    fuel = ["Shell", "BP", "Costco Gas"]
    restaurants = ["Pita House", "Corner Cafe", "Taco Patio", "Lakeview Deli"]
    pharmacies = ["Walgreens", "CVS Pharmacy"]
    online = ["Amazon Marketplace", "Etsy", "Neighborhood Hardware"]
    for y, m in month_names:
        first = max(_date(y, m, 1), start)
        last = min(_date(y, m, calendar.monthrange(y, m)[1]), cutoff)
        if first > last:
            continue
        days = (last - first).days + 1
        # 12 grocery, 3 fuel, 5 meals, and occasional pharmacy/shopping purchases.
        n_grocery = max(3, round(12 * days / calendar.monthrange(y, m)[1]))
        for _ in range(n_grocery):
            day = rng.randint(first.day, last.day)
            amt = max(18, rng.gauss(68, 21))
            if (y, m) == (2025, 12):
                amt *= 1.28
            if (y, m) == (2026, 2):
                amt *= 1.12
            add_event(
                _date(y, m, day),
                "purchase",
                round(amt, 2),
                "Groceries",
                rng.choice(groceries),
                rng.choice(["Weekly groceries", "Household food", "Produce and pantry"]),
                card_probability=0.17,
            )
        for _ in range(max(1, round(3 * days / calendar.monthrange(y, m)[1]))):
            add_event(
                _date(y, m, rng.randint(first.day, last.day)),
                "purchase",
                round(max(20, rng.gauss(48, 12)), 2),
                "Transportation",
                rng.choice(fuel),
                "Fuel purchase",
                card_probability=0.1,
            )
        for _ in range(max(2, round(5 * days / calendar.monthrange(y, m)[1]))):
            add_event(
                _date(y, m, rng.randint(first.day, last.day)),
                "purchase",
                round(max(12, rng.gauss(31, 13)), 2),
                "Dining & Entertainment",
                rng.choice(restaurants),
                rng.choice(["Lunch", "Dinner", "Coffee and snack"]),
                card_probability=0.35,
            )
        for _ in range(max(1, round(2 * days / calendar.monthrange(y, m)[1]))):
            cat, merchant, amt = rng.choice(
                [
                    ("Medical", rng.choice(pharmacies), rng.uniform(12, 65)),
                    ("Shopping", rng.choice(online), rng.uniform(22, 125)),
                ]
            )
            add_event(
                _date(y, m, rng.randint(first.day, last.day)),
                "purchase",
                round(amt, 2),
                cat,
                merchant,
                "Pharmacy essentials" if cat == "Medical" else "Household purchase",
                card_probability=0.5,
            )

    # One-off events attached to the underlying ledger and reports.
    oneoffs = [
        (
            dt.date(2025, 5, 11),
            "Car repair",
            895.00,
            "Unexpected expense",
            "Northside Auto Repair",
            "Transmission and brake repair",
        ),
        (
            dt.date(2026, 2, 13),
            "Medical",
            487.35,
            "Unexpected expense",
            "Lakeview Clinic",
            "Unexpected medical copay and prescription",
        ),
        (
            dt.date(2025, 11, 9),
            "Shopping",
            276.20,
            "Unexpected expense",
            "Home & Field",
            "Winter coat and household essentials",
        ),
        (
            dt.date(2026, 9, 7),
            "Refund",
            86.40,
            "refund",
            "Jewel-Osco",
            "Returned duplicate grocery purchase",
        ),
    ]
    for date, category, amount, kind, merchant, desc in oneoffs:
        if start <= date <= cutoff:
            add_event(date, kind, amount, category, merchant, desc)

    # Reconcile checking cash; draw a recorded savings transfer before a check-account debit.
    events.sort(key=lambda e: (e["date"], 0 if e["kind"] == "income" else 1))
    checking, savings = opening["Checking"], opening["Savings"]
    txns: list[dict[str, Any]] = []
    tx_counter = 0

    def append_tx(
        date,
        merchant,
        amount,
        category,
        tx_type,
        method,
        desc,
        account,
        recurring=False,
    ):
        nonlocal tx_counter
        tx_counter += 1
        txns.append(
            {
                "transaction_id": f"TX-DEMO-{tx_counter:05d}",
                "date": pd.Timestamp(date),
                "merchant": merchant,
                "amount": round(float(amount), 2),
                "category": category,
                "transaction_type": tx_type,
                "payment_method": method,
                "description": desc,
                "recurrence": "Recurring" if recurring else "One-time",
                "account": account,
            }
        )

    def append_event(
        ev, amount, tx_type, method, account="Checking", recurring=False, category=None
    ):
        append_tx(
            ev["date"],
            ev["merchant"],
            amount,
            category or ev["category"],
            tx_type,
            method,
            ev["description"],
            account,
            recurring,
        )

    def append_transfer(date, checking_amount, description):
        for account, amount in (("Checking", checking_amount), ("Savings", -checking_amount)):
            append_tx(
                date,
                "Internal transfer",
                amount,
                "Transfers",
                "Transfer",
                "Savings transfer",
                description,
                account,
            )

    monthly_transfer_done: set[tuple[int, int]] = set()
    for ev in events:
        date, kind, amount = ev["date"], ev["kind"], float(ev["amount"])
        if kind == "income":
            checking += amount
            append_event(ev, amount, "Income", "Direct deposit", recurring=True)
        elif kind == "refund":
            checking += amount
            append_event(ev, amount, "Refund", "Debit card", category="Shopping")
        elif kind == "purchase" and rng.random() < ev.get("card_probability", 0):
            append_event(ev, -amount, "Purchase", "Credit card", "Credit Card")
        else:
            # All obligations and debit purchases are real checking debits. Use savings only when required.
            if checking - amount < 0 and savings > 25:
                needed = min(savings - 25, max(0.0, amount - checking + 75))
                if needed > 0:
                    checking += needed
                    savings -= needed
                    append_transfer(date, needed, "Emergency-fund transfer to checking")
            if checking - amount < -150:
                # If household cash is short, discretionary purchases roll to the card; obligations retain recorded partial status.
                if kind == "purchase":
                    append_event(ev, -amount, "Purchase", "Credit card", "Credit Card")
                    continue
                amount = max(0.0, checking + 150)
            checking -= amount
            recurring = kind in ("bill", "fee")
            tx_cat = "Transfers" if ev.get("bill_name") == "Credit Card Minimum" else ev["category"]
            append_event(
                ev,
                -amount,
                "Payment" if recurring else "Purchase",
                "Automatic payment" if recurring else "Debit card",
                recurring=recurring,
                category=tx_cat,
            )
            if ev.get("bill_name") == "Credit Card Minimum":
                append_tx(
                    date,
                    ev["merchant"],
                    amount,
                    "Transfers",
                    "Transfer",
                    "Card payment",
                    "Payment to credit card",
                    "Credit Card",
                    True,
                )
            # Small automated savings transfers, after end-of-month cash has recovered.
            if (
                date.day >= 27
                and (date.year, date.month) not in monthly_transfer_done
                and checking > 1650
                and savings < 9000
            ):
                sav_amt = min(230.0, checking - 1100, 9000 - savings)
                if sav_amt > 0:
                    monthly_transfer_done.add((date.year, date.month))
                    checking -= sav_amt
                    savings += sav_amt
                    append_transfer(date, -sav_amt, "Monthly emergency-fund contribution")

    transactions = pd.DataFrame(txns).sort_values("date").reset_index(drop=True)
    # Ensure about 800-1,200 records without padding with artificial duplicated rows; generated events are naturally around 950.
    # Materialize consistent account/debt month-end balances from the transaction ledger.
    balance_rows, debt_rows = [], []
    for y, m in month_names:
        month_end = min(_date(y, m, calendar.monthrange(y, m)[1]), cutoff)
        subset = transactions[transactions.date.dt.date <= month_end]
        cb = opening["Checking"] + subset.loc[subset.account == "Checking", "amount"].sum()
        sb = opening["Savings"] + subset.loc[subset.account == "Savings", "amount"].sum()
        card_tx = subset.loc[subset.account == "Credit Card", "amount"].sum()
        # Card ledger amounts are negative for purchases and positive for payments.
        cc = max(0.0, initial_debt["Credit Card"] - card_tx)
        # Loans accrue monthly interest and principal is paid through the documented recurring payment records.
        months_elapsed = max(0, (y - 2024) * 12 + m - 11)
        loans = {}
        for name, apr, paid_share in (("Auto Loan", 0.089, 0.76), ("Student Loan", 0.052, 0.88)):
            paid = (
                subset.loc[
                    subset.account.eq("Checking")
                    & subset.description.str.contains(f"{name} payment", case=False, na=False),
                    "amount",
                ]
                .abs()
                .sum()
            )
            loans[name] = max(
                0, initial_debt[name] * (1 + apr / 12) ** months_elapsed - paid * paid_share
            )
        auto, student = loans["Auto Loan"], loans["Student Loan"]
        balance_rows.append(
            {
                "month": pd.Timestamp(month_end),
                "checking": round(cb, 2),
                "savings": round(sb, 2),
                "total_cash": round(cb + sb, 2),
            }
        )
        debt_rows.append(
            {
                "month": pd.Timestamp(month_end),
                "Credit Card": round(cc, 2),
                "Auto Loan": round(auto, 2),
                "Student Loan": round(student, 2),
                "total_debt": round(cc + auto + student, 2),
            }
        )
    balance_history, debt_history = pd.DataFrame(balance_rows), pd.DataFrame(debt_rows)
    # Current obligations are for the remaining November window plus December rent.
    templates = {
        name: Bill(
            "",
            name,
            provider,
            category,
            float(base),
            _date(2026, 11, day),
            minimum,
            fee,
            apr,
            grace,
            consequence,
            risk,
            riskdays,
            partial_allowed=partial,
        )
        for name, provider, category, base, day, minimum, fee, apr, grace, consequence, risk, riskdays, partial in bill_specs
    }

    def current_bill(name, code, amount, consequence=None, due_date=None):
        template = templates[name]
        due = due_date or template.due_date
        return replace(
            template,
            bill_id=f"B-{code}-{due:%Y%m}",
            amount=amount,
            due_date=due,
            consequence=consequence or template.consequence,
        )

    current_specs = [
        current_bill(
            "Electricity", "ELEC", 148.6, "Possible service interruption; verify provider notice"
        ),
        current_bill("Credit Card Minimum", "CC", 126.0),
        current_bill(
            "Natural Gas", "GAS", 58.0, "Possible service interruption; confirm provider terms"
        ),
        current_bill("Internet", "NET", 74.0),
        current_bill("Mobile Phone", "PHONE", 67.0),
        current_bill("Auto Loan", "AUTO", 318.0),
        current_bill("Auto Insurance", "INS", 168.0, "Coverage lapse risk; confirm insurer terms"),
        current_bill("Student Loan", "STUDENT", 125.0, "Servicer terms vary; contact servicer"),
        current_bill("Streaming & Apps", "SUB", 19.99),
        current_bill(
            "Rent",
            "RENT",
            1425.0,
            "Housing stability risk; contact property manager",
            dt.date(2026, 12, 1),
        ),
    ]
    return {
        "transactions": transactions,
        "bill_history": pd.DataFrame(bill_rows),
        "income_history": pd.DataFrame(incomes),
        "balance_history": balance_history,
        "debt_history": debt_history,
        "bills": current_specs,
        "opening": opening,
    }


# -------------------------- demo_account / persistence ----------------------
class AccountStore:
    """The demo account: generated records plus any changes confirmed in the chat."""

    def __init__(self, records: dict[str, Any]):
        self.lock = threading.RLock()
        self.records = records
        # Expected next paycheck, used by "what if my paycheck is late?" answers.
        self.preferences = {
            "paycheck": 2200.0,
            "payday": dt.date(2026, 11, 20),
            "reserve": 1000.0,
        }

    @property
    def bills(self) -> list[Bill]:
        return self.records["bills"]

    @property
    def transactions(self) -> pd.DataFrame:
        return self.records["transactions"]

    def balance(self, account: str) -> float:
        with self.lock:
            return round(
                float(
                    self.records["opening"].get(account, 0)
                    + self.transactions.loc[self.transactions.account == account, "amount"].sum()
                ),
                2,
            )

    def debts(self) -> dict[str, float]:
        latest = self.records["debt_history"].iloc[-1]
        return {
            k: round(max(0.0, float(latest[k])), 2)
            for k in ("Credit Card", "Auto Loan", "Student Loan")
        }

    def adjust_debt(self, kind: str, delta: float):
        """Change the latest balance of one debt; ``delta`` is negative when principal is paid."""
        with self.lock:
            history = self.records["debt_history"]
            last = history.index[-1]
            history.loc[last, kind] = max(0.0, float(history.loc[last, kind]) + float(delta))
            history.loc[last, "total_debt"] = sum(
                float(history.loc[last, k]) for k in ("Credit Card", "Auto Loan", "Student Loan")
            )

    def add_transaction(
        self,
        amount: float,
        category: str,
        merchant: str,
        description: str,
        tx_type: str,
    ):
        """Record a confirmed checking-account entry dated on the snapshot day."""
        with self.lock:
            if not math.isfinite(float(amount)) or float(amount) == 0:
                raise ValueError("Enter a finite, non-zero amount")
            if self.balance("Checking") + float(amount) < -0.01:
                raise ValueError("Transaction would make checking negative")
            row = {
                "transaction_id": f"TX-{uuid.uuid4().hex[:10].upper()}",
                "date": pd.Timestamp(AS_OF),
                "merchant": merchant,
                "amount": round(float(amount), 2),
                "category": category,
                "transaction_type": tx_type,
                "payment_method": "Voice/text confirmed",
                "description": description,
                "recurrence": "One-time",
                "account": "Checking",
            }
            self.records["transactions"] = (
                pd.concat(
                    [self.records["transactions"], pd.DataFrame([row])],
                    ignore_index=True,
                )
                .sort_values("date")
                .reset_index(drop=True)
            )
            if category == "Income" and float(amount) > 0:
                income_row = {
                    "date": pd.Timestamp(AS_OF),
                    "amount": round(float(amount), 2),
                    "source": merchant,
                    "type": tx_type,
                    "scheduled_date": AS_OF,
                    "delayed": False,
                }
                self.records["income_history"] = pd.concat(
                    [self.records["income_history"], pd.DataFrame([income_row])],
                    ignore_index=True,
                )
            last = self.records["balance_history"].index[-1]
            checking, savings = self.balance("Checking"), self.balance("Savings")
            self.records["balance_history"].loc[last, "checking"] = checking
            self.records["balance_history"].loc[last, "savings"] = savings
            self.records["balance_history"].loc[last, "total_cash"] = checking + savings

    def record_bill_payment(self, bill: Bill, amount: float):
        """Add a payment to the bill history (used by the on-time payment score)."""
        with self.lock:
            row = {
                "bill_id": bill.bill_id,
                "provider": bill.provider,
                "bill_name": bill.name,
                "category": bill.category,
                "original_amount": round(float(bill.amount), 2),
                "due_date": bill.effective_due,
                "payment_date": AS_OF,
                "amount_paid": round(float(amount), 2),
                "status": "Paid" if bill.amount - amount < 0.01 else "Partial",
                "late_fee_paid": 0.0,
                "minimum_payment": bill.minimum_payment,
                "grace_period_days": bill.grace_days,
                "confirmed_arrangement": bill.confirmed_extension,
                "extension_days": (
                    (bill.extension_date - bill.due_date).days if bill.extension_date else 0
                ),
                "partial_payment": amount < bill.amount,
            }
            self.records["bill_history"] = pd.concat(
                [self.records["bill_history"], pd.DataFrame([row])], ignore_index=True
            )

    def find_bill(self, bill_id: str) -> Bill | None:
        return next((b for b in self.bills if b.bill_id == bill_id), None)

    def reset(self):
        """Throw away chat changes and regenerate the original demo data."""
        with self.lock:
            self.records = generate_demo_records()
            self.preferences = {
                "paycheck": 2200.0,
                "payday": dt.date(2026, 11, 20),
                "reserve": 1000.0,
            }


DEMO = AccountStore(generate_demo_records())


# ------------------------- financial_calculations ---------------------------


def monthly_summary(account: AccountStore) -> pd.DataFrame:
    tx = account.transactions.copy()
    tx["month"] = tx.date.dt.to_period("M").dt.to_timestamp()
    tx["income"] = np.where((tx.category == "Income") & (tx.amount > 0), tx.amount, 0.0)
    tx["expense"] = np.where(
        (tx.amount < 0) & (~tx.category.isin(["Transfers", "Income"])), -tx.amount, 0.0
    )
    return (
        tx.groupby("month", as_index=False)
        .agg(income=("income", "sum"), expenses=("expense", "sum"))
        .assign(net=lambda d: d.income - d.expenses)
    )


def category_spending(
    account: AccountStore, start: dt.date | None = None, end: dt.date = AS_OF
) -> pd.DataFrame:
    df = account.transactions.copy()
    mask = (df.amount < 0) & (~df.category.isin(["Transfers", "Income"])) & (df.date.dt.date <= end)
    if start:
        mask &= df.date.dt.date >= start
    out = (
        df[mask]
        .groupby("category", as_index=False)
        .amount.apply(lambda s: -s.sum())
        .rename(columns={"amount": "spending"})
    )
    return out.sort_values("spending", ascending=False).reset_index(drop=True)


def essential_monthly_expense(account: AccountStore) -> float:
    x = category_spending(account, AS_OF - dt.timedelta(days=180), AS_OF)
    essential = {
        "Housing",
        "Utilities",
        "Groceries",
        "Transportation",
        "Insurance",
        "Debt payments",
        "Medical",
    }
    return float(x[x.category.isin(essential)].spending.sum() / 6) if not x.empty else 0.0


def health_assessment(account: AccountStore) -> tuple[int, pd.DataFrame]:
    """0-100 score from seven weighted factors, plus the per-factor breakdown."""
    monthly = monthly_summary(account)
    # A half-finished current month is not evidence of an income collapse.
    monthly = monthly.loc[monthly.month.dt.date < AS_OF.replace(day=1)].tail(12)
    income = monthly.income.mean() if not monthly.empty else 0
    expense = monthly.expenses.mean() if not monthly.empty else 0
    positive = float((monthly.net > 0).mean()) if not monthly.empty else 0
    stability = (
        0 if income <= 0 else max(0, min(1, 1 - monthly.income.std(ddof=0) / max(income, 1)))
    )
    coverage = account.balance("Savings") / max(essential_monthly_expense(account), 1)
    emergency = min(1, coverage / 3)
    dti = sum(account.debts().values()) / max(income * 12, 1)
    dti_score = max(0, min(1, 1 - dti / 1.5))
    history = account.records["bill_history"].copy()
    history["due_key"] = pd.to_datetime(history.due_date).dt.date
    # Recording a payment appends an audit row, not a second bill. The latest
    # state of each provider/bill/due date is the one used for payment history.
    history = history.drop_duplicates(["provider", "bill_name", "due_key"], keep="last")
    completed = history.loc[~history.status.str.contains("upcoming|partial", case=False, na=False)]
    due = pd.to_datetime(completed.due_date)
    paid = pd.to_datetime(completed.payment_date)
    late = (
        completed.status.str.contains("late|overdue", case=False, na=False)
        | (paid > due)
        | (paid.isna() & (due.dt.date < AS_OF))
    ).sum()
    late_rate = late / max(1, len(completed))
    payment_score = max(0, 1 - late_rate * 6)
    hist = account.records["balance_history"].tail(6)
    saving_trend = (
        1.0
        if len(hist) < 2
        else max(
            0,
            min(
                1,
                0.5
                + (hist.savings.iloc[-1] - hist.savings.iloc[0]) / max(hist.savings.iloc[0] * 2, 1),
            ),
        )
    )
    cashflow = max(
        0,
        min(
            1,
            (positive + (max(-1, min(1, (income - expense) / max(income, 1))) + 1) / 2) / 2,
        ),
    )
    components = [
        ("Income stability", 0.20, stability),
        ("Positive cash-flow months", 0.10, positive),
        ("Income-to-expense balance", 0.10, cashflow),
        ("Emergency savings coverage", 0.20, emergency),
        ("Debt-to-income", 0.15, dti_score),
        ("Historical on-time payments", 0.10, payment_score),
        ("Savings trend", 0.15, saving_trend),
    ]
    detail = pd.DataFrame(
        [
            {
                "factor": n,
                "weight": w,
                "component_score_0_100": round(s * 100, 1),
                "weighted_points": round(s * w * 100, 1),
            }
            for n, w, s in components
        ]
    )
    score = round(detail.weighted_points.sum())
    return score, detail


def current_open_bills(account: AccountStore, within_days: int | None = None) -> list[Bill]:
    """Unpaid bills sorted by due date; optionally only those due within ``within_days`` days."""
    bills = sorted(
        (b for b in account.bills if b.status != "Paid"),
        key=lambda b: (b.effective_due, b.name),
    )
    if within_days is None:
        return bills
    return [b for b in bills if (b.effective_due - AS_OF).days <= within_days]


def scenario_from_account(account: AccountStore) -> Scenario:
    """Today's checking balance and open bills as an optimizer scenario (no cash held back)."""
    return Scenario(
        float(account.balance("Checking")),
        AS_OF,
        copy.deepcopy(current_open_bills(account)),
        [],
        0.0,
        40,
    )


# ------------------------- financial_optimizer ------------------------------
def _risk_date(b: Bill) -> dt.date:
    return b.effective_due + dt.timedelta(days=max(0, b.risk_after_days))


def _penalty_date(b: Bill) -> dt.date:
    return b.effective_due + dt.timedelta(days=max(0, b.grace_days))


def _payment_events(s: Scenario) -> list[dt.date]:
    dates = {s.as_of}
    for b in s.bills:
        dates.update(
            [
                max(s.as_of, b.effective_due),
                max(s.as_of, _penalty_date(b)),
                max(s.as_of, _risk_date(b)),
            ]
        )
    for i in s.incomes:
        if i.date >= s.as_of:
            dates.add(i.date)
    dates.add(s.as_of + dt.timedelta(days=s.horizon_days))
    return sorted(d for d in dates if d <= s.as_of + dt.timedelta(days=s.horizon_days))


def _available_by_date(s: Scenario, date: dt.date) -> float:
    return max(
        0.0,
        s.available_cash - max(0.0, s.reserve) + sum(i.amount for i in s.incomes if i.date <= date),
    )


def _benefit_per_dollar(bill: Bill, payment_date: dt.date, horizon: dt.date) -> float:
    """Estimate how much modeled harm one dollar of payment avoids at a given date."""
    amount = max(float(bill.amount), 0.01)
    fee_avoided = max(0.0, bill.late_fee / amount) if payment_date <= _penalty_date(bill) else 0.0
    # Paying sooner avoids only the future simple interest, not interest already accrued.
    interest_avoided = (
        max(0.0, bill.apr) * max(0, (horizon - max(payment_date, bill.effective_due)).days) / 365
    )
    consequence_avoided = (
        max(0.0, bill.critical_risk / amount) if payment_date <= _risk_date(bill) else 0.0
    )
    return fee_avoided + interest_avoided + consequence_avoided


def optimize(s: Scenario) -> PlanResult:
    """MILP allocation with cash-by-date constraints, minimums, and non-partial bill rules."""
    if not s.bills:
        return evaluate_plan(s, {})
    dates = _payment_events(s)
    n = len(s.bills)
    t = len(dates)
    horizon = s.as_of + dt.timedelta(days=s.horizon_days)
    # x(i,t) allocations, y_any, y_early, and per-date binaries for all-or-nothing bills.
    nx = n * t
    z_start = nx + 2 * n
    nv = z_start + nx
    c = np.zeros(nv)
    for i, b in enumerate(s.bills):
        for j, d in enumerate(dates):
            benefit = _benefit_per_dollar(b, d, horizon)
            c[i * t + j] = -benefit
    integrality = np.zeros(nv, dtype=int)
    integrality[nx:] = 1
    lower = np.zeros(nv)
    upper = np.full(nv, np.inf)
    upper[nx:] = 1
    for i, b in enumerate(s.bills):
        for j in range(t):
            upper[i * t + j] = max(0, float(b.amount))
            upper[z_start + i * t + j] = 1 if not b.partial_allowed else 0
    rows = []
    lows = []
    highs = []
    # Cash cannot be spent before it exists; reserve is protected, income is only available on/after arrival.
    for j, d in enumerate(dates):
        row = np.zeros(nv)
        for i in range(n):
            for k in range(j + 1):
                row[i * t + k] = 1
        rows.append(row)
        lows.append(-np.inf)
        highs.append(_available_by_date(s, d))
    # Total amount, applicable minimum by due date, and all-or-nothing rules.
    for i, b in enumerate(s.bills):
        y_any = nx + i
        y_early = nx + n + i
        row = np.zeros(nv)
        row[i * t : (i + 1) * t] = 1
        row[y_any] = -max(0, float(b.amount))
        rows.append(row)
        lows.append(-np.inf)
        highs.append(0)
        minimum = min(max(0, float(b.minimum_payment)), max(0, float(b.amount)))
        row = np.zeros(nv)
        row[i * t : (i + 1) * t] = 1
        row[y_any] = -minimum
        rows.append(row)
        lows.append(0)
        highs.append(np.inf)
        if minimum > 0:
            early_idx = [j for j, d in enumerate(dates) if d <= b.effective_due]
            row = np.zeros(nv)
            for j in early_idx:
                row[i * t + j] = 1
            row[y_early] = -max(0, float(b.amount))
            rows.append(row)
            lows.append(-np.inf)
            highs.append(0)
            row = np.zeros(nv)
            for j in early_idx:
                row[i * t + j] = 1
            row[y_early] = -minimum
            rows.append(row)
            lows.append(0)
            highs.append(np.inf)
            row = np.zeros(nv)
            row[y_early] = 1
            row[y_any] = -1
            rows.append(row)
            lows.append(-np.inf)
            highs.append(0)
        if not b.partial_allowed:
            row = np.zeros(nv)
            row[i * t : (i + 1) * t] = 1
            row[y_any] = -max(0, float(b.amount))
            rows.append(row)
            lows.append(0)
            highs.append(0)
            # A bill that disallows partial payments must be paid in one full transaction/date.
            for j in range(t):
                row = np.zeros(nv)
                row[i * t + j] = 1
                row[z_start + i * t + j] = -max(0, float(b.amount))
                rows.append(row)
                lows.append(-np.inf)
                highs.append(0)
            row = np.zeros(nv)
            for j in range(t):
                row[z_start + i * t + j] = 1
            row[y_any] = -1
            rows.append(row)
            lows.append(-np.inf)
            highs.append(0)
    mat = lil_matrix((len(rows), nv), dtype=float)
    for r, row in enumerate(rows):
        mat[r, :] = row
    res = milp(
        c,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(mat.tocsr(), np.array(lows), np.array(highs)),
        options={"time_limit": 8},
    )
    if res.x is None:
        # Safe fallback: allocate nothing rather than risk exceeding available cash.
        return evaluate_plan(s, {})
    # Lexicographic second pass: at the best modeled harm, cover as much of the
    # remaining bills as possible. A zero-fee subscription must not be left
    # unpaid merely because the first objective is indifferent to it.
    secondary = np.zeros(nv)
    for i in range(n):
        for j, d in enumerate(dates):
            secondary[i * t + j] = -1 + 1e-5 * (d - s.as_of).days
    covered = milp(
        secondary,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=[
            LinearConstraint(mat.tocsr(), np.array(lows), np.array(highs)),
            LinearConstraint(c.reshape(1, -1), -np.inf, float(c @ res.x) + 1e-7),
        ],
        options={"time_limit": 4},
    )
    if covered.x is not None:
        res = covered
    payments = {}
    for i, b in enumerate(s.bills):
        for j, d in enumerate(dates):
            amount = float(res.x[i * t + j])
            if amount > 0.005:
                payments.setdefault(b.bill_id, []).append((d, amount))
    return evaluate_plan(s, payments)


def evaluate_plan(s: Scenario, allocations: dict[str, list[tuple[dt.date, float]]]) -> PlanResult:
    """Total the modeled late fees, interest and consequence risk for a set of dated payments."""
    late_total = interest_total = risk_total = unpaid_total = 0.0
    all_pay = []
    horizon = s.as_of + dt.timedelta(days=s.horizon_days)
    for b in s.bills:
        p = sorted(allocations.get(b.bill_id, []), key=lambda x: x[0])
        paid = min(float(b.amount), sum(max(0, a) for _, a in p))
        unpaid_total += max(0, float(b.amount) - paid)
        by_penalty = sum(a for d, a in p if d <= _penalty_date(b))
        late_total += max(0, b.late_fee) * (max(0, b.amount - by_penalty) / max(b.amount, 0.01))
        # Simple APR daily accrual on unpaid principal from effective due until payment/horizon; not a lender quote.
        cursor = max(b.effective_due, s.as_of)
        bal = float(b.amount)
        for d, a in p:
            if d <= cursor:
                bal = max(0, bal - a)
                continue
            interest_total += bal * max(0, b.apr) * max(0, (min(d, horizon) - cursor).days) / 365
            bal = max(0, bal - a)
            cursor = min(d, horizon)
        interest_total += bal * max(0, b.apr) * max(0, (horizon - cursor).days) / 365
        unpaid_at_risk = max(0, b.amount - sum(a for d, a in p if d <= _risk_date(b)))
        risk_total += max(0, b.critical_risk) * unpaid_at_risk / max(b.amount, 0.01)
        if paid > 0:
            all_pay.extend(
                {"bill_id": b.bill_id, "bill": b.name, "date": d, "amount": round(a, 2)}
                for d, a in p
            )
    return PlanResult(
        all_pay,
        {
            "late_fees": round(late_total, 2),
            "interest": round(interest_total, 2),
            "critical_harm": round(risk_total, 2),
            "total_harm": round(late_total + interest_total + risk_total, 2),
        },
        round(sum(x["amount"] for x in all_pay), 2),
        round(unpaid_total, 2),
    )


# -------------------------- what_if_scenarios ------------------------------
def simulate_delay(s: Scenario, bill_id: str, days: int) -> PlanResult:
    """Re-run the optimizer as if one bill were due ``days`` later (a what-if, not a real extension)."""
    changed = copy.deepcopy(s)
    for b in changed.bills:
        if b.bill_id == bill_id:
            b.confirmed_extension = True
            b.extension_date = b.effective_due + dt.timedelta(days=int(days))
    return optimize(changed)


def simulate_late_payment(bill: Bill, days_late: int) -> PlanResult:
    """Estimated fees, interest and risk if this one bill were paid ``days_late`` days after it's due."""
    late_date = bill.effective_due + dt.timedelta(days=max(0, int(days_late)))
    horizon = max(40, (late_date - AS_OF).days + 14)
    s = Scenario(max(0, bill.amount), AS_OF, [copy.deepcopy(bill)], [], 0, horizon)
    return evaluate_plan(s, {bill.bill_id: [(late_date, bill.amount)]})


# --------------------------- natural_language -------------------------------
def _last_month_bounds() -> tuple[dt.date, dt.date]:
    """First and last day of the month before the snapshot date."""
    first = AS_OF.replace(day=1)
    last_prev = first - dt.timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def _spoken_date(value) -> str:
    """'2026-11-16' -> 'Nov 16' (adds the year only when it differs from the snapshot year)."""
    if isinstance(value, str):
        try:
            value = dt.date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, dt.datetime):
        value = value.date()
    label = f"{value:%b} {value.day}"
    return label if value.year == AS_OF.year else f"{label}, {value.year}"


def _join_words(items: list[str]) -> str:
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


_BILL_ALIASES = {
    "electric": "Electricity",
    "power": "Electricity",
    "light bill": "Electricity",
    "gas bill": "Natural Gas",
    "wifi": "Internet",
    "wi-fi": "Internet",
    "phone": "Mobile Phone",
    "cell": "Mobile Phone",
    "car payment": "Auto Loan",
    "car loan": "Auto Loan",
    "car insurance": "Auto Insurance",
    "insurance": "Auto Insurance",
    "credit card": "Credit Card Minimum",
    "student": "Student Loan",
    "streaming": "Streaming & Apps",
    "subscription": "Streaming & Apps",
    "netflix": "Streaming & Apps",
    "rent": "Rent",
}


def _find_bill_in_text(low: str, account: AccountStore) -> Bill | None:
    """Best-effort match of a bill mentioned in free text (name, provider, or common alias)."""
    bills = current_open_bills(account) + [b for b in account.bills if b.status == "Paid"]
    for b in bills:
        if b.name.lower() in low or b.provider.lower() in low:
            return b
    for alias, name in _BILL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            match = next((b for b in bills if b.name == name), None)
            if match:
                return match
    for b in bills:
        words = [w for w in re.findall(r"[a-z]+", b.name.lower()) if len(w) > 4]
        if any(re.search(rf"\b{w}\b", low) for w in words):
            return b
    return None


def answer_financial_question(
    question: str, account: AccountStore = DEMO, context: list | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Compatibility entry point for the account-grounded conversational engine."""
    from solvra_assistant import answer_question

    response = answer_question(question, account, context)
    return response["reply"], response.get("pending")


def confirm_account_update(
    pending: dict | None, approve: bool, account: AccountStore = DEMO
) -> str:
    """Validate a staged change and apply it atomically, only on explicit approval."""
    if not pending or not isinstance(pending, dict):
        return "No pending financial change to confirm."
    if not approve:
        return "Okay, I won't change anything."
    action = pending.get("action")
    if action not in {
        "income",
        "cash_reduction",
        "payment",
        "transaction",
        "extension",
        "paycheck_delay",
    }:
        return "Unsupported update; nothing changed."
    if action in {"income", "cash_reduction", "payment", "transaction"}:
        try:
            amount = float(pending.get("amount", 0))
        except (ValueError, TypeError):
            return "Invalid amount; nothing changed."
        if (
            not math.isfinite(amount)
            or not 0 < abs(amount) <= 1_000_000
            or (action != "transaction" and amount <= 0)
        ):
            return "Invalid amount; nothing changed."
    if action in {"extension", "paycheck_delay"}:
        try:
            if not 0 <= int(pending.get("days", 0)) <= 90:
                return "Choose a delay of 0 to 90 days; nothing changed."
        except (ValueError, TypeError):
            return "Invalid delay; nothing changed."
    with account.lock:
        if action == "transaction":
            if amount < 0 and -amount > account.balance("Checking"):
                return "Insufficient recorded checking balance; nothing changed."
            account.add_transaction(
                amount,
                str(pending.get("category", "Other expenses")),
                str(pending.get("merchant", "Manual entry")),
                str(pending.get("description", "Manual entry")),
                str(pending.get("type", "Purchase")),
            )
            return f"Done. I recorded the {money(abs(amount))} {'income' if amount > 0 else 'expense'}. Checking is now {money(account.balance('Checking'))}."
        try:
            return _apply_account_update(pending, True, account)
        except (KeyError, ValueError, TypeError):
            return "That change could not be recorded. Check its details and try again."


def _apply_account_update(pending: dict | None, approve: bool, account: AccountStore = DEMO) -> str:
    if not pending:
        return "No pending financial change to confirm."
    if not approve:
        return "Okay, I won't change anything."
    action = pending.get("action")
    if action == "income":
        account.add_transaction(
            pending["amount"],
            "Income",
            "User-reported income",
            pending["description"],
            tx_type="Income",
        )
        return f"Done. I added ${pending['amount']:,.2f} to checking. Your new balance is ${account.balance('Checking'):,.2f}."
    if action == "cash_reduction":
        amt = float(pending["amount"])
        if amt > account.balance("Checking"):
            return "Cannot record a reduction larger than the recorded checking balance. Nothing changed."
        account.add_transaction(
            -amt,
            "Other expenses",
            "Available cash adjustment",
            pending["description"],
            tx_type="Adjustment",
        )
        return f"Done. Checking is now ${account.balance('Checking'):,.2f}."
    if action == "paycheck_delay":
        old = pending.get("date")
        try:
            new = dt.date.fromisoformat(old) + dt.timedelta(days=int(pending.get("days", 5)))
        except Exception:
            new = AS_OF + dt.timedelta(days=int(pending.get("days", 5)))
        account.preferences["payday"] = new
        return f"Done. I moved your expected paycheck to {_spoken_date(new)}."
    if action == "extension":
        b = account.find_bill(pending["bill_id"])
        if b:
            b.confirmed_extension = True
            b.extension_date = b.due_date + dt.timedelta(days=int(pending["days"]))
            return f"Done. {b.name} is now due {_spoken_date(b.extension_date)}."
    if action == "payment":
        b = account.find_bill(pending["bill_id"])
        amt = min(float(pending["amount"]), b.amount if b else 0)
        if not b:
            return "Bill no longer exists; nothing changed."
        if amt > account.balance("Checking") + 0.01:
            return "Insufficient recorded checking balance; nothing changed. Update your balance first or record a smaller payment."
        account.add_transaction(
            -amt,
            "Transfers" if b.category == "Debt payments" else b.category,
            b.provider,
            f"Payment recorded for {b.name}",
            tx_type="Payment",
        )
        if b.name == "Credit Card Minimum":
            account.adjust_debt("Credit Card", -amt)
        elif b.name == "Auto Loan":
            account.adjust_debt("Auto Loan", -amt * 0.76)
        elif b.name == "Student Loan":
            account.adjust_debt("Student Loan", -amt * 0.88)
        account.record_bill_payment(b, amt)
        b.amount = round(b.amount - amt, 2)
        b.minimum_payment = round(max(0.0, b.minimum_payment - amt), 2)
        b.status = "Paid" if b.amount < 0.01 else "Partially paid"
        return f"Done. I recorded a ${amt:,.2f} payment for {b.name}. " + (
            "It's fully paid." if b.amount < 0.01 else f"${b.amount:,.2f} is still left on it."
        )
    return "Unsupported update; nothing changed."


# ----------------------------- voice ---------------------------------------
_YES_STARTERS = {
    "record",
    "yes",
    "yup",
    "sure",
    "confirm",
    "do",
    "ok",
    "absolutely",
    "correct",
    "thats",
    "confirmed",
    "yep",
    "save",
    "that's",
    "yeah",
    "go",
    "okay",
    "definitely",
}
_YES_WORDS = _YES_STARTERS | {
    "please",
    "you",
    "right",
    "solvra",
    "that",
    "good",
    "sounds",
    "is",
    "it",
    "thank",
    "ahead",
    "thanks",
}
_NO_STARTERS = {
    "never",
    "do",
    "wrong",
    "nevermind",
    "nope",
    "no",
    "dont",
    "stop",
    "don't",
    "cancel",
    "nah",
}
_NO_WORDS = _NO_STARTERS | {
    "thats",
    "please",
    "you",
    "not",
    "solvra",
    "mind",
    "that's",
    "it",
    "thank",
    "thanks",
}

_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "howdy",
    "good morning",
    "good afternoon",
    "good evening",
    "hey there",
    "hi there",
    "hello there",
    "yo",
}
_GOODBYES = {
    "bye",
    "goodbye",
    "good bye",
    "see you",
    "see ya",
    "that's all",
    "thats all",
    "that is all",
    "i'm done",
    "im done",
    "end chat",
    "stop listening",
    "end the chat",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def _short_reply_matches(text: str, vocab: set[str], starters: set[str]) -> bool:
    words = _words(text)
    return 0 < len(words) <= 6 and words[0] in starters and all(w in vocab for w in words)


def assistant_turn(
    text: str,
    pending: dict | None = None,
    last_question: str = "",
    account: AccountStore = DEMO,
) -> dict[str, Any]:
    """One grounded typed/voice turn. Network callers use server-owned session state."""
    from solvra_assistant import conversation_turn

    return conversation_turn(text, pending, last_question, account)


def transcribe_audio(path: str | None) -> str:
    """Transcribe offline without a network model download."""
    if not path:
        return ""
    from solvra_voice import transcribe

    try:
        return transcribe(path)
    except Exception as exc:
        return f"[Transcription unavailable: {exc}]"


def money(x: float) -> str:
    return f"${float(x):,.2f}"


def account_panel_html(account: AccountStore = DEMO) -> str:
    """Small escaped snapshot retained for ledger integrations."""
    bills = "".join(
        f"<li>{html.escape(b.name)} · {money(b.amount)}</li>" for b in current_open_bills(account)
    )
    return f"<section><h3>Your money</h3><p>Checking {money(account.balance('Checking'))} · Savings {money(account.balance('Savings'))}</p><ul>{bills}</ul></section>"


def transcribe_clip(payload: Any) -> dict[str, Any]:
    """Only read bounded audio files from Gradio's upload directory."""
    from solvra_voice import ALLOWED_SUFFIXES, MAX_BYTES, capabilities

    path = payload.get("path") if isinstance(payload, dict) else payload
    if not path:
        return {"text": "", "error": "Choose or record an audio clip first."}
    try:
        from gradio.utils import get_upload_folder

        allowed = Path(get_upload_folder()).resolve()
        resolved = Path(str(path)).resolve()
        if allowed not in resolved.parents or not resolved.is_file():
            return {
                "text": "",
                "error": "That recording could not be found. Please try again.",
            }
        if (
            resolved.suffix.lower() not in ALLOWED_SUFFIXES
            or not 0 < resolved.stat().st_size <= MAX_BYTES
        ):
            return {
                "text": "",
                "error": "Choose a supported audio file smaller than 15 MB.",
            }
        text = transcribe_audio(str(resolved))
        if text.startswith("[Transcription unavailable"):
            return {
                "text": "",
                "error": text.removeprefix("[Transcription unavailable: ").removesuffix("]"),
            }
        return {
            "text": text,
            "error": "",
            "engine": capabilities()["engine"],
            "review_required": True,
        }
    except Exception:
        return {
            "text": "",
            "error": "That recording could not be read. Record again or use the text box.",
        }


def live_turn(payload: Any) -> dict[str, Any]:
    from solvra_workspace import chat_turn

    return chat_turn(payload)


def transaction_table(account: AccountStore = DEMO) -> pd.DataFrame:
    """Return a clean, editable transaction view."""
    cols = [
        "transaction_id",
        "date",
        "merchant",
        "amount",
        "category",
        "transaction_type",
        "description",
        "account",
    ]
    return account.transactions.reindex(columns=cols).copy()


def save_transaction_table(data: Any) -> tuple[pd.DataFrame, str, str]:
    """Persist edits from the grid while preserving ledger safety and schema."""
    try:
        edited = pd.DataFrame(data).copy()
        current = DEMO.transactions.copy()
        required = [
            "transaction_id",
            "date",
            "merchant",
            "amount",
            "category",
            "transaction_type",
            "description",
            "account",
        ]
        if any(c not in edited.columns for c in required):
            raise ValueError("The table columns are incomplete; refresh and try again.")
        edited["amount"] = pd.to_numeric(edited["amount"], errors="raise").round(2)
        if not np.isfinite(edited["amount"].to_numpy(dtype=float)).all():
            raise ValueError("Amounts must be finite numbers.")
        edited["date"] = pd.to_datetime(edited["date"], errors="raise")
        if edited[required[2:]].isna().any().any():
            raise ValueError(
                "Merchant, category, transaction type, description, and account are required."
            )
        known_accounts = set(current["account"].dropna().astype(str)) | set(
            DEMO.records["opening"].keys()
        )
        if not set(edited["account"].astype(str)).issubset(known_accounts):
            raise ValueError("Choose a recognized account from the ledger.")
        if edited["transaction_id"].duplicated().any() or set(edited.transaction_id) != set(
            current.transaction_id
        ):
            raise ValueError(
                "Transaction IDs cannot be added or removed in the editor. Use Add transaction for new entries."
            )
        edited = edited.set_index("transaction_id")
        current = current.set_index("transaction_id")
        for txid, row in edited.iterrows():
            current.loc[txid, required[1:]] = row[required[1:]].values
        current = current.reset_index()
        for account_name, opening_balance in DEMO.records["opening"].items():
            ending_balance = float(opening_balance) + float(
                current.loc[current.account == account_name, "amount"].sum()
            )
            if ending_balance < -0.01:
                raise ValueError(f"These edits would make {account_name.lower()} negative.")
        DEMO.records["transactions"] = current.sort_values("date").reset_index(drop=True)
        return transaction_table(), "Changes saved.", account_panel_html(DEMO)
    except Exception as exc:
        return (
            transaction_table(),
            f"Could not save changes: {exc}",
            account_panel_html(DEMO),
        )


def add_manual_transaction(
    amount: float, category: str, merchant: str, description: str, tx_type: str
):
    try:
        amount = float(amount)
        if not merchant or not category or not tx_type or amount == 0:
            raise ValueError("Enter a non-zero amount, merchant, category, and type.")
        DEMO.add_transaction(amount, category, merchant, description or "Manually entered", tx_type)
        return transaction_table(), "Transaction added.", account_panel_html(DEMO)
    except Exception as exc:
        return (
            transaction_table(),
            f"Could not add transaction: {exc}",
            account_panel_html(DEMO),
        )


# ----------------------------- workspace interface --------------------------
ASSET_DIR = Path(__file__).resolve().parent / "web"


def light_only_theme():
    import gradio as gr

    theme = gr.themes.Base(primary_hue="orange", neutral_hue="stone", radius_size="lg")
    for name in list(vars(theme)):
        if name.endswith("_dark") and hasattr(theme, name[:-5]):
            setattr(theme, name, getattr(theme, name[:-5]))
    return theme


def launch_app():
    """A custom, accessible workspace; Gradio supplies transport and Colab sharing."""
    import gradio as gr

    from solvra_workspace import workspace_action

    with gr.Blocks(
        title="Solvra — your money, in focus",
        analytics_enabled=False,
        delete_cache=(300, 300),
    ) as app:
        gr.HTML(
            (ASSET_DIR / "index.html").read_text(),
            js_on_load=(
                "function loadPuterSDK() { if (!globalThis.puter) {\n"
                "globalThis.puter_socket_enabled = false;\n"
                + (ASSET_DIR / "vendor" / "puter-2.6.5.js").read_text()
                + "\n} return globalThis.puter; }\n"
                + "\n".join(
                    (ASSET_DIR / name).read_text()
                    for name in ("app.js", "ai.js", "speech.js", "voice.js")
                )
            ),
            server_functions=[live_turn, transcribe_clip, workspace_action],
            apply_default_css=False,
            elem_id="sv-workspace",
            padding=False,
        )
    return app


def launch_options() -> dict[str, Any]:
    import base64

    font = base64.b64encode((ASSET_DIR / "dm-sans-latin.woff2").read_bytes()).decode()
    font_css = (
        "@font-face{font-family:'DM Sans';font-style:normal;font-weight:100 1000;font-display:swap;src:url(data:font/woff2;base64,"
        + font
        + ") format('woff2');}"
    )
    return {
        "theme": light_only_theme(),
        "css": font_css + (ASSET_DIR / "styles.css").read_text(),
        "js": "() => { document.documentElement.classList.remove('dark'); document.body.classList.remove('dark'); }",
    }


def configured_server_port() -> int | None:
    """Return an explicitly requested port, or let Gradio find an available one.

    Passing ``7860`` ourselves restricted Gradio to that single port.  Passing
    ``None`` preserves Gradio's normal fallback range when the default port is
    occupied, which is especially useful in reused Colab and notebook runtimes.
    Set ``GRADIO_SERVER_PORT`` only when a particular port is required; leave
    it unset for automatic selection.
    """
    value = os.environ.get("GRADIO_SERVER_PORT", "").strip()
    if not value:
        return None

    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(
            "GRADIO_SERVER_PORT must be a number from 1 to 65535; leave it unset "
            "to select an available port automatically."
        ) from exc

    if not 1 <= port <= 65535:
        raise ValueError("GRADIO_SERVER_PORT must be a number from 1 to 65535.")
    return port


# ---------------------------- application launch ----------------------------
def main():
    """Start the workspace; Colab also prints a public HTTPS share link."""
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    app = launch_app()
    app.launch(
        share="google.colab" in sys.modules,
        server_name="0.0.0.0",
        server_port=configured_server_port(),
        show_error=True,
        max_file_size=15 * 1024 * 1024,
        height=1000,
        footer_links=[],
        **launch_options(),
    )


if __name__ == "__main__":
    main()
