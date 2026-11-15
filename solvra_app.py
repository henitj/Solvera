# Solvra — a voice money assistant for a fictional household account.
# Tap "Speak live", ask out loud, hear the answer. Runs locally or in Google Colab; no paid APIs.
import calendar
import copy
import datetime as dt
import html
import os
import random
import re
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

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
    critical_risk: float = (
        0.0  # transparent dollar-equivalent model weight, not a real-world loss estimate
    )
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
    harm: dict[str, float]  # late_fees, interest, critical_harm, total_harm (modeled $)
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
                paydate + dt.timedelta(days=4)
                if (y, m, day) == (2026, 10, 20)
                else paydate
            )
            if actual_date <= cutoff:
                events.append(
                    {
                        "date": actual_date,
                        "kind": "income",
                        "amount": amt,
                        "category": "Income",
                        "merchant": "Lakeshore Design Studio",
                        "description": "Net semi-monthly paycheck",
                    }
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
                events.append(
                    {
                        "date": bonus_date,
                        "kind": "income",
                        "amount": bonus,
                        "category": "Income",
                        "merchant": "Lakeshore Design Studio",
                        "description": "Occasional overtime",
                    }
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
            pay_date = due + dt.timedelta(
                days=(8 if late else rng.choice([0, 0, 1, 2]))
            )
            paid = round(amount * (0.68 if partial_month else 1.0), 2)
            if pay_date <= cutoff:
                events.append(
                    {
                        "date": pay_date,
                        "kind": "bill",
                        "amount": paid,
                        "category": category,
                        "merchant": provider,
                        "description": f"{name} payment",
                        "bill_name": name,
                    }
                )
                if partial_month:
                    catch_up_date = pay_date + dt.timedelta(days=11)
                    events.append(
                        {
                            "date": catch_up_date,
                            "kind": "bill",
                            "amount": round(amount - paid, 2),
                            "category": category,
                            "merchant": provider,
                            "description": f"{name} remaining balance catch-up",
                            "bill_name": name,
                        }
                    )
                if late and late_fee:
                    events.append(
                        {
                            "date": pay_date,
                            "kind": "fee",
                            "amount": float(late_fee),
                            "category": "Fees",
                            "merchant": provider,
                            "description": f"Historical late fee for {name}",
                        }
                    )
            settlement_date = (
                pay_date + dt.timedelta(days=11) if partial_month else pay_date
            )
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
                        else (
                            "Partial"
                            if partial_month and not settled
                            else "Paid on time"
                        )
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
                    "amount_paid": (
                        amount if settled else (paid if pay_date <= cutoff else 0.0)
                    ),
                    "status": status,
                    "late_fee_paid": (
                        float(late_fee) if late and pay_date <= cutoff else 0.0
                    ),
                    "minimum_payment": float(minimum),
                    "late_fee_terms": float(late_fee),
                    "interest_rate_apr": float(apr),
                    "grace_period_days": int(grace),
                    "consequence": consequence,
                    "modeled_consequence_weight": float(risk),
                    "risk_deadline_days": int(riskdays),
                    "partial_allowed": bool(partial),
                    "confirmed_arrangement": bool(
                        late and name == "Credit Card Minimum"
                    ),
                    "extension_days": (
                        5 if late and name == "Credit Card Minimum" else 0
                    ),
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
            events.append(
                {
                    "date": _date(y, m, day),
                    "kind": "purchase",
                    "amount": round(amt, 2),
                    "category": "Groceries",
                    "merchant": rng.choice(groceries),
                    "description": rng.choice(
                        ["Weekly groceries", "Household food", "Produce and pantry"]
                    ),
                    "card_probability": 0.17,
                }
            )
        for _ in range(max(1, round(3 * days / calendar.monthrange(y, m)[1]))):
            events.append(
                {
                    "date": _date(y, m, rng.randint(first.day, last.day)),
                    "kind": "purchase",
                    "amount": round(max(20, rng.gauss(48, 12)), 2),
                    "category": "Transportation",
                    "merchant": rng.choice(fuel),
                    "description": "Fuel purchase",
                    "card_probability": 0.1,
                }
            )
        for _ in range(max(2, round(5 * days / calendar.monthrange(y, m)[1]))):
            events.append(
                {
                    "date": _date(y, m, rng.randint(first.day, last.day)),
                    "kind": "purchase",
                    "amount": round(max(12, rng.gauss(31, 13)), 2),
                    "category": "Dining & Entertainment",
                    "merchant": rng.choice(restaurants),
                    "description": rng.choice(["Lunch", "Dinner", "Coffee and snack"]),
                    "card_probability": 0.35,
                }
            )
        for _ in range(max(1, round(2 * days / calendar.monthrange(y, m)[1]))):
            cat, merchant, amt = rng.choice(
                [
                    ("Medical", rng.choice(pharmacies), rng.uniform(12, 65)),
                    ("Shopping", rng.choice(online), rng.uniform(22, 125)),
                ]
            )
            events.append(
                {
                    "date": _date(y, m, rng.randint(first.day, last.day)),
                    "kind": "purchase",
                    "amount": round(amt, 2),
                    "category": cat,
                    "merchant": merchant,
                    "description": (
                        "Pharmacy essentials"
                        if cat == "Medical"
                        else "Household purchase"
                    ),
                    "card_probability": 0.5,
                }
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
            events.append(
                {
                    "date": date,
                    "kind": kind,
                    "amount": amount,
                    "category": category,
                    "merchant": merchant,
                    "description": desc,
                }
            )

    # Reconcile checking cash; draw a recorded savings transfer before a check-account debit.
    events.sort(key=lambda e: (e["date"], 0 if e["kind"] == "income" else 1))
    checking, savings = opening["Checking"], opening["Savings"]
    txns: list[dict[str, Any]] = []
    tx_counter = 0
    card_open = initial_debt["Credit Card"]
    card_balance = card_open
    loan_auto, loan_student = initial_debt["Auto Loan"], initial_debt["Student Loan"]

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

    monthly_transfer_done: set[tuple[int, int]] = set()
    for ev in events:
        date, kind, amount = ev["date"], ev["kind"], float(ev["amount"])
        if kind == "income":
            checking += amount
            append_tx(
                date,
                ev["merchant"],
                amount,
                "Income",
                "Income",
                "Direct deposit",
                ev["description"],
                "Checking",
                True,
            )
        elif kind == "refund":
            checking += amount
            append_tx(
                date,
                ev["merchant"],
                amount,
                "Shopping",
                "Refund",
                "Debit card",
                ev["description"],
                "Checking",
            )
        elif kind == "purchase" and rng.random() < ev.get("card_probability", 0):
            card_balance += amount
            append_tx(
                date,
                ev["merchant"],
                -amount,
                ev["category"],
                "Purchase",
                "Credit card",
                ev["description"],
                "Credit Card",
            )
        else:
            # All obligations and debit purchases are real checking debits. Use savings only when required.
            if checking - amount < 0 and savings > 25:
                needed = min(savings - 25, max(0.0, amount - checking + 75))
                if needed > 0:
                    checking += needed
                    savings -= needed
                    append_tx(
                        date,
                        "Internal transfer",
                        needed,
                        "Transfers",
                        "Transfer",
                        "Savings transfer",
                        "Emergency-fund transfer to checking",
                        "Checking",
                    )
                    append_tx(
                        date,
                        "Internal transfer",
                        -needed,
                        "Transfers",
                        "Transfer",
                        "Savings transfer",
                        "Emergency-fund transfer to checking",
                        "Savings",
                    )
            if checking - amount < -150:
                # If household cash is short, discretionary purchases roll to the card; obligations retain recorded partial status.
                if kind == "purchase":
                    card_balance += amount
                    append_tx(
                        date,
                        ev["merchant"],
                        -amount,
                        ev["category"],
                        "Purchase",
                        "Credit card",
                        ev["description"],
                        "Credit Card",
                    )
                    continue
                amount = max(0.0, checking + 150)
            checking -= amount
            recurring = kind in ("bill", "fee")
            tx_cat = (
                "Transfers"
                if ev.get("bill_name") == "Credit Card Minimum"
                else ev["category"]
            )
            append_tx(
                date,
                ev["merchant"],
                -amount,
                tx_cat,
                "Payment" if kind in ("bill", "fee") else "Purchase",
                "Automatic payment" if kind in ("bill", "fee") else "Debit card",
                ev["description"],
                "Checking",
                recurring,
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
                card_balance = max(0.0, card_balance - amount)
            if ev.get("bill_name") == "Auto Loan":
                loan_auto = max(
                    0.0, loan_auto - max(0.0, amount - loan_auto * 0.089 / 12)
                )
            if ev.get("bill_name") == "Student Loan":
                loan_student = max(
                    0.0, loan_student - max(0.0, amount - loan_student * 0.052 / 12)
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
                    append_tx(
                        date,
                        "Internal transfer",
                        -sav_amt,
                        "Transfers",
                        "Transfer",
                        "Savings transfer",
                        "Monthly emergency-fund contribution",
                        "Checking",
                    )
                    append_tx(
                        date,
                        "Internal transfer",
                        sav_amt,
                        "Transfers",
                        "Transfer",
                        "Savings transfer",
                        "Monthly emergency-fund contribution",
                        "Savings",
                    )

    transactions = pd.DataFrame(txns).sort_values("date").reset_index(drop=True)
    # Ensure about 800-1,200 records without padding with artificial duplicated rows; generated events are naturally around 950.
    # Materialize consistent account/debt month-end balances from the transaction ledger.
    balance_rows, debt_rows = [], []
    for y, m in month_names:
        month_end = min(_date(y, m, calendar.monthrange(y, m)[1]), cutoff)
        subset = transactions[transactions.date.dt.date <= month_end]
        cb = (
            opening["Checking"]
            + subset.loc[subset.account == "Checking", "amount"].sum()
        )
        sb = (
            opening["Savings"] + subset.loc[subset.account == "Savings", "amount"].sum()
        )
        card_tx = subset.loc[subset.account == "Credit Card", "amount"].sum()
        # Card ledger amounts are negative for purchases and positive for payments.
        cc = max(0.0, initial_debt["Credit Card"] - card_tx)
        # Loans accrue monthly interest and principal is paid through the documented recurring payment records.
        months_elapsed = max(0, (y - 2024) * 12 + m - 11)
        auto_paid = (
            subset[
                (subset.account == "Checking")
                & subset.description.str.contains(
                    "Auto Loan payment", case=False, na=False
                )
            ]
            .amount.abs()
            .sum()
        )
        student_paid = (
            subset[
                (subset.account == "Checking")
                & subset.description.str.contains(
                    "Student Loan payment", case=False, na=False
                )
            ]
            .amount.abs()
            .sum()
        )
        auto = max(
            0,
            initial_debt["Auto Loan"] * (1 + 0.089 / 12) ** months_elapsed
            - auto_paid * 0.76,
        )
        student = max(
            0,
            initial_debt["Student Loan"] * (1 + 0.052 / 12) ** months_elapsed
            - student_paid * 0.88,
        )
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
    current_specs = [
        Bill(
            "B-ELEC-202611",
            "Electricity",
            "ComEd",
            "Utilities",
            148.60,
            dt.date(2026, 11, 16),
            25,
            18,
            0.18,
            5,
            "Possible service interruption; verify provider notice",
            360,
            9,
            False,
            None,
            True,
        ),
        Bill(
            "B-CC-202611",
            "Credit Card Minimum",
            "Harbor Bank Card",
            "Debt payments",
            126.00,
            dt.date(2026, 11, 18),
            45,
            35,
            0.249,
            21,
            "Interest and credit reporting risk; issuer terms apply",
            220,
            35,
            False,
            None,
            True,
        ),
        Bill(
            "B-GAS-202611",
            "Natural Gas",
            "Peoples Gas",
            "Utilities",
            58.00,
            dt.date(2026, 11, 19),
            20,
            15,
            0.18,
            5,
            "Possible service interruption; confirm provider terms",
            260,
            12,
            False,
            None,
            True,
        ),
        Bill(
            "B-NET-202611",
            "Internet",
            "Astound Broadband",
            "Utilities",
            74.00,
            dt.date(2026, 11, 20),
            25,
            10,
            0.24,
            3,
            "Service may be restricted after provider notice",
            100,
            14,
            False,
            None,
            True,
        ),
        Bill(
            "B-PHONE-202611",
            "Mobile Phone",
            "T-Mobile",
            "Utilities",
            67.00,
            dt.date(2026, 11, 22),
            25,
            10,
            0.24,
            3,
            "Service may be interrupted after provider notice",
            180,
            12,
            False,
            None,
            True,
        ),
        Bill(
            "B-AUTO-202611",
            "Auto Loan",
            "Lakeview Credit Union",
            "Debt payments",
            318.00,
            dt.date(2026, 11, 23),
            318,
            28,
            0.089,
            10,
            "Credit and repossession risk depends on account and law",
            650,
            24,
            False,
            None,
            False,
        ),
        Bill(
            "B-INS-202611",
            "Auto Insurance",
            "Midwest Mutual",
            "Insurance",
            168.00,
            dt.date(2026, 11, 24),
            0,
            20,
            0,
            5,
            "Coverage lapse risk; confirm insurer terms",
            700,
            12,
            False,
            None,
            True,
        ),
        Bill(
            "B-STUDENT-202611",
            "Student Loan",
            "Federal Student Aid Servicer",
            "Debt payments",
            125.00,
            dt.date(2026, 11, 25),
            125,
            0,
            0.052,
            15,
            "Servicer terms vary; contact servicer",
            130,
            40,
            False,
            None,
            False,
        ),
        Bill(
            "B-SUB-202611",
            "Streaming & Apps",
            "Subscription Bundle",
            "Subscriptions",
            19.99,
            dt.date(2026, 11, 27),
            0,
            0,
            0,
            0,
            "Usually cancellable; service may stop",
            0,
            30,
            False,
            None,
            True,
        ),
        Bill(
            "B-RENT-202612",
            "Rent",
            "Northside Property Group",
            "Housing",
            1425.00,
            dt.date(2026, 12, 1),
            0,
            0,
            0,
            0,
            "Housing stability risk; contact property manager",
            1050,
            5,
            False,
            None,
            False,
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
        self.preferences = {"paycheck": 2200.0, "payday": dt.date(2026, 11, 20)}

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
                    + self.transactions.loc[
                        self.transactions.account == account, "amount"
                    ].sum()
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
                    (bill.extension_date - bill.due_date).days
                    if bill.extension_date
                    else 0
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
            self.__init__(generate_demo_records())


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
    mask = (
        (df.amount < 0)
        & (~df.category.isin(["Transfers", "Income"]))
        & (df.date.dt.date <= end)
    )
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
    return (
        float(x[x.category.isin(essential)].spending.sum() / 6) if not x.empty else 0.0
    )


def health_assessment(account: AccountStore) -> tuple[int, pd.DataFrame]:
    """0-100 score from seven weighted factors, plus the per-factor breakdown."""
    monthly = monthly_summary(account).tail(12)
    income = monthly.income.mean() if not monthly.empty else 0
    expense = monthly.expenses.mean() if not monthly.empty else 0
    positive = float((monthly.net > 0).mean()) if not monthly.empty else 0
    stability = (
        0
        if income <= 0
        else max(0, min(1, 1 - monthly.income.std(ddof=0) / max(income, 1)))
    )
    coverage = account.balance("Savings") / max(essential_monthly_expense(account), 1)
    emergency = min(1, coverage / 3)
    dti = sum(account.debts().values()) / max(income * 12, 1)
    dti_score = max(0, min(1, 1 - dti / 1.5))
    late = (
        account.records["bill_history"]
        .status.str.contains("late", case=False, na=False)
        .sum()
    )
    late_rate = late / max(1, len(account.records["bill_history"]))
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
                + (hist.savings.iloc[-1] - hist.savings.iloc[0])
                / max(hist.savings.iloc[0] * 2, 1),
            ),
        )
    )
    cashflow = max(
        0,
        min(
            1,
            (positive + (max(-1, min(1, (income - expense) / max(income, 1))) + 1) / 2)
            / 2,
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
        s.available_cash
        - max(0.0, s.reserve)
        + sum(i.amount for i in s.incomes if i.date <= date),
    )


def _benefit_per_dollar(bill: Bill, payment_date: dt.date, horizon: dt.date) -> float:
    """Estimate how much modeled harm one dollar of payment avoids at a given date."""
    amount = max(float(bill.amount), 0.01)
    fee_avoided = (
        max(0.0, bill.late_fee / amount) if payment_date <= _penalty_date(bill) else 0.0
    )
    # Paying sooner avoids only the future simple interest, not interest already accrued.
    interest_avoided = (
        max(0.0, bill.apr)
        * max(0, (horizon - max(payment_date, bill.effective_due)).days)
        / 365
    )
    consequence_avoided = (
        max(0.0, bill.critical_risk / amount)
        if payment_date <= _risk_date(bill)
        else 0.0
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
            # Deterministic tie-break: at equal harm, schedule the payment earlier, never changing meaningful dollar costs.
            c[i * t + j] = -benefit + 1e-7 * (d - s.as_of).days
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
    payments = {}
    for i, b in enumerate(s.bills):
        for j, d in enumerate(dates):
            amount = float(res.x[i * t + j])
            if amount > 0.005:
                payments.setdefault(b.bill_id, []).append((d, amount))
    return evaluate_plan(s, payments)


def evaluate_plan(
    s: Scenario, allocations: dict[str, list[tuple[dt.date, float]]]
) -> PlanResult:
    """Total the modeled late fees, interest and consequence risk for a set of dated payments."""
    late_total = interest_total = risk_total = unpaid_total = 0.0
    all_pay = []
    horizon = s.as_of + dt.timedelta(days=s.horizon_days)
    for b in s.bills:
        p = sorted(allocations.get(b.bill_id, []), key=lambda x: x[0])
        paid = min(float(b.amount), sum(max(0, a) for _, a in p))
        unpaid_total += max(0, float(b.amount) - paid)
        by_penalty = sum(a for d, a in p if d <= _penalty_date(b))
        late_total += max(0, b.late_fee) * (
            max(0, b.amount - by_penalty) / max(b.amount, 0.01)
        )
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
    bills = current_open_bills(account) or list(account.bills)
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
    q = (question or "").strip()
    low = q.lower()
    pending = None
    if not q:
        return (
            "Ask me about your balance, upcoming bills, spending, debt, or what to pay first.",
            None,
        )
    if (
        low in {"why?", "why", "explain that", "what about that?", "how so?"}
        and context
    ):
        previous = next(
            (
                x.get("content", "")
                for x in reversed(context)
                if x.get("role") == "user"
            ),
            "your previous question",
        )
        s = scenario_from_account(account)
        result = optimize(s)
        paid_ids = {p["bill_id"] for p in result.payments if p["amount"] > 0.005}
        ordered = sorted(
            (b for b in s.bills if b.bill_id in paid_ids),
            key=lambda b: (b.effective_due, -b.critical_risk),
        )
        if not ordered:
            return (
                f"About '{previous[:80]}': there isn't enough cash to pay any bill right now, so nothing is recommended yet.",
                None,
            )
        top = ordered[0]
        return (
            (
                f"About '{previous[:80]}': {top.name} comes first because it's due soonest, on {_spoken_date(top.effective_due)}, "
                f"and paying late risks this: {top.consequence.rstrip('.')}. "
                "I put bills in order by due date and by how much a late payment would cost you in fees, interest, or lost service."
            ),
            None,
        )
    # Recognize common updates; stage these for explicit confirmation, never mutate on interpretation alone.
    # A follow-up hypothetical applies a temporary income event without mutating the account.
    m = re.search(
        r"(?:receive|receiving|received)\s+(?:another\s+)?\$?([\d,]+(?:\.\d{1,2})?)\s+(?:tomorrow|in\s+1\s+day)",
        low,
    )
    if m and any(w in low for w in ["what if", "what happens", "if i"]):
        amount = float(m.group(1).replace(",", ""))
        s = scenario_from_account(account)
        s.incomes.append(
            IncomeEvent(
                amount, AS_OF + dt.timedelta(days=1), "What-if additional income", False
            )
        )
        r = optimize(s)
        return (
            f"With an extra ${amount:,.2f} tomorrow, the plan would pay ${r.total_allocated:,.2f} of your bills and leave ${r.unpaid:,.2f} unpaid, with about ${r.harm['total_harm']:,.2f} in estimated fees and interest. This is just a what-if, so nothing was recorded.",
            None,
        )
    if "paycheck" in low and any(w in low for w in ["delay", "delayed", "late"]):
        amount = float(account.preferences.get("paycheck") or 2200)
        payday = account.preferences.get("payday", dt.date(2026, 11, 20))
        if isinstance(payday, str):
            payday = dt.date.fromisoformat(payday)
        mday = re.search(r"(\d+)\s*days?", low)
        days = int(mday.group(1)) if mday else 5
        if any(w in low for w in ["what if", "what happens", "if my"]):
            s = scenario_from_account(account)
            s.incomes = [
                IncomeEvent(
                    amount,
                    payday + dt.timedelta(days=days),
                    "Delayed paycheck what-if",
                    False,
                )
            ]
            result = optimize(s)
            return (
                f"If your ${amount:,.2f} paycheck came {days} days late, on {_spoken_date(payday + dt.timedelta(days=days))}, the plan would still pay ${result.total_allocated:,.2f} of your bills and leave ${result.unpaid:,.2f} unpaid, with about ${result.harm['total_harm']:,.2f} in estimated fees and interest. This is just a what-if.",
                None,
            )
        pending = {"action": "paycheck_delay", "days": days, "date": payday.isoformat()}
        return (
            f"Should I move your expected paycheck from {_spoken_date(payday)} to {_spoken_date(payday+dt.timedelta(days=days))}, {days} days later? Confirm by saying yes, or say no to cancel.",
            pending,
        )
    m = re.search(
        r"(?:received|got|earned|deposited|made)\s+(?:paid\s+|a\s+|an\s+extra\s+|another\s+)?\$?([\d,]+(?:\.\d{1,2})?)",
        low,
    )
    if m and float(m.group(1).replace(",", "") or 0) > 0:
        amount = float(m.group(1).replace(",", ""))
        pending = {
            "action": "income",
            "amount": amount,
            "date": AS_OF.isoformat(),
            "description": "User-reported income",
        }
        return (
            f"Should I add a ${amount:,.2f} deposit to your checking account? Confirm by saying yes, or say no to cancel.",
            pending,
        )
    m = re.search(r"(?:now have|have)\s+\$?([\d,]+(?:\.\d{1,2})?)\s+less", low)
    if m:
        amount = float(m.group(1).replace(",", ""))
        pending = {
            "action": "cash_reduction",
            "amount": amount,
            "date": AS_OF.isoformat(),
            "description": "User-reported available-cash adjustment",
        }
        return (
            f"Should I lower your checking balance by ${amount:,.2f}? Confirm by saying yes, or say no to cancel.",
            pending,
        )
    if "extension" in low and any(
        x in low for x in ["approved", "extended", "five-day", "5-day", "5 day"]
    ):
        b = next(
            (
                b
                for b in account.bills
                if any(k in low for k in b.name.lower().split() if len(k) > 3)
                or b.provider.lower() in low
            ),
            None,
        )
        if b:
            md = re.search(r"(\d+)\s*[- ]?day", low)
            days = int(md.group(1)) if md else 5
            pending = {
                "action": "extension",
                "bill_id": b.bill_id,
                "days": days,
                "date": AS_OF.isoformat(),
            }
            return (
                f"Should I record a {days}-day extension for {b.name} from {b.provider}? Confirm by saying yes, or say no to cancel.",
                pending,
            )
    if "paid" in low:
        b = next(
            (
                b
                for b in account.bills
                if b.name.lower() in low
                or b.provider.lower() in low
                or any(k in low for k in b.name.lower().split() if len(k) > 4)
            ),
            None,
        )
        if b:
            amt = b.amount
            mm = re.search(
                r"paid\s+(?:my\s+)?(?:\w+\s+){0,3}\$?([\d,]+(?:\.\d{1,2})?)", low
            )
            if mm:
                amt = float(mm.group(1).replace(",", ""))
            pending = {
                "action": "payment",
                "bill_id": b.bill_id,
                "amount": amt,
                "date": AS_OF.isoformat(),
            }
            return (
                f"Should I record a ${amt:,.2f} payment toward {b.name}? Confirm by saying yes, or say no to cancel.",
                pending,
            )
    if any(
        w in low
        for w in [
            "how much money",
            "balance",
            "checking",
            "savings",
            "how much cash",
            "how much do i have",
        ]
    ) and not ("why" in low and "saving" in low):
        checking = account.balance("Checking")
        savings = account.balance("Savings")
        return (
            (
                f"You have ${checking:,.2f} in checking and ${savings:,.2f} in savings, "
                f"so ${checking + savings:,.2f} in total."
            ),
            None,
        )
    if "net worth" in low:
        cash = account.balance("Checking") + account.balance("Savings")
        debt = sum(account.debts().values())
        return (
            (
                f"Your cash is ${cash:,.2f} and your debt is about ${debt:,.2f}, "
                f"so your rough net worth is ${cash - debt:,.2f}. That doesn't count things like a car or other assets."
            ),
            None,
        )
    if any(
        w in low
        for w in [
            "due this week",
            "upcoming",
            "bills due",
            "due soon",
            "what's due",
            "what is due",
            "next bill",
            "coming up",
            "two weeks",
            "my bills",
            "what bills",
        ]
    ):
        horizon = (
            14
            if any(
                w in low
                for w in ["two weeks", "2 weeks", "upcoming", "coming up", "next bill", "my bills"]
            )
            else 7
        )
        window = current_open_bills(account, horizon)
        if not window:
            return (f"Nothing is due in the next {horizon} days.", None)
        items = [f"{b.name} ${b.amount:,.2f} on {_spoken_date(b.effective_due)}" for b in window]
        count = len(items)
        return (
            f"You have {count} bill{'s' if count != 1 else ''} due in the next {horizon} days: "
            + _join_words(items)
            + f". That's ${sum(b.amount for b in window):,.2f} in total.",
            None,
        )
    if any(
        w in low
        for w in [
            "priorit",
            "pay first",
            "what should i pay",
            "which bill",
            "which bills",
            "payment plan",
            "what to pay",
        ]
    ):
        s = scenario_from_account(account)
        result = optimize(s)
        paid = {}
        for p in result.payments:
            paid[p["bill_id"]] = paid.get(p["bill_id"], 0) + p["amount"]
        ordered = sorted(
            (b for b in s.bills if paid.get(b.bill_id, 0) > 0.005),
            key=lambda b: (b.effective_due, b.name),
        )
        if not ordered:
            return (
                (
                    "Right now there isn't enough cash in checking to cover any bill. "
                    "Consider calling providers about an extension or payment plan."
                ),
                None,
            )
        names = [
            f"{b.name} ${paid[b.bill_id]:,.2f} (due {_spoken_date(b.effective_due)})"
            for b in ordered[:6]
        ]
        reply = "Here's what I'd pay first, in order: " + _join_words(names)
        if len(ordered) > 6:
            reply += f", then {len(ordered) - 6} more"
        reply += f". That's ${result.total_allocated:,.2f} in total."
        skipped = [b for b in s.bills if paid.get(b.bill_id, 0) < b.amount - 0.005]
        if skipped:
            reply += " " + _join_words(
                [f"{b.name} (${b.amount - paid.get(b.bill_id, 0):,.2f})" for b in skipped]
            ) + (
                " can wait, since paying it late doesn't add a fee or major risk."
                if result.harm["total_harm"] < 0.01
                else " can't be fully covered right now."
            )
        if result.harm["total_harm"] >= 0.01:
            reply += f" Estimated fees and interest with this plan: ${result.harm['total_harm']:,.2f}."
        return reply, None
    if any(
        w in low
        for w in [
            "how am i doing",
            "how i'm doing",
            "health",
            "okay financially",
            "ok financially",
            "doing financially",
            "financial score",
            "my score",
            "am i okay",
            "am i ok",
        ]
    ):
        score, factors = health_assessment(account)
        months = account.balance("Savings") / max(essential_monthly_expense(account), 1)
        weakest = factors.sort_values("component_score_0_100").iloc[0]["factor"].lower()
        mood = (
            "You're in good shape"
            if score >= 75
            else ("You're doing okay" if score >= 55 else "Things are tight")
        )
        return (
            (
                f"{mood}: your financial health score is {score} out of 100. "
                f"Your savings would cover about {months:.1f} months of essential expenses. "
                f"The area with the most room to improve is {weakest}."
            ),
            None,
        )
    named_bill = _find_bill_in_text(low, account)
    if named_bill and not any(
        w in low for w in ["owe", "spend", "spent", "late", "delay", "what if", "extension"]
    ):
        days = (named_bill.effective_due - AS_OF).days
        when = (
            "today"
            if days == 0
            else (
                f"in {days} day{'s' if days != 1 else ''}"
                if days > 0
                else f"{-days} day{'s' if days != -1 else ''} ago"
            )
        )
        status = (
            "It's already paid."
            if named_bill.status == "Paid"
            else (
                f"The minimum payment is ${named_bill.minimum_payment:,.2f}."
                if named_bill.minimum_payment and named_bill.minimum_payment < named_bill.amount
                else ""
            )
        )
        return (
            f"Your {named_bill.name} bill from {named_bill.provider} is ${named_bill.amount:,.2f}, "
            f"due {_spoken_date(named_bill.effective_due)}, {when}. {status}".strip(),
            None,
        )
    if any(w in low for w in ["spend", "spent", "expenses", "grocery", "groceries"]):
        start, end = _last_month_bounds()
        tx = account.transactions
        mask = (
            (tx.date.dt.date >= start)
            & (tx.date.dt.date <= end)
            & (tx.amount < 0)
            & (~tx.category.isin(["Transfers", "Income"]))
        )
        subset = tx[mask]
        total = -subset.amount.sum()
        cats = (
            subset.groupby("category")
            .amount.sum()
            .abs()
            .sort_values(ascending=False)
            .head(3)
        )
        detail = _join_words([f"{k} (${v:,.0f})" for k, v in cats.items()])
        return (
            f"In {start:%B} you spent ${total:,.2f}."
            + (f" The biggest categories were {detail}." if detail else ""),
            None,
        )
    if any(w in low for w in ["debt", "owe", "loan"]):
        d = account.debts()
        return (
            f"You owe about ${sum(d.values()):,.0f} in total: "
            + _join_words([f"{k} ${v:,.0f}" for k, v in d.items()])
            + ".",
            None,
        )
    if "delay" in low or ("late" in low and "pay" in low):
        bill = next(
            (
                b
                for b in account.bills
                if b.name.lower() in low or b.provider.lower() in low
            ),
            None,
        )
        if bill is None and "electric" in low:
            bill = next((b for b in account.bills if b.name == "Electricity"), None)
        md = re.search(r"(\d+)\s*days?", low)
        delay = int(md.group(1)) if md else 5
        if bill and "late" in low and "pay" in low:
            late_result = simulate_late_payment(bill, delay)
            return (
                f"If you paid {bill.name} (${bill.amount:,.2f}) {delay} days after it's due on {_spoken_date(bill.effective_due)}, you'd pay about ${late_result.harm['late_fees']:,.2f} in late fees and ${late_result.harm['interest']:,.2f} in interest."
                + (
                    f" There's also a risk of this: {bill.consequence.rstrip('.')}."
                    if late_result.harm["critical_harm"] > 0
                    else ""
                )
                + f" Check {bill.provider}'s actual terms to be sure.",
                None,
            )
        if bill:
            s = scenario_from_account(account)
            r = simulate_delay(s, bill.bill_id, delay)
            return (
                f"If {bill.name} were pushed back {delay} days, estimated fees and interest across all your bills would be about ${r.harm['total_harm']:,.2f}, with ${r.unpaid:,.2f} left unpaid. This is just a what-if, not a confirmed extension.",
                None,
            )
    if any(w in low for w in ["paycheck", "income"]):
        upcoming = [
            r
            for r in account.records["income_history"].to_dict("records")
            if pd.Timestamp(r["date"]).date() <= AS_OF
        ]
        recent = sum(
            x["amount"]
            for x in upcoming
            if pd.Timestamp(x["date"]).date() >= AS_OF - dt.timedelta(days=30)
        )
        return (
            f"You've received ${recent:,.2f} in income over the last 30 days. Your next paycheck of about ${float(account.preferences.get('paycheck') or 0):,.2f} is expected around {_spoken_date(account.preferences.get('payday', AS_OF))}.",
            None,
        )
    if "why" in low and "saving" in low:
        h = account.records["balance_history"].tail(4)
        delta = float(h.savings.iloc[-1] - h.savings.iloc[0]) if len(h) > 1 else 0
        tx = account.transactions[
            account.transactions.date.dt.date >= AS_OF - dt.timedelta(days=90)
        ]
        transfers = tx[
            (tx.account == "Savings")
            & tx.description.str.contains("transfer", case=False)
        ].amount.sum()
        return (
            f"The last four monthly savings snapshots changed by ${delta:,.2f}. In the last 90 days, recorded transfers into savings netted ${transfers:,.2f}; irregular expenses, income timing, and withdrawals also affect the balance.",
            None,
        )
    return (
        (
            "Sorry, I'm not sure about that one. You can ask me things like: how much money do I have, "
            "what bills are due this week, what should I pay first, how much did I spend last month, "
            "or how much debt do I have."
        ),
        None,
    )


def confirm_account_update(
    pending: dict | None, approve: bool, account: AccountStore = DEMO
) -> str:
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
            new = dt.date.fromisoformat(old) + dt.timedelta(
                days=int(pending.get("days", 5))
            )
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
        b.status = "Paid" if b.amount < 0.01 else "Partially paid"
        return (
            f"Done. I recorded a ${amt:,.2f} payment for {b.name}. "
            + ("It's fully paid." if b.amount < 0.01 else f"${b.amount:,.2f} is still left on it.")
        )
    return "Unsupported update; nothing changed."


# ----------------------------- voice ---------------------------------------
_YES_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "correct", "right", "please", "do", "it", "go", "ahead", "record", "save",
    "that's", "thats", "that", "is", "sounds", "good", "absolutely", "definitely",
    "thanks", "thank", "you", "solvra",
}
_YES_STARTERS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
                 "correct", "absolutely", "definitely", "do", "go", "record", "save", "that's", "thats"}
_NO_WORDS = {
    "no", "nope", "nah", "cancel", "don't", "dont", "do", "not", "stop", "never", "mind",
    "nevermind", "wrong", "that's", "thats", "please", "thanks", "thank", "you", "it", "solvra",
}
_NO_STARTERS = {"no", "nope", "nah", "cancel", "don't", "dont", "do", "stop", "never", "nevermind", "wrong"}
_GREETINGS = {"hi", "hello", "hey", "hiya", "howdy", "good morning", "good afternoon", "good evening",
              "hey there", "hi there", "hello there", "yo"}
_GOODBYES = {"bye", "goodbye", "good bye", "see you", "see ya", "that's all", "thats all",
             "that is all", "i'm done", "im done", "end chat", "stop listening", "end the chat"}


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
    """One conversational turn for the live voice chat and the typed chat.

    Returns ``reply`` (display text), ``speech`` (text cleaned for text-to-speech),
    ``pending`` (an update waiting for a spoken/typed yes or no), ``changed``
    (True when the account was updated) and ``end`` (True when the user said goodbye).
    """
    q = re.sub(r"\s+", " ", (text or "")).strip()
    # Drop a leading wake phrase such as "Hey Solvra," so it doesn't confuse intent matching.
    q = re.sub(r"^(?:(?:hey|hi|okay|ok)\s+)?solvra[\s,.!?]*", "", q, flags=re.IGNORECASE).strip() or q
    low = q.lower().strip(" .!?")
    changed = False
    end = False
    new_pending = None

    if not low:
        reply = "Sorry, I didn't catch that. Could you say it again?"
        new_pending = pending
    elif pending and _short_reply_matches(low, _YES_WORDS, _YES_STARTERS) and not _short_reply_matches(
        low, _NO_WORDS, _NO_STARTERS
    ):
        reply = confirm_account_update(pending, True, account)
        changed = reply.startswith("Done")
    elif pending and _short_reply_matches(low, _NO_WORDS, _NO_STARTERS):
        reply = confirm_account_update(pending, False, account)
    elif low in _GREETINGS or (low.split(" ")[0] in {"hi", "hello", "hey"} and len(low.split()) <= 3):
        reply = (
            "Hi! I'm Solvra. Ask me about your balance, upcoming bills, spending, "
            "debt, or what to pay first."
        )
    elif low in _GOODBYES or low.startswith(("bye", "goodbye")):
        reply = "Goodbye! Come back any time."
        end = True
    elif re.fullmatch(r"(?:thanks|thank you|thank you so much|thanks a lot|cool|great|awesome|perfect|got it)(?: solvra)?", low):
        reply = "You're welcome! Anything else?"
    elif re.search(
        r"\b(what can you do|what can i ask|what do you do|help me|^help$|how does this work|who are you)\b",
        low,
    ):
        reply = (
            "I'm Solvra, your bill and budget helper. You can ask: how much money do I have, "
            "what bills are due this week, what should I pay first, how much did I spend last month, "
            "how much debt do I have, or what if I pay a bill late. You can also tell me things like "
            "'I got paid 500 dollars' and I'll update the account after you confirm."
        )
    else:
        context = [{"role": "user", "content": last_question}] if last_question else []
        reply, new_pending = answer_financial_question(q, account, context)
    return {
        "reply": reply,
        "speech": speech_text(reply),
        "pending": new_pending,
        "changed": changed,
        "end": end,
    }


def speech_text(text: str) -> str:
    """Make a reply sound natural when read aloud by the browser's speech synthesizer."""
    s = re.sub(r"[*_`#>|]", "", text or "")
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda m: _spoken_date(m.group(0)), s)

    def _money(m):
        value = float(m.group(1).replace(",", ""))
        if value >= 100:
            return f"${round(value):,}"
        return f"${value:,.2f}".replace(".00", "")

    s = re.sub(r"\$([\d,]+\.\d{2})", _money, s)
    s = s.replace("&", " and ").replace("—", ", ").replace(" / ", " or ")
    return re.sub(r"\s+", " ", s).strip()


def transcribe_audio(path: str | None) -> str:
    """Speech-to-text with Faster-Whisper; used when the browser has no built-in recognition."""
    if not path:
        return ""
    try:
        from faster_whisper import WhisperModel

        global _WHISPER_MODEL
        if "_WHISPER_MODEL" not in globals():
            _WHISPER_MODEL = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, _ = _WHISPER_MODEL.transcribe(
            path, beam_size=3, language="en", vad_filter=True
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        return f"[Transcription unavailable: {e}. Install faster-whisper and retry, or type your question.]"


# ----------------------------- gradio interface ----------------------------
# One page, no tabs: a live voice chat on the left and a simple account summary on the right.
# Live voice runs in the browser: speech recognition (Web Speech API) turns speech into text,
# Solvra answers on the server, and the browser reads the answer aloud. Browsers without
# built-in recognition (e.g. Firefox) record short clips that Faster-Whisper transcribes.


def money(x: float) -> str:
    return f"${float(x):,.2f}"


APP_CSS = """
:root, body, gradio-app, .gradio-container { color-scheme: light !important; }
body, gradio-app, .gradio-container, .main, .wrap.app {
  background: #eef3f5 !important;
}
.gradio-container {
  max-width: 1200px !important;
  width: 100% !important;
  margin: 0 auto !important;
  padding: clamp(10px, 2.2vw, 18px) clamp(8px, 2vw, 20px) 28px !important;
  color: #0f2433 !important;
  font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, ui-sans-serif, system-ui, sans-serif !important;
}
.gradio-container .html-container, .gradio-container .prose { color: #0f2433; }
.gradio-container .main.app, .gradio-container .main.fillable { padding: 0 !important; }
.gradio-container .html-container { padding: 0 !important; }
#sv-main { gap: 18px !important; align-items: stretch; }
#sv-main > .column { gap: 12px !important; }
#sv-reset button, button#sv-reset {
  background: #ffffff !important; color: #334155 !important; border: 1px solid #cbd5df !important;
  font-weight: 600 !important; box-shadow: none !important;
}
#sv-reset button:hover, button#sv-reset:hover { background: #f1f5f9 !important; }
footer { opacity: .85; }

/* ---------- header ---------- */
.sv-header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 18px 22px; border-radius: 18px;
  background: linear-gradient(115deg, #0f2a3f 0%, #134e5e 60%, #0f766e 100%);
  box-shadow: 0 10px 24px rgba(15, 42, 63, .18);
}
.sv-brand { display: flex; align-items: center; gap: 14px; }
.sv-logo {
  flex: 0 0 auto; width: 44px; height: 44px; border-radius: 13px; display: grid; place-items: center;
  background: rgba(255,255,255,.16); color: #ffffff; font-size: 22px; font-weight: 800;
}
.sv-header h1 { margin: 0 !important; color: #ffffff !important; font-size: 26px !important; line-height: 1.1 !important; font-weight: 800 !important; letter-spacing: -.02em; }
.sv-header p { margin: 3px 0 0 !important; color: #d6efea !important; font-size: 14px !important; }
.sv-badge {
  padding: 7px 12px; border-radius: 999px; border: 1px solid rgba(255,255,255,.3);
  background: rgba(255,255,255,.12); color: #ffffff; font-size: 12.5px; font-weight: 600; white-space: nowrap;
}

/* ---------- live voice card ---------- */
.sv-live {
  --lvl: 0;
  display: flex; flex-direction: column; gap: 12px;
  height: min(760px, calc(100vh - 190px)); min-height: 540px;
  padding: 18px; border-radius: 18px; background: #ffffff; border: 1px solid #d5dee5;
  box-shadow: 0 6px 18px rgba(15, 36, 51, .06); color: #0f2433; box-sizing: border-box;
}
.sv-stage { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px; padding: 6px 4px 10px; border-bottom: 1px solid #e5ecf1; }
.sv-orb {
  position: relative; width: 128px; height: 128px; margin: 4px 0 6px; border: 0; padding: 0;
  border-radius: 50%; cursor: pointer; background: transparent; outline-offset: 6px;
}
.sv-orb:focus-visible { outline: 3px solid #0f766e; }
.sv-live.has-chat .sv-stage { gap: 4px; padding-bottom: 8px; }
.sv-live.has-chat .sv-orb { width: 96px; height: 96px; margin: 0 0 2px; }
.sv-live.has-chat .sv-core svg { width: 32px; height: 32px; }
.sv-live.has-chat .sv-orb-label { font-size: 18px; }
.sv-core {
  position: absolute; inset: 14px; border-radius: 50%; display: grid; place-items: center; z-index: 2;
  background: radial-gradient(circle at 32% 28%, #5eead4 0%, #14b8a6 32%, #0f766e 70%, #134e5e 100%);
  box-shadow: 0 10px 26px rgba(15, 118, 110, .35), inset 0 -6px 14px rgba(0,0,0,.18);
  transition: transform .15s ease;
  transform: scale(calc(1 + var(--lvl) * .12));
}
.sv-core svg { width: 40px; height: 40px; fill: #ffffff; }
.sv-orb:hover .sv-core { filter: brightness(1.06); }
.sv-ring { position: absolute; inset: 14px; border-radius: 50%; border: 3px solid rgba(20, 184, 166, .45); opacity: 0; z-index: 1; }
.sv-live[data-phase="listening"] .sv-ring { animation: sv-pulse 1.8s ease-out infinite; }
.sv-live[data-phase="listening"] .sv-ring2 { animation-delay: .9s; }
.sv-live[data-phase="speaking"] .sv-ring { border-color: rgba(59, 130, 246, .45); animation: sv-pulse 1.1s ease-out infinite; }
.sv-live[data-phase="speaking"] .sv-ring2 { animation-delay: .55s; }
.sv-live[data-phase="speaking"] .sv-core { background: radial-gradient(circle at 32% 28%, #93c5fd 0%, #3b82f6 38%, #1d4ed8 75%, #1e3a8a 100%); }
.sv-live[data-phase="thinking"] .sv-core { animation: sv-think 1.2s ease-in-out infinite; }
@keyframes sv-pulse { 0% { transform: scale(1); opacity: .9; } 100% { transform: scale(1.55); opacity: 0; } }
@keyframes sv-think { 0%, 100% { transform: scale(.94); filter: brightness(.95); } 50% { transform: scale(1.03); filter: brightness(1.12); } }
.sv-orb-label { font-size: 20px; font-weight: 800; color: #0f2433; letter-spacing: -.01em; }
.sv-status { max-width: 520px; font-size: 14.5px; line-height: 1.45; color: #475569; min-height: 21px; }
.sv-live.has-error .sv-status { color: #b42318; font-weight: 600; }
.sv-caption { max-width: 560px; min-height: 22px; font-size: 16px; font-style: italic; color: #0f766e; }
.sv-live:not(.is-live) .sv-caption { display: none; }
.sv-end {
  display: none; margin-top: 4px; padding: 7px 16px; border-radius: 999px; cursor: pointer;
  border: 1px solid #f1b8b4; background: #fff5f4; color: #b42318; font-weight: 700; font-size: 13.5px;
}
.sv-live.is-live .sv-end { display: inline-block; }
.sv-end:hover { background: #fee4e2; }

.sv-log { flex: 1 1 auto; min-height: 120px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 4px 4px 4px 2px; }
.sv-msg { max-width: 86%; padding: 10px 14px; border-radius: 16px; font-size: 15px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
.sv-bot { align-self: flex-start; background: #f1f5f9; color: #0f2433; border: 1px solid #e2e8f0; border-bottom-left-radius: 5px; }
.sv-user { align-self: flex-end; background: #0f766e; color: #ffffff; border-bottom-right-radius: 5px; }

.sv-confirm { display: none; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 12px; border-radius: 12px; background: #fff8e6; border: 1px solid #f5d48a; color: #7a4b00; font-size: 14px; font-weight: 600; }
.sv-confirm.show { display: flex; }
.sv-confirm span { margin-right: auto; }
.sv-confirm button { padding: 6px 14px; border-radius: 999px; cursor: pointer; font-weight: 700; font-size: 13.5px; border: 1px solid transparent; }
.sv-confirm .sv-yes { background: #0f766e; color: #ffffff; }
.sv-confirm .sv-no { background: #ffffff; color: #334155; border-color: #cbd5df; }

.sv-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.sv-chip {
  padding: 7px 12px; border-radius: 999px; cursor: pointer; font-size: 13.5px; font-weight: 600;
  border: 1px solid #bfd9d5; background: #effaf8; color: #0f5e57;
}
.sv-chip:hover { background: #dff4f0; }
.sv-form { display: flex; gap: 8px; }
.sv-form input {
  flex: 1 1 auto; min-width: 0; padding: 12px 14px; border-radius: 12px; font-size: 15px;
  border: 1px solid #cbd5df; background: #ffffff; color: #0f2433; outline: none;
}
.sv-form input::placeholder { color: #7b8794; }
.sv-form input:focus { border-color: #0f766e; box-shadow: 0 0 0 3px rgba(15, 118, 110, .15); }
.sv-form button {
  padding: 0 20px; border: 0; border-radius: 12px; cursor: pointer; font-size: 15px; font-weight: 700;
  background: #0f766e; color: #ffffff;
}
.sv-form button:hover { background: #0b5f59; }

/* ---------- account panel ---------- */
.sv-panel { padding: 18px; border-radius: 18px; background: #ffffff; border: 1px solid #d5dee5; box-shadow: 0 6px 18px rgba(15, 36, 51, .06); color: #0f2433; }
.sv-panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
.sv-panel h3 { margin: 0 !important; font-size: 18px !important; font-weight: 800 !important; color: #0f2433 !important; }
.sv-panel h4 { margin: 18px 0 8px !important; font-size: 13px !important; font-weight: 800 !important; color: #475569 !important; text-transform: uppercase; letter-spacing: .06em; }
.sv-muted { color: #64748b; font-size: 12.5px; }
.sv-tiles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.sv-tile { padding: 12px 13px; border-radius: 13px; background: #f6f9fb; border: 1px solid #e2e8f0; }
.sv-tile-label { font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }
.sv-tile-value { margin-top: 4px; font-size: 20px; font-weight: 800; color: #0f2433; letter-spacing: -.01em; }
.sv-tile-value.sv-debt { color: #b42318; }
.sv-bills { list-style: none; margin: 0 !important; padding: 0 2px 0 0 !important; display: flex; flex-direction: column; gap: 6px;
  max-height: max(230px, calc(100vh - 520px)); overflow-y: auto; }
.sv-bills li { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 !important; padding: 9px 11px; border-radius: 11px; border: 1px solid #e8eef2; background: #ffffff; }
.sv-bill-name { font-weight: 700; font-size: 14.5px; color: #0f2433; }
.sv-bill-meta { font-size: 12.5px; color: #64748b; }
.sv-bill-amt { font-weight: 800; font-size: 14.5px; color: #0f2433; white-space: nowrap; }
.sv-soon { color: #b45309; font-weight: 700; }
.sv-disclaimer { margin-top: 2px; text-align: center; font-size: 12.5px; color: #64748b; }

@media (max-width: 760px) {
  .sv-live, .sv-panel { padding: 14px; }
  .sv-header { padding: 14px 16px; }
  .sv-header h1 { font-size: 22px !important; }
  .sv-live { height: auto; min-height: 0; }
  .sv-bills { max-height: none; }
  .sv-log { max-height: 46vh; }
  .sv-orb { width: 112px; height: 112px; }
  .sv-msg { max-width: 94%; }
}
"""

# Removes the "dark" class Gradio adds when the operating system uses dark mode. The theme
# below also maps every dark-mode color to its light value, so even if the class comes back
# text never ends up light-on-light (that is what made tabs and labels invisible before).
FORCE_LIGHT_JS = """
() => {
  document.documentElement.classList.remove('dark');
  if (document.body) document.body.classList.remove('dark');
}
"""


def light_only_theme():
    import gradio as gr

    theme = gr.themes.Soft(primary_hue="teal", neutral_hue="slate", radius_size="lg")
    for name in list(vars(theme)):
        if name.endswith("_dark") and hasattr(theme, name[: -len("_dark")]):
            setattr(theme, name, getattr(theme, name[: -len("_dark")]))
    return theme


HEADER_HTML = f"""
<header class="sv-header">
  <div class="sv-brand">
    <div class="sv-logo">S</div>
    <div><h1>Solvra</h1><p>Talk to your money. Ask about bills, balances and what to pay first.</p></div>
  </div>
  <div class="sv-badge">Demo account · {AS_OF:%b} {AS_OF.day}, {AS_OF.year}</div>
</header>
"""

_MIC_SVG = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a1 1 0 1 1 2 0'
    " 7 7 0 0 1-6 6.93V21h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-2.07A7 7 0 0 1 5 12a1 1 0 1 1 2 0 5 5 0 0 0 10 0Z\"/></svg>"
)

LIVE_SUGGESTIONS = [
    "How much money do I have?",
    "What bills are due this week?",
    "What should I pay first?",
    "How much did I spend last month?",
]

LIVE_HTML = (
    '<div class="sv-live" data-phase="idle">'
    '<div class="sv-stage">'
    '<button id="sv-orb" class="sv-orb" type="button" aria-label="Start live voice chat">'
    '<span class="sv-ring sv-ring1"></span><span class="sv-ring sv-ring2"></span>'
    f'<span class="sv-core">{_MIC_SVG}</span></button>'
    '<div id="sv-orb-label" class="sv-orb-label">Speak live</div>'
    '<div id="sv-status" class="sv-status">Tap the button and just start talking. Solvra listens, then answers out loud.</div>'
    '<div id="sv-caption" class="sv-caption" aria-live="polite"></div>'
    '<button id="sv-end" class="sv-end" type="button">End live chat</button>'
    "</div>"
    '<div id="sv-log" class="sv-log" aria-live="polite">'
    '<div class="sv-msg sv-bot">Hi! I\'m Solvra. Tap <b>Speak live</b> and ask me anything about this account, '
    "like what's due this week or which bills to pay first. You can also type below.</div>"
    "</div>"
    '<div id="sv-confirm" class="sv-confirm"><span>Waiting for your OK. Say yes or no.</span>'
    '<button type="button" class="sv-yes" data-answer="Yes">Yes, do it</button>'
    '<button type="button" class="sv-no" data-answer="No">No, cancel</button></div>'
    '<div class="sv-chips">'
    + "".join(
        f'<button type="button" class="sv-chip">{q}</button>' for q in LIVE_SUGGESTIONS
    )
    + "</div>"
    '<form id="sv-form" class="sv-form" autocomplete="off">'
    '<input id="sv-input" type="text" placeholder="Or type a question..." aria-label="Type a question" />'
    '<button type="submit">Send</button></form>'
    "</div>"
)

LIVE_JS = r"""
const root = element.querySelector('.sv-live');
const $ = (id) => element.querySelector('#' + id);
const orb = $('sv-orb'), orbLabel = $('sv-orb-label'), statusEl = $('sv-status');
const caption = $('sv-caption'), log = $('sv-log'), form = $('sv-form'), input = $('sv-input');
const endBtn = $('sv-end'), confirmBar = $('sv-confirm');
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const IDLE_TEXT = 'Tap the button and just start talking. Solvra listens, then answers out loud.';
const LABELS = { idle: 'Speak live', listening: 'Listening...', thinking: 'Thinking...', speaking: 'Speaking...' };
const S = {
  live: false, phase: 'idle', pending: null, last: '', mode: SR ? 'browser' : 'recorder',
  rec: null, recorder: null, stream: null, ctx: null, timer: null, listenId: 0,
  busy: false, quiet: 0, failures: 0, voice: null, speakToken: 0, discard: false,
};

function setPhase(phase, text) {
  S.phase = phase;
  root.dataset.phase = phase;
  root.classList.toggle('is-live', S.live);
  orbLabel.textContent = LABELS[phase] || 'Speak live';
  statusEl.textContent = text || '';
  orb.setAttribute('aria-label', phase === 'idle' ? 'Start live voice chat'
    : phase === 'speaking' ? 'Interrupt and speak' : 'End live voice chat');
  if (phase !== 'listening') root.style.setProperty('--lvl', 0);
}
function addMsg(who, text) {
  const div = document.createElement('div');
  div.className = 'sv-msg sv-' + who;
  div.textContent = text;
  log.appendChild(div);
  root.classList.add('has-chat');
  log.scrollTop = log.scrollHeight;
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
}
function showConfirm() { confirmBar.classList.toggle('show', !!S.pending); }

/* ---------- speaking (browser text-to-speech) ---------- */
function pickVoice() {
  if (!('speechSynthesis' in window)) return;
  const english = speechSynthesis.getVoices().filter((v) => /^en([-_]|$)/i.test(v.lang));
  const preferred = [/Google US English/i, /Natural/i, /Neural/i, /Samantha/i, /Aria/i, /Jenny/i, /Ava/i, /Zira/i, /Google UK English Female/i];
  for (const pattern of preferred) {
    const match = english.find((v) => pattern.test(v.name));
    if (match) { S.voice = match; return; }
  }
  S.voice = english.find((v) => /en[-_]US/i.test(v.lang)) || english[0] || null;
}
if ('speechSynthesis' in window) {
  pickVoice();
  speechSynthesis.addEventListener('voiceschanged', pickVoice);
}
function stopSpeaking() {
  S.speakToken += 1;
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}
function speak(text) {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window) || !text) { resolve(); return; }
    stopSpeaking();
    const token = S.speakToken;
    const parts = text.split(/(?<=[.!?])\s+/).filter(Boolean);
    let index = 0;
    const next = () => {
      if (token !== S.speakToken || index >= parts.length) { resolve(); return; }
      const utterance = new SpeechSynthesisUtterance(parts[index++]);
      if (S.voice) { utterance.voice = S.voice; utterance.lang = S.voice.lang; } else { utterance.lang = 'en-US'; }
      utterance.rate = 1.04;
      let finished = false;
      const finish = () => { if (finished) return; finished = true; clearTimeout(guard); next(); };
      // Some browsers occasionally never fire "end"; never let the conversation get stuck.
      const guard = setTimeout(finish, 4000 + utterance.text.length * 95);
      utterance.onend = finish;
      utterance.onerror = finish;
      speechSynthesis.speak(utterance);
    };
    next();
  });
}

/* ---------- live session control ---------- */
function micProblem(kind) {
  S.live = false;
  S.listenId += 1;
  releaseMic();
  let message;
  if (!window.isSecureContext) {
    message = 'Voice needs a secure (https) link or localhost. Open the app through its https link.';
  } else if (kind === 'nomic') {
    message = 'No microphone was found. Connect one, or type your question below.';
  } else if (kind === 'unsupported') {
    message = 'This browser cannot do live voice. Try Chrome, Edge or Safari, or type your question below.';
  } else {
    message = 'The microphone is blocked. Allow microphone access for this site (lock icon in the address bar), then tap Speak live again.';
    if (window.top !== window) message += ' If the app is shown inside another page, open it in its own tab.';
  }
  root.classList.add('has-error');
  setPhase('idle', message);
}
function releaseMic() {
  if (S.timer) { clearInterval(S.timer); S.timer = null; }
  if (S.stream) { S.stream.getTracks().forEach((t) => t.stop()); S.stream = null; }
}
async function ensureStream() {
  if (S.stream) return S.stream;
  S.stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  return S.stream;
}
async function startLive() {
  root.classList.remove('has-error');
  if (!window.isSecureContext) { micProblem('insecure'); return; }
  if (!SR && !(navigator.mediaDevices && window.MediaRecorder)) { micProblem('unsupported'); return; }
  S.live = true; S.quiet = 0; S.failures = 0;
  // Unlock speech output inside the click (required by Safari / iOS).
  if ('speechSynthesis' in window) {
    try { const u = new SpeechSynthesisUtterance(' '); u.volume = 0; speechSynthesis.speak(u); } catch (e) {}
  }
  if (S.mode === 'recorder') {
    try { await ensureStream(); } catch (e) { micProblem(e && e.name === 'NotFoundError' ? 'nomic' : 'blocked'); return; }
  }
  listen();
}
function stopLive(message) {
  S.live = false;
  S.listenId += 1;
  stopSpeaking();
  if (S.rec) { try { S.rec.abort(); } catch (e) {} S.rec = null; }
  if (S.recorder && S.recorder.state === 'recording') { S.discard = true; try { S.recorder.stop(); } catch (e) {} }
  releaseMic();
  caption.textContent = '';
  setPhase('idle', message || IDLE_TEXT);
}
function listen() {
  if (!S.live) return;
  const id = ++S.listenId;
  caption.textContent = '';
  setPhase('listening', S.mode === 'browser'
    ? "Go ahead, I'm listening."
    : "Go ahead, I'm listening. Pause when you're done.");
  if (S.mode === 'browser') listenBrowser(id); else listenRecorder(id);
}
function quietTooLong() {
  S.quiet += 1;
  if (S.quiet >= 6) { stopLive('Paused because it was quiet for a while. Tap Speak live to continue.'); return true; }
  return false;
}
function switchToRecorder() {
  S.mode = 'recorder';
  ensureStream().then(() => listen()).catch((e) => micProblem(e && e.name === 'NotFoundError' ? 'nomic' : 'blocked'));
}

/* Browser speech recognition (Chrome, Edge, Safari): live captions, automatic end-of-speech. */
function listenBrowser(id) {
  let rec;
  try { rec = new SR(); } catch (e) { switchToRecorder(); return; }
  S.rec = rec;
  rec.lang = 'en-US';
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;
  let finalText = '', interimText = '', error = null;
  rec.onresult = (event) => {
    interimText = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) finalText += result[0].transcript + ' ';
      else interimText += result[0].transcript;
    }
    caption.textContent = (finalText + interimText).trim();
  };
  rec.onerror = (event) => { error = event.error; };
  rec.onend = () => {
    if (S.rec === rec) S.rec = null;
    if (id !== S.listenId || !S.live) return;
    const text = (finalText || interimText).trim();
    if (error === 'not-allowed') { micProblem('blocked'); return; }
    if (error === 'audio-capture') { micProblem('nomic'); return; }
    if (error === 'network' || error === 'service-not-allowed' || error === 'language-not-supported') {
      switchToRecorder();
      return;
    }
    if (text) { S.quiet = 0; S.failures = 0; handleUtterance(text); return; }
    if (error && error !== 'no-speech' && error !== 'aborted') {
      S.failures += 1;
      if (S.failures >= 4) { switchToRecorder(); return; }
    }
    if (quietTooLong()) return;
    setTimeout(() => { if (id === S.listenId && S.live) listen(); }, 150);
  };
  try { rec.start(); } catch (e) {
    S.failures += 1;
    if (S.failures >= 4) { switchToRecorder(); return; }
    setTimeout(() => { if (id === S.listenId && S.live) listen(); }, 400);
  }
}

/* Fallback: record until a pause, then transcribe on the server with Faster-Whisper. */
async function listenRecorder(id) {
  let stream;
  try { stream = await ensureStream(); } catch (e) { micProblem(e && e.name === 'NotFoundError' ? 'nomic' : 'blocked'); return; }
  if (id !== S.listenId || !S.live) return;
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  S.ctx = S.ctx || new AudioCtx();
  if (S.ctx.state === 'suspended') { try { await S.ctx.resume(); } catch (e) {} }
  const source = S.ctx.createMediaStreamSource(stream);
  const analyser = S.ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
    .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks = [];
  recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  const stopped = new Promise((resolve) => { recorder.onstop = resolve; });
  S.recorder = recorder;
  S.discard = false;
  recorder.start(250);
  const t0 = performance.now();
  let noise = 0.008, speaking = false, speechStart = 0, lastVoice = 0;
  S.timer = setInterval(() => {
    if (recorder.state !== 'recording') { clearInterval(S.timer); S.timer = null; return; }
    if (id !== S.listenId || !S.live) { recorder.stop(); return; }
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    const rms = Math.sqrt(sum / samples.length);
    const now = performance.now();
    if (!speaking) noise = noise * 0.95 + Math.min(rms, 0.05) * 0.05;
    const threshold = Math.max(0.018, noise * 2.8);
    root.style.setProperty('--lvl', Math.min(1, rms * 10).toFixed(3));
    if (rms > threshold) { if (!speaking) { speaking = true; speechStart = now; } lastVoice = now; }
    if (speaking && now - lastVoice > 1200 && now - speechStart > 500) recorder.stop();
    else if (!speaking && now - t0 > 12000) recorder.stop();
    else if (speaking && now - speechStart > 25000) recorder.stop();
  }, 50);
  await stopped;
  if (S.timer) { clearInterval(S.timer); S.timer = null; }
  try { source.disconnect(); } catch (e) {}
  root.style.setProperty('--lvl', 0);
  if (S.discard || id !== S.listenId || !S.live) { S.discard = false; return; }
  if (!speaking || !chunks.length) { if (!quietTooLong()) listen(); return; }
  S.quiet = 0;
  setPhase('thinking', 'Turning your speech into text...');
  try {
    const type = recorder.mimeType || mime || 'audio/webm';
    const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm';
    const file = new File([new Blob(chunks, { type })], 'speech.' + ext, { type });
    const uploaded = await upload(file);
    let result = await server.transcribe_clip({ path: uploaded.path });
    if (typeof result === 'string') result = JSON.parse(result);
    if (id !== S.listenId || !S.live) return;
    if (result.error) { stopLive(result.error); root.classList.add('has-error'); return; }
    if (result.text) handleUtterance(result.text); else listen();
  } catch (e) {
    stopLive('Could not transcribe that. Please try again or type your question.');
    root.classList.add('has-error');
  }
}

/* ---------- one conversation turn ---------- */
async function handleUtterance(text) {
  text = (text || '').trim();
  if (!text || S.busy) return;
  S.busy = true;
  stopSpeaking();
  S.listenId += 1;  // cancel any listening that is still running
  if (S.rec) { try { S.rec.abort(); } catch (e) {} S.rec = null; }
  if (S.recorder && S.recorder.state === 'recording') { S.discard = true; try { S.recorder.stop(); } catch (e) {} }
  root.classList.remove('has-error');
  addMsg('user', text);
  caption.textContent = '';
  setPhase('thinking', 'Thinking...');
  let res;
  try {
    res = await server.live_turn({ text: text, pending: S.pending, last: S.last });
    if (typeof res === 'string') res = JSON.parse(res);
  } catch (e) {
    res = {
      reply: "Sorry, I couldn't reach the Solvra server. Make sure the app is still running, then try again.",
      speech: 'Sorry, I could not reach the server. Please try again.',
    };
  }
  S.busy = false;
  if (!/^(yes|yeah|yep|no|nope|ok|okay|sure|cancel)\b/i.test(text)) S.last = text;
  S.pending = res.pending || null;
  showConfirm();
  addMsg('bot', res.reply || '');
  if (res.changed) trigger('account_changed');
  if (S.live) {
    setPhase('speaking', 'Speaking... tap the button to interrupt.');
    await speak(res.speech || res.reply);
    if (res.end) { stopLive('Live chat ended. Tap Speak live to start again.'); return; }
    if (S.live && S.phase === 'speaking') listen();
  } else {
    setPhase('idle', IDLE_TEXT);
  }
}

/* ---------- controls ---------- */
orb.addEventListener('click', () => {
  if (S.phase === 'speaking') { stopSpeaking(); if (S.live) listen(); else setPhase('idle', IDLE_TEXT); return; }
  if (!S.live) { startLive(); return; }
  if (S.phase === 'listening') stopLive();
});
endBtn.addEventListener('click', () => stopLive('Live chat ended. Tap Speak live to start again.'));
form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  handleUtterance(text);
});
element.querySelectorAll('.sv-chip').forEach((chip) => {
  chip.addEventListener('click', () => handleUtterance(chip.textContent));
});
confirmBar.querySelectorAll('button').forEach((button) => {
  button.addEventListener('click', () => handleUtterance(button.dataset.answer));
});
window.addEventListener('pagehide', () => stopLive());
"""


def account_panel_html(account: AccountStore = DEMO) -> str:
    """Plain HTML snapshot: four balance tiles and the list of open bills."""
    checking = account.balance("Checking")
    savings = account.balance("Savings")
    debt = sum(account.debts().values())
    open_bills = current_open_bills(account)
    due_14 = sum(b.amount for b in current_open_bills(account, 14))
    tiles = [
        ("Checking", money(checking), ""),
        ("Savings", money(savings), ""),
        ("Debt", money(debt), " sv-debt"),
        ("Due in 14 days", money(due_14), ""),
    ]
    tile_html = "".join(
        f'<div class="sv-tile"><div class="sv-tile-label">{label}</div>'
        f'<div class="sv-tile-value{extra}">{value}</div></div>'
        for label, value, extra in tiles
    )
    rows = []
    for b in open_bills:
        days = (b.effective_due - AS_OF).days
        when = (
            "due today"
            if days == 0
            else (f"in {days} day{'s' if days != 1 else ''}" if days > 0 else f"{-days} days late")
        )
        when_html = f'<span class="sv-soon">{when}</span>' if days <= 3 else when
        partial = " · partly paid" if b.status == "Partially paid" else ""
        rows.append(
            f'<li><div><div class="sv-bill-name">{html.escape(b.name)}</div>'
            f'<div class="sv-bill-meta">{_spoken_date(b.effective_due)} · {when_html}{partial}</div></div>'
            f'<div class="sv-bill-amt">{money(b.amount)}</div></li>'
        )
    bills_html = (
        f'<ul class="sv-bills">{"".join(rows)}</ul>'
        if rows
        else '<p class="sv-muted">No open bills. Nice work!</p>'
    )
    return (
        '<div class="sv-panel">'
        f'<div class="sv-panel-head"><h3>Your money</h3><span class="sv-muted">as of {_spoken_date(AS_OF)}, {AS_OF.year}</span></div>'
        f'<div class="sv-tiles">{tile_html}</div>'
        f"<h4>Bills to pay ({len(open_bills)})</h4>{bills_html}"
        "</div>"
    )


def transcribe_clip(payload: Any) -> dict[str, str]:
    """Live-chat server function: transcribe a clip the browser uploaded (Gradio upload folder only)."""
    path = payload.get("path") if isinstance(payload, dict) else payload
    if not path:
        return {"text": "", "error": ""}
    try:
        from gradio.utils import get_upload_folder

        allowed = Path(get_upload_folder()).resolve()
        resolved = Path(str(path)).resolve()
        if allowed not in resolved.parents or not resolved.is_file():
            return {"text": "", "error": "That recording could not be found. Please try again."}
    except Exception:
        return {"text": "", "error": "That recording could not be read. Please try again."}
    text = transcribe_audio(str(resolved))
    if text.startswith("[Transcription unavailable"):
        return {
            "text": "",
            "error": "Speech-to-text isn't available in this browser setup. Use Chrome, Edge or Safari for live voice, or type your question.",
        }
    return {"text": text, "error": ""}


def live_turn(payload: Any) -> dict[str, Any]:
    """Live-chat server function: the browser sends {text, pending, last} and speaks the reply."""
    data = payload if isinstance(payload, dict) else {"text": str(payload or "")}
    pending = data.get("pending") if isinstance(data.get("pending"), dict) else None
    return assistant_turn(
        str(data.get("text") or ""), pending, str(data.get("last") or ""), DEMO
    )


def launch_app():
    """Build the one-page Gradio interface."""
    import gradio as gr

    def reset_account() -> str:
        DEMO.reset()
        return account_panel_html(DEMO)

    with gr.Blocks(title="Solvra — voice money assistant") as app:
        gr.HTML(HEADER_HTML, js_on_load=None, apply_default_css=False)
        with gr.Row(elem_id="sv-main", equal_height=False):
            with gr.Column(scale=3, min_width=340):
                live = gr.HTML(
                    LIVE_HTML,
                    js_on_load=LIVE_JS,
                    server_functions=[live_turn, transcribe_clip],
                    apply_default_css=False,
                    elem_id="sv-live-wrap",
                )
            with gr.Column(scale=2, min_width=300):
                panel = gr.HTML(
                    account_panel_html(DEMO), js_on_load=None, apply_default_css=False
                )
                reset = gr.Button(
                    "Reset demo account", size="sm", variant="secondary", elem_id="sv-reset"
                )
        gr.HTML(
            f'<p class="sv-disclaimer">Fictional demo household. {DISCLAIMER} Solvra never moves money or contacts anyone.</p>',
            js_on_load=None,
            apply_default_css=False,
        )
        live.account_changed(lambda: account_panel_html(DEMO), None, panel)
        reset.click(reset_account, None, panel)
        app.load(lambda: account_panel_html(DEMO), None, panel)
    return app


def launch_options() -> dict[str, Any]:
    """Styling passed to ``Blocks.launch`` (Gradio 6 takes theme/css/js at launch time)."""
    return {"theme": light_only_theme(), "css": APP_CSS, "js": FORCE_LIGHT_JS}


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
    """Start the app; inside Google Colab it also prints a public https share link."""
    server_port = configured_server_port()
    app = launch_app()
    app.launch(
        share="google.colab" in sys.modules,
        server_name="0.0.0.0",
        server_port=server_port,
        show_error=True,
        height=900,
        footer_links=[],
        **launch_options(),
    )


if __name__ == "__main__":
    main()
