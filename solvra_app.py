# Solvra — synthetic, consequence-aware financial decision support prototype
# Google Colab-ready, modular single-file implementation. No paid APIs required.
from __future__ import annotations

import calendar
import copy
import datetime as dt
import json
import os
import random
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from sklearn.linear_model import LinearRegression

# ----------------------------- data_models ---------------------------------
AS_OF = dt.date(2026, 11, 14)
PROJECT_TITLE = "Solvra"
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
    extension_terms: str = ""
    partial_allowed: bool = True
    source: str = "Synthetic demonstration data"
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
    strategy: str
    payments: list[dict[str, Any]]
    harm: dict[str, float]
    total_allocated: float
    remaining_cash: float
    unpaid: float
    critical_count: int
    feasible: bool
    explanation: list[str]


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


def _month_label(d):
    return pd.Timestamp(d).strftime("%Y-%m")


def generate_demo_records(seed: int = RNG_SEED) -> dict[str, Any]:
    """Build a deterministic, ledger-backed fictional 24-month household history."""
    rng = random.Random(seed)
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
            "",
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
            "",
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
            "",
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
            "",
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
            "",
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
            "",
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
            "",
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
            "",
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
            "",
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
            "",
            False,
        ),
    ]
    # Event-driven synthetic profile facts are shown alongside the actual ledger.
    events_story = [
        {
            "date": "2025-05-11",
            "event": "Unexpected $895 car repair; savings transfer and tighter bill timing followed.",
        },
        {
            "date": "2025-08-16",
            "event": "Electricity bill rose to $298.40 during a heat wave; partial and late payment recorded.",
        },
        {
            "date": "2025-12-01",
            "event": "Rent increased from $1,325 to $1,425; seasonal grocery spending also rose.",
        },
        {
            "date": "2026-02-13",
            "event": "Unexpected $487.35 medical expense during a temporary reduction in work hours.",
        },
        {
            "date": "2026-10-24",
            "event": "One paycheck arrived four days late; credit-card payment was recorded late.",
        },
        {
            "date": "2026-07-01",
            "event": "Subscription bundle was reduced after unused services were canceled.",
        },
    ]
    return {
        "transactions": transactions,
        "bill_history": pd.DataFrame(bill_rows),
        "income_history": pd.DataFrame(incomes),
        "balance_history": balance_history,
        "debt_history": debt_history,
        "bills": current_specs,
        "opening": opening,
        "initial_debt": initial_debt,
        "events": events_story,
    }


# -------------------------- demo_account / persistence ----------------------
class AccountStore:
    """One in-memory source of truth; constructed once, reset explicitly by the user."""

    def __init__(self, records: dict[str, Any]):
        self.lock = threading.RLock()
        self.records = records
        self.preferences = {
            "reserve": 250.0,
            "financial_priority": "Protect housing and essential services",
            "special_circumstances": "",
            "paycheck": 2200.0,
            "payday": dt.date(2026, 11, 20),
            "other_income": 0.0,
            "other_income_date": dt.date(2026, 11, 20),
        }
        self.debt_adjustments = {
            "Credit Card": 0.0,
            "Auto Loan": 0.0,
            "Student Loan": 0.0,
        }
        self.custom_bills: list[Bill] = []
        self.removed_bill_ids: set[str] = set()
        self.chat_context: list[dict[str, str]] = []
        self.version = 1

    @property
    def bills(self) -> list[Bill]:
        return [
            b
            for b in self.records["bills"] + self.custom_bills
            if b.bill_id not in self.removed_bill_ids
        ]

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
        with self.lock:
            # Latest history is ledger-derived; apply current-session card/loan updates if present.
            latest = self.records["debt_history"].iloc[-1]
            return {
                k: round(
                    max(0.0, float(latest[k]) + self.debt_adjustments.get(k, 0.0)), 2
                )
                for k in ["Credit Card", "Auto Loan", "Student Loan"]
            }

    def adjust_debt(self, kind: str, delta: float):
        """delta is positive when liability rises, negative when principal is paid."""
        aliases = {
            "credit card": "Credit Card",
            "credit card minimum": "Credit Card",
            "auto loan": "Auto Loan",
            "student loan": "Student Loan",
        }
        key = aliases.get(kind.lower(), kind)
        if key in self.debt_adjustments:
            base = float(
                self.records["debt_history"].iloc[-1][key]
            ) + self.debt_adjustments.get(key, 0.0)
            updated = max(0.0, base + float(delta))
            last = self.records["debt_history"].index[-1]
            self.records["debt_history"].loc[last, key] = updated
            self.records["debt_history"].loc[last, "total_debt"] = sum(
                float(self.records["debt_history"].loc[last, k])
                for k in ("Credit Card", "Auto Loan", "Student Loan")
            )
            self.debt_adjustments[key] = 0.0
            self.version += 1

    def add_transaction(
        self,
        amount: float,
        category: str,
        merchant: str,
        description: str,
        date: dt.date | None = None,
        account: str = "Checking",
        tx_type: str = "Adjustment",
        method: str = "Manual entry",
        recurrence: str = "One-time",
    ):
        with self.lock:
            date = date or AS_OF
            if date != AS_OF:
                raise ValueError(
                    f"Session entries must use the account snapshot date {AS_OF.isoformat()}; use expected-income inputs for future deposits"
                )
            if (
                account in ("Checking", "Savings")
                and self.balance(account) + float(amount) < -0.01
            ):
                raise ValueError(f"Transaction would make {account.lower()} negative")
            row = {
                "transaction_id": f"TX-{uuid.uuid4().hex[:10].upper()}",
                "date": pd.Timestamp(date),
                "merchant": merchant,
                "amount": round(float(amount), 2),
                "category": category,
                "transaction_type": tx_type,
                "payment_method": method,
                "description": description,
                "recurrence": recurrence,
                "account": account,
            }
            self.records["transactions"] = (
                pd.concat(
                    [self.records["transactions"], pd.DataFrame([row])],
                    ignore_index=True,
                )
                .sort_values("date")
                .reset_index(drop=True)
            )
            if account == "Checking" and category == "Income" and float(amount) > 0:
                income_row = {
                    "date": pd.Timestamp(date),
                    "amount": round(float(amount), 2),
                    "source": merchant,
                    "type": tx_type,
                    "scheduled_date": date,
                    "delayed": False,
                }
                self.records["income_history"] = pd.concat(
                    [self.records["income_history"], pd.DataFrame([income_row])],
                    ignore_index=True,
                )
            if account == "Credit Card":
                self.adjust_debt("Credit Card", -float(amount))
            last = self.records["balance_history"].index[-1]
            self.records["balance_history"].loc[last, "checking"] = self.balance(
                "Checking"
            )
            self.records["balance_history"].loc[last, "savings"] = self.balance(
                "Savings"
            )
            self.records["balance_history"].loc[last, "total_cash"] = self.balance(
                "Checking"
            ) + self.balance("Savings")
            self.version += 1
            return row

    def add_bill(self, bill: Bill):
        with self.lock:
            self.custom_bills.append(bill)
            self.version += 1

    def record_bill_payment(
        self, bill: Bill, amount: float, date: dt.date | None = None
    ):
        with self.lock:
            date = date or AS_OF
            row = {
                "bill_id": bill.bill_id,
                "provider": bill.provider,
                "bill_name": bill.name,
                "category": bill.category,
                "original_amount": round(float(bill.amount + amount), 2),
                "due_date": bill.effective_due,
                "payment_date": date,
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
            self.version += 1

    def find_bill(self, identifier: str) -> Bill | None:
        key = str(identifier).strip().lower()
        return next(
            (
                b
                for b in self.bills
                if b.bill_id.lower() == key
                or b.name.lower() == key
                or b.provider.lower() == key
            ),
            None,
        )

    def delete_bill(self, identifier: str) -> bool:
        with self.lock:
            bill = self.find_bill(identifier)
            if bill is None:
                return False
            if bill in self.custom_bills:
                self.custom_bills.remove(bill)
            else:
                self.removed_bill_ids.add(bill.bill_id)
            self.version += 1
            return True

    def reset(self):
        with self.lock:
            self.records = generate_demo_records()
            self.custom_bills = []
            self.preferences = {
                "reserve": 250.0,
                "financial_priority": "Protect housing and essential services",
                "special_circumstances": "",
                "paycheck": 2200.0,
                "payday": dt.date(2026, 11, 20),
                "other_income": 0.0,
                "other_income_date": dt.date(2026, 11, 20),
            }
            self.debt_adjustments = {
                "Credit Card": 0.0,
                "Auto Loan": 0.0,
                "Student Loan": 0.0,
            }
            self.removed_bill_ids = set()
            self.chat_context = []
            self.version += 1


DEMO = AccountStore(generate_demo_records())


# ------------------------- financial_calculations ---------------------------
def transactions_for_period(
    account: AccountStore, days: int | None = 90
) -> pd.DataFrame:
    df = account.transactions.copy()
    if days is not None:
        df = df[df.date >= pd.Timestamp(AS_OF - dt.timedelta(days=days))]
    return df


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


def health_assessment(account: AccountStore) -> tuple[int, pd.DataFrame, str]:
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
    explanation = (
        f"Transparent 0–100 index: weighted sum of the seven factors shown (weights total 100%). "
        f"Income stability uses 1 − 12-month income coefficient of variation; positive cash-flow months use the share of months net-positive; "
        f"income-to-expense balance averages that positive-month share with a clipped, normalized income-minus-expense margin; "
        f"emergency coverage is savings ÷ essential monthly expense, capped at 3 months; DTI score declines linearly to zero at 150%; "
        f"payment score uses recorded late bills; savings trend compares the latest six monthly snapshots. Current coverage is {coverage:.1f} months and DTI is {dti:.1%}. "
        "This is a transparent prototype indicator, not a credit score or a prediction of outcomes."
    )
    return score, detail, explanation


def current_open_bills(account: AccountStore) -> list[Bill]:
    return [b for b in account.bills if b.status not in ("Paid", "Closed")]


def scenario_from_account(
    account: AccountStore,
    available: float | None = None,
    income_amount: float = 0,
    income_date: dt.date | None = None,
    reserve: float | None = None,
    bills: list[Bill] | None = None,
) -> Scenario:
    income = []
    if income_amount and income_date:
        income.append(
            IncomeEvent(float(income_amount), income_date, "Expected paycheck", False)
        )
    # include other expected income entered as preferences, if any
    return Scenario(
        float(account.balance("Checking") if available is None else available),
        AS_OF,
        copy.deepcopy(bills if bills is not None else current_open_bills(account)),
        income,
        float(account.preferences["reserve"] if reserve is None else reserve),
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


def _benefit_per_dollar(
    bill: Bill,
    payment_date: dt.date,
    horizon: dt.date,
    weights: dict[str, float],
) -> float:
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
    return (
        weights.get("late_fee", 1.0) * fee_avoided
        + weights.get("interest", 1.0) * interest_avoided
        + weights.get("critical", 1.0) * consequence_avoided
    )


def optimize(s: Scenario, weights: dict[str, float] | None = None) -> PlanResult:
    """MILP allocation with cash-by-date constraints, minimums, and non-partial bill rules."""
    if not s.bills:
        return PlanResult(
            "Intelligent optimization",
            [],
            {"late_fees": 0, "interest": 0, "critical_harm": 0, "total_harm": 0},
            0,
            max(0, s.available_cash - s.reserve),
            0,
            0,
            True,
            ["No outstanding bills were supplied."],
        )
    weights = weights or {"late_fee": 1.0, "interest": 1.0, "critical": 1.0}
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
            benefit = _benefit_per_dollar(b, d, horizon, weights)
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
        # Explicit valid fallback: hold funds and let the user consider provider contact; never exceed cash.
        return evaluate_plan(
            s,
            {},
            "Intelligent optimization (safe fallback)",
            [
                "Solver did not return a feasible allocation; no funds are allocated automatically."
            ],
            weights=weights,
        )
    payments = {}
    for i, b in enumerate(s.bills):
        for j, d in enumerate(dates):
            amount = float(res.x[i * t + j])
            if amount > 0.005:
                payments.setdefault(b.bill_id, []).append((d, amount))
    return evaluate_plan(
        s,
        payments,
        "Intelligent optimization",
        [
            "MILP maximizes modeled penalty reduction under cumulative cash, bill amount, minimum-payment, and non-partial constraints.",
            f"Consequence weights used: late fee {weights.get('late_fee',1):g}, interest {weights.get('interest',1):g}, critical consequence {weights.get('critical',1):g}.",
        ],
        weights=weights,
    )


def evaluate_plan(
    s: Scenario,
    allocations: dict[str, list[tuple[dt.date, float]]],
    strategy: str,
    extra_explanation: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> PlanResult:
    late_total = interest_total = risk_total = unpaid_total = 0.0
    critical = 0
    details = []
    all_pay = []
    for b in s.bills:
        p = sorted(allocations.get(b.bill_id, []), key=lambda x: x[0])
        paid = min(float(b.amount), sum(max(0, a) for _, a in p))
        remaining = max(0, float(b.amount) - paid)
        unpaid_total += remaining
        by_penalty = sum(a for d, a in p if d <= _penalty_date(b))
        late = max(0, b.late_fee) * (
            max(0, b.amount - by_penalty) / max(b.amount, 0.01)
        )
        # Simple APR daily accrual on unpaid principal from effective due until payment/horizon; not a lender quote.
        horizon = s.as_of + dt.timedelta(days=s.horizon_days)
        cursor = max(b.effective_due, s.as_of)
        bal = float(b.amount)
        interest = 0.0
        for d, a in p:
            if d <= cursor:
                bal = max(0, bal - a)
                continue
            days = max(0, (min(d, horizon) - cursor).days)
            interest += bal * max(0, b.apr) * days / 365
            bal = max(0, bal - a)
            cursor = min(d, horizon)
        days = max(0, (horizon - cursor).days)
        interest += bal * max(0, b.apr) * days / 365
        unpaid_at_risk = max(0, b.amount - sum(a for d, a in p if d <= _risk_date(b)))
        risk = max(0, b.critical_risk) * unpaid_at_risk / max(b.amount, 0.01)
        late_total += late
        interest_total += interest
        risk_total += risk
        if unpaid_at_risk > 0.01 and b.critical_risk > 0:
            critical += 1
        if paid > 0:
            for d, a in p:
                all_pay.append(
                    {
                        "bill_id": b.bill_id,
                        "bill": b.name,
                        "provider": b.provider,
                        "date": d,
                        "amount": round(a, 2),
                        "paid_total": round(paid, 2),
                        "remaining": round(remaining, 2),
                    }
                )
        details.append((b, paid, remaining, late, interest, risk, unpaid_at_risk))
    weights = weights or {"late_fee": 1.0, "interest": 1.0, "critical": 1.0}
    total = (
        late_total * weights.get("late_fee", 1.0)
        + interest_total * weights.get("interest", 1.0)
        + risk_total * weights.get("critical", 1.0)
    )
    allocated = sum(x["amount"] for x in all_pay)
    ending = max(
        0, s.available_cash - s.reserve + sum(i.amount for i in s.incomes) - allocated
    )
    explanations = list(extra_explanation or [])
    for b, paid, remaining, late, interest, risk, unpaidrisk in details:
        if paid > 0.01:
            explanations.append(
                f"{b.name}: allocate ${paid:,.2f} of ${b.amount:,.2f}; estimated ${late:,.2f} fee, ${interest:,.2f} interest, and ${risk:,.2f} consequence-weight exposure remain in the model. Effective due {b.effective_due.isoformat()}; {b.consequence}"
            )
        else:
            why = "cash is preserved for obligations with greater modeled harm per dollar or unavailable before this deadline"
            explanations.append(
                f"{b.name}: defer/seek arrangement; ${b.amount:,.2f} remains. This is not a guarantee of no impact; {why}. {b.consequence}"
            )
    # Validate all allocations against cash at dates and account rules.
    feasible = True
    for d in _payment_events(s):
        spent = sum(a for vals in allocations.values() for pdte, a in vals if pdte <= d)
        if spent > _available_by_date(s, d) + 0.011:
            feasible = False
    for b in s.bills:
        paid = sum(a for d, a in allocations.get(b.bill_id, []))
        paid_by_due = sum(
            a for d, a in allocations.get(b.bill_id, []) if d <= b.effective_due
        )
        if (
            paid > b.amount + 0.011
            or (paid > 0.01 and paid + 0.011 < min(b.minimum_payment, b.amount))
            or (
                paid_by_due > 0.01
                and paid_by_due + 0.011 < min(b.minimum_payment, b.amount)
            )
            or (
                not b.partial_allowed
                and paid > 0.01
                and (
                    abs(paid - b.amount) > 0.011
                    or len(allocations.get(b.bill_id, [])) > 1
                )
            )
        ):
            feasible = False
    return PlanResult(
        strategy,
        all_pay,
        {
            "late_fees": round(late_total, 2),
            "interest": round(interest_total, 2),
            "critical_harm": round(risk_total, 2),
            "total_harm": round(total, 2),
        },
        round(allocated, 2),
        round(ending, 2),
        round(unpaid_total, 2),
        critical,
        feasible,
        explanations,
    )


# -------------------------- baseline_strategies ----------------------------
def baseline(
    s: Scenario, policy: str, weights: dict[str, float] | None = None
) -> PlanResult:
    """Shared rules for all baselines: same cash dates, minimums, partial rules and confirmed extensions."""
    rank = {
        "Earliest Due Date": lambda b: (b.effective_due, b.name),
        "Smallest Bill First": lambda b: (b.amount, b.effective_due, b.name),
        "Largest Bill First": lambda b: (-b.amount, b.effective_due, b.name),
    }
    if policy not in rank:
        raise ValueError("Unknown baseline strategy")
    dates = _payment_events(s)
    alloc: dict[str, list[tuple[dt.date, float]]] = {}
    # Funds are deployed at the earliest event on/after a bill's effective due date.
    for d in dates:
        available = max(
            0,
            _available_by_date(s, d)
            - sum(a for vals in alloc.values() for pdte, a in vals if pdte <= d),
        )
        candidates = sorted(
            [
                b
                for b in s.bills
                if b.effective_due <= d
                and sum(a for _, a in alloc.get(b.bill_id, [])) < b.amount - 0.01
            ],
            key=rank[policy],
        )
        for b in candidates:
            if available <= 0.005:
                break
            already = sum(a for _, a in alloc.get(b.bill_id, []))
            remaining = max(0, b.amount - already)
            if not b.partial_allowed:
                if available + 0.005 >= remaining:
                    amount = remaining
                else:
                    continue
            else:
                amount = min(remaining, available)
                minimum = max(0, b.minimum_payment - already)
                if amount + 0.005 < minimum:
                    continue
            if amount > 0:
                alloc.setdefault(b.bill_id, []).append((d, amount))
                available -= amount
    return evaluate_plan(
        s,
        alloc,
        policy,
        [
            f"Baseline order: {policy}. It uses identical minimum, partial, extension, cash-timing, and cost-evaluation rules; it does not optimize consequence weights."
        ],
        weights=weights,
    )


def run_all_strategies(
    s: Scenario, weights: dict[str, float] | None = None
) -> list[PlanResult]:
    return [
        baseline(s, n, weights)
        for n in ("Earliest Due Date", "Smallest Bill First", "Largest Bill First")
    ] + [optimize(s, weights)]


def plan_table(results: list[PlanResult]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Strategy": r.strategy,
                "Modeled harm ($-equivalent)": r.harm["total_harm"],
                "Late fees": r.harm["late_fees"],
                "Interest estimate": r.harm["interest"],
                "Critical consequences": r.critical_count,
                "Unpaid obligations": r.unpaid,
                "Cash allocated": r.total_allocated,
                "Remaining cash": r.remaining_cash,
                "Fully paid": r.feasible and r.unpaid < 0.01,
            }
            for r in results
        ]
    )


# -------------------------- simulation_engine ------------------------------
def simulate_delay(
    s: Scenario, bill_name: str, days: int
) -> tuple[Scenario, list[PlanResult]]:
    changed = copy.deepcopy(s)
    target = next(
        (
            b
            for b in changed.bills
            if bill_name.lower() in b.name.lower()
            or bill_name.lower() in b.provider.lower()
        ),
        None,
    )
    if target is None:
        return changed, run_all_strategies(changed)
    target.due_date += dt.timedelta(days=int(days))
    target.confirmed_extension = True
    target.extension_date = target.due_date
    target.extension_terms = f"What-if only: due date shifted {days} days; not a provider-confirmed extension."
    return changed, run_all_strategies(changed)


def simulate_late_payment(bill: Bill, days_late: int) -> tuple[PlanResult, PlanResult]:
    """Isolated on-time vs late bill cost estimate; actual cash/provider outcomes remain uncertain."""
    late_date = bill.effective_due + dt.timedelta(days=max(0, int(days_late)))
    horizon = max(40, (late_date - AS_OF).days + 14)
    s = Scenario(max(0, bill.amount), AS_OF, [copy.deepcopy(bill)], [], 0, horizon)
    on_time = evaluate_plan(
        s,
        {bill.bill_id: [(bill.effective_due, bill.amount)]},
        "Illustrative on-time payment",
    )
    delayed = evaluate_plan(
        s,
        {bill.bill_id: [(late_date, bill.amount)]},
        f"Illustrative payment {days_late} days late",
    )
    return on_time, delayed


# ------------------------- bill_extraction ---------------------------------
DATE_PATTERNS = [
    r"(?:due\s+date|payment\s+due|due)\s*[:#-]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
]


def _parse_date(s: str) -> dt.date | None:
    s = s.strip().replace(",", "")
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y", "%B %d %Y", "%b %d %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def extract_bill_fields(text: str) -> dict[str, Any]:
    """Conservative regex extraction; nulls mean unknown and must not be treated as zero."""
    raw = text or ""
    lines = [x.strip() for x in raw.splitlines() if x.strip()]

    def money(patterns):
        for pat in patterns:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                try:
                    return round(float(m.group(1).replace(",", "")), 2)
                except ValueError:
                    pass
        return None

    provider = None
    for line in lines[:5]:
        cleaned = re.sub(
            r"\b(?:bill|statement|account|invoice)\b", "", line, flags=re.IGNORECASE
        ).strip(" :-")
        if (
            cleaned
            and not re.search(
                r"(due date|amount due|balance due|minimum payment)",
                cleaned,
                re.IGNORECASE,
            )
            and len(cleaned) < 80
        ):
            provider = cleaned
            break
    due = None
    for pat in DATE_PATTERNS:
        m = re.search(pat, raw, re.IGNORECASE)
        if m and (due := _parse_date(m.group(1))):
            break
    amount = money(
        [
            r"(?:total\s+)?amount\s+due\s*[:$ ]+\$?\s*([\d,]+(?:\.\d{2})?)",
            r"balance\s+due\s*[:$ ]+\$?\s*([\d,]+(?:\.\d{2})?)",
        ]
    )
    minimum = money([r"minimum\s+(?:payment|due)\s*[:$ ]+\$?\s*([\d,]+(?:\.\d{2})?)"])
    late = money([r"late\s+fee\s*[:$ ]+\$?\s*([\d,]+(?:\.\d{2})?)"])
    apr = None
    m = re.search(r"(?:interest\s+rate|APR)\s*[: ]+([\d.]+)\s*%", raw, re.IGNORECASE)
    if m:
        apr = round(float(m.group(1)) / 100, 6)
    grace = None
    m = re.search(
        r"(\d+)\s*(?:calendar\s+)?days?\s+(?:grace\s+period|after\s+the\s+due\s+date)",
        raw,
        re.IGNORECASE,
    )
    if m:
        grace = int(m.group(1))
    extension = None
    m = re.search(r"(?:extension|payment arrangement)[^\n]{0,90}", raw, re.IGNORECASE)
    if m:
        extension = m.group(0).strip()
    values = {
        "provider": provider,
        "amount": amount,
        "due_date": due.isoformat() if due else None,
        "minimum_payment": minimum,
        "late_fee": late,
        "apr": apr,
        "grace_days": grace,
        "extension_terms": extension,
    }
    confidence = {
        k: ("high" if v is not None else "unknown") for k, v in values.items()
    }
    # Multiple candidate amounts on the amount-due line are ambiguous, so keep the amount null.
    amount_line = re.search(r"(?:amount\s+due|balance\s+due)[^\n]*", raw, re.IGNORECASE)
    if amount_line:
        candidates = re.findall(r"\$?\s*[\d,]+(?:\.\d{2})?", amount_line.group(0))
        if len(candidates) > 1:
            values["amount"] = None
            confidence["amount"] = "review: multiple candidate amounts"
    # Ambiguous repeated monetary references elsewhere are explicitly flagged for human review.
    if (
        len(re.findall(r"\$\s*[\d,]+(?:\.\d{2})?", raw)) > 3
        and values["amount"] is not None
    ):
        confidence["amount"] = "review: multiple monetary values"
    if due and due.year < 2020:
        confidence["due_date"] = "review: unusual year"
    return {
        "fields": values,
        "confidence": confidence,
        "source_text": raw,
        "needs_confirmation": True,
    }


def read_uploaded_bill(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            return "\n".join(
                page.extract_text() or "" for page in PdfReader(str(p)).pages
            )
        except Exception as e:
            return f"PDF text extraction unavailable: {e}"
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(p))
    except Exception as e:
        return f"Image OCR unavailable ({e}). Paste the bill text instead."


# --------------------------- natural_language -------------------------------
def upcoming_frame(account: AccountStore) -> pd.DataFrame:
    rows = []
    for b in current_open_bills(account):
        days = (b.effective_due - AS_OF).days
        rows.append(
            {
                "Bill": b.name,
                "Provider": b.provider,
                "Amount": b.amount,
                "Due": b.effective_due.isoformat(),
                "Days": days,
                "Status": "Confirmed extension" if b.confirmed_extension else b.status,
                "Grace (days)": b.grace_days,
                "Extension terms": b.extension_terms,
                "Data source": b.source,
                "Modeled consequence": b.consequence,
                "Risk class": (
                    "Critical"
                    if b.critical_risk >= 300
                    else ("Elevated" if b.critical_risk > 0 else "Low")
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("Due") if rows else pd.DataFrame()


def _last_month_bounds(today=AS_OF):
    first = today.replace(day=1)
    last_prev = first - dt.timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def answer_financial_question(
    question: str, account: AccountStore = DEMO, context: list | None = None
) -> tuple[str, dict[str, Any] | None]:
    q = (question or "").strip()
    low = q.lower()
    pending = None
    if not q:
        return (
            "Ask a question about this synthetic account, or dictate one with the microphone.",
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
        result = optimize(scenario_from_account(account, reserve=0))
        first = next(
            (x for x in result.explanation if ": allocate $" in x),
            "No payment is recommended from current assumptions.",
        )
        return (
            f"Following up on your question, ‘{previous[:100]}’: {first} The model ranks avoided late fees, estimated interest, and explicit consequence weights per dollar; check the assumptions and provider terms before acting.",
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
        s = scenario_from_account(account, reserve=0)
        s.incomes.append(
            IncomeEvent(
                amount, AS_OF + dt.timedelta(days=1), "What-if additional income", False
            )
        )
        r = optimize(s)
        return (
            f"With an additional hypothetical ${amount:,.2f} tomorrow (not recorded as income), the optimized plan allocates ${r.total_allocated:,.2f}, leaves ${r.unpaid:,.2f} unpaid, and has modeled harm ${r.harm['total_harm']:,.2f}. The account itself is unchanged.",
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
            s = scenario_from_account(account, reserve=0)
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
                f"If the expected ${amount:,.2f} paycheck arrives {days} days later than {payday}, the re-optimized plan allocates ${result.total_allocated:,.2f}, leaves ${result.unpaid:,.2f} unpaid, and models ${result.harm['total_harm']:,.2f} harm. This is a scenario, not an income prediction; account data is unchanged.",
                None,
            )
        pending = {"action": "paycheck_delay", "days": days, "date": payday.isoformat()}
        return (
            f"I interpreted this as moving the expected paycheck from {payday} to {payday+dt.timedelta(days=days)} ({days} days later). Confirm before updating planning assumptions.",
            pending,
        )
    m = re.search(r"(?:received|got|earned)\s+\$?([\d,]+(?:\.\d{1,2})?)", low)
    if m:
        amount = float(m.group(1).replace(",", ""))
        pending = {
            "action": "income",
            "amount": amount,
            "date": AS_OF.isoformat(),
            "description": "User-reported income",
        }
        return (
            f"I interpreted that as a ${amount:,.2f} deposit to checking dated today ({AS_OF}). Confirm before I record it.",
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
            f"I interpreted that as a ${amount:,.2f} decrease in checking. Confirm before I record the adjustment.",
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
                f"I interpreted this as a provider-approved {days}-day extension for {b.name} ({b.provider}). Confirm to update its due date. Only confirmed extensions are used by the optimizer.",
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
                f"I interpreted this as a ${amt:,.2f} payment toward {b.name}. Confirm to record it and reduce the open obligation.",
                pending,
            )
    if any(w in low for w in ["how much money", "balance", "checking", "savings"]):
        return (
            f"As of {AS_OF:%B %d, %Y}, checking is ${account.balance('Checking'):,.2f}, savings is ${account.balance('Savings'):,.2f}, total cash is ${account.balance('Checking')+account.balance('Savings'):,.2f}. The demo data is synthetic.",
            None,
        )
    if any(w in low for w in ["due this week", "upcoming", "bills due", "due soon"]):
        df = upcoming_frame(account)
        week = df[df.Days <= 7] if not df.empty else df
        if week.empty:
            return (
                "No recorded obligations are due in the next seven days in this account snapshot.",
                None,
            )
        short = "; ".join(
            f"{r['Bill']} ${r['Amount']:,.2f} on {r['Due']}" for _, r in week.iterrows()
        )
        return (
            f"Recorded bills due within seven days: {short}. Check provider notices for exact terms.",
            None,
        )
    if any(w in low for w in ["priorit", "pay first", "what should i pay"]):
        s = scenario_from_account(account, reserve=0)
        result = optimize(s)
        names = []
        for b in s.bills:
            total = sum(
                x["amount"] for x in result.payments if x["bill_id"] == b.bill_id
            )
            if total > 0:
                names.append(f"{b.name} ${total:,.0f}")
        return (
            "The consequence model recommends allocating available checking cash across "
            + (", ".join(names) if names else "none right now")
            + f". Modeled harm is ${result.harm['total_harm']:,.2f} ($-equivalent, including estimates); {result.unpaid:,.2f} remains unpaid. Review the assumptions and unknown provider consequences before acting."
        ), None
    if any(w in low for w in ["spend", "expenses", "grocery", "groceries"]):
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
        detail = (
            ", ".join(f"{k} ${v:,.0f}" for k, v in cats.items())
            or "no category records"
        )
        return (
            f"Recorded spending in {start:%B %Y} was ${total:,.2f}; the largest categories were {detail}. Transfers are excluded to avoid counting savings movements as spending.",
            None,
        )
    if any(w in low for w in ["debt", "owe"]):
        d = account.debts()
        return (
            "Latest recorded debt estimates: "
            + ", ".join(f"{k} ${v:,.0f}" for k, v in d.items())
            + f"; total ${sum(d.values()):,.0f}. Loan balances are synthetic ledger estimates and should be verified with servicers.",
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
            ontime, late_result = simulate_late_payment(bill, delay)
            return (
                f"Isolated what-if for {bill.name}: paying ${bill.amount:,.2f} {delay} days after its {bill.effective_due} effective due date models late fee ${late_result.harm['late_fees']:,.2f}, simple-interest estimate ${late_result.harm['interest']:,.2f}, and consequence-weight exposure ${late_result.harm['critical_harm']:,.2f} (total ${late_result.harm['total_harm']:,.2f}). A same-day payment model totals ${ontime.harm['total_harm']:,.2f}. The late-fee rule is prorated in this prototype; actual grace periods, provider actions, and legal protections must be confirmed.",
                None,
            )
        if bill:
            s = scenario_from_account(account, reserve=0)
            _changed, results = simulate_delay(s, bill.name, delay)
            r = results[-1]
            return (
                f"In a what-if only (not a confirmed extension), shifting {bill.name} by {delay} days gives optimized modeled harm ${r.harm['total_harm']:,.2f}, with ${r.unpaid:,.2f} unpaid. Fees and consequences depend on the provider's actual terms; the model cannot confirm whether service or credit reporting changes.",
                None,
            )
    if any(w in low for w in ["paycheck", "income"]):
        upcoming = [
            r
            for r in account.records["income_history"].to_dict("records")
            if r["date"].date() <= AS_OF
        ]
        recent = sum(
            x["amount"]
            for x in upcoming
            if x["date"].date() >= AS_OF - dt.timedelta(days=30)
        )
        return (
            f"Recorded income in the last 30 days is ${recent:,.2f}. The next expected paycheck is a user scenario input, not guaranteed; enter its amount and date in Financial Situation before simulating it.",
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
        f"I can answer from this account's transaction, bill, income, debt, and optimization records. Current checking is ${account.balance('Checking'):,.2f}; ask about bills due, spending, debt, savings, or a what-if scenario. {DISCLAIMER}",
        None,
    )


def confirm_account_update(
    pending: dict | None, approve: bool, account: AccountStore = DEMO
) -> str:
    if not pending:
        return "No pending financial change to confirm."
    if not approve:
        return "No change made."
    action = pending.get("action")
    if action == "income":
        account.add_transaction(
            pending["amount"],
            "Income",
            "User-reported income",
            pending["description"],
            account="Checking",
            tx_type="Income",
            method="Voice/text confirmed",
        )
        return f"Confirmed: ${pending['amount']:,.2f} added to checking. Recommendations now use the updated balance."
    if action == "cash_reduction":
        amt = float(pending["amount"])
        if amt > account.balance("Checking"):
            return "Cannot record a reduction larger than the recorded checking balance. Nothing changed."
        account.add_transaction(
            -amt,
            "Other expenses",
            "Available cash adjustment",
            pending["description"],
            account="Checking",
            tx_type="Adjustment",
            method="Voice/text confirmed",
        )
        return f"Confirmed: checking reduced by ${amt:,.2f}."
    if action == "paycheck_delay":
        old = pending.get("date")
        try:
            new = dt.date.fromisoformat(old) + dt.timedelta(
                days=int(pending.get("days", 5))
            )
        except Exception:
            new = AS_OF + dt.timedelta(days=int(pending.get("days", 5)))
        account.preferences["payday"] = new
        account.version += 1
        return f"Confirmed: expected paycheck planning date moved to {new}. No deposit was recorded."
    if action == "extension":
        b = account.find_bill(pending["bill_id"])
        if b:
            b.confirmed_extension = True
            b.extension_date = b.due_date + dt.timedelta(days=int(pending["days"]))
            b.extension_terms = (
                f"User-confirmed provider approval: +{pending['days']} days"
            )
            account.version += 1
            return f"Confirmed: {b.name} due date updated to {b.extension_date}. The optimizer will use this confirmed extension."
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
            account="Checking",
            tx_type="Payment",
            method="Voice/text confirmed",
            recurrence="One-time",
        )
        if b.name == "Credit Card Minimum":
            account.adjust_debt("Credit Card", -amt)
        elif b.name == "Auto Loan":
            account.adjust_debt("Auto Loan", -amt * 0.76)
        elif b.name == "Student Loan":
            account.adjust_debt("Student Loan", -amt * 0.88)
        account.record_bill_payment(b, amt)
        b.amount = round(b.amount - amt, 2)
        account.version += 1
        b.status = "Paid" if b.amount < 0.01 else "Partially paid"
        return f"Confirmed: ${amt:,.2f} payment recorded; remaining amount on {b.name} is ${b.amount:,.2f}."
    return "Unsupported update; nothing changed."


# ----------------------------- voice ---------------------------------------
def transcribe_audio(path: str | None) -> str:
    if not path:
        return ""
    try:
        from faster_whisper import WhisperModel

        global _WHISPER_MODEL
        if "_WHISPER_MODEL" not in globals():
            _WHISPER_MODEL = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, _ = _WHISPER_MODEL.transcribe(path, beam_size=3)
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        return f"[Transcription unavailable: {e}. Install faster-whisper and retry, or type your question.]"


def speech_file(text: str) -> str | None:
    try:
        from gtts import gTTS

        path = os.path.join(
            tempfile.gettempdir(), f"solvra-speech-{uuid.uuid4().hex[:8]}.mp3"
        )
        gTTS(text=text[:1200], lang="en", slow=False).save(path)
        return path
    except Exception:
        return None


# -------------------------- evaluation / testing ----------------------------
def generate_evaluation_scenarios(
    seed: int = 314159,
) -> tuple[list[Scenario], list[str]]:
    rng = random.Random(seed)
    scenarios = []
    labels = []
    start = dt.date(2026, 1, 1)
    names = [
        ("Rent", "Housing", 1200, 1550, 950, "Housing stability risk", 700),
        (
            "Electricity",
            "Utilities",
            70,
            220,
            380,
            "Potential service interruption",
            250,
        ),
        (
            "Credit Card",
            "Debt payments",
            75,
            500,
            35,
            "Interest and credit-reporting risk",
            200,
        ),
        ("Auto Insurance", "Insurance", 90, 230, 22, "Coverage lapse risk", 550),
        ("Phone", "Utilities", 35, 120, 12, "Service interruption risk", 130),
        ("Medical", "Medical", 40, 420, 0, "Collection/plan terms uncertain", 100),
        ("Auto Loan", "Debt payments", 180, 420, 28, "Credit and vehicle risk", 500),
        ("Internet", "Utilities", 45, 110, 12, "Service restriction risk", 90),
    ]
    for idx in range(500):
        asof = start + dt.timedelta(days=idx % 270)
        count = rng.randint(3, 6)
        chosen = rng.sample(names, count)
        bills = []
        for j, (name, cat, lo, hi, fee, cons, risk) in enumerate(chosen):
            amount = round(rng.uniform(lo, hi), 2)
            due = asof + dt.timedelta(days=rng.randint(0, 15))
            grace = rng.choice([0, 3, 5, 10, 21]) if cat != "Housing" else 0
            ext = idx % 7 == 0 and j == 0
            b = Bill(
                f"S{idx}-{j}",
                name,
                name,
                cat,
                amount,
                due,
                (
                    round(min(amount, rng.uniform(20, 60)), 2)
                    if cat in ("Debt payments", "Utilities")
                    else 0
                ),
                fee,
                rng.choice([0, 0.05, 0.12, 0.249]),
                grace,
                cons,
                float(risk),
                rng.randint(3, 15),
                ext,
                due + dt.timedelta(days=5) if ext else None,
                "synthetic confirmed extension" if ext else "",
                rng.random() > 0.18,
            )
            bills.append(b)
        cash = round(rng.uniform(150, 1800), 2)
        # Ensure designated difficult cases and income timing patterns occur in every split.
        if idx % 5 == 0:
            cash = round(rng.uniform(100, 450), 2)
        if idx % 9 == 0 and bills:
            bills[0].amount = round(rng.uniform(300, 850), 2)
            bills[0].critical_risk = 700
            bills[0].category = "Housing"
        incomes = []
        if idx % 4 == 0:
            incomes.append(
                IncomeEvent(
                    round(rng.uniform(350, 1200), 2),
                    asof + dt.timedelta(days=rng.randint(5, 20)),
                    "Paycheck after some deadlines",
                    False,
                )
            )
        elif idx % 4 == 1:
            incomes.append(
                IncomeEvent(
                    round(rng.uniform(250, 800), 2),
                    asof + dt.timedelta(days=1),
                    "Expected paycheck",
                    False,
                )
            )
        scenarios.append(
            Scenario(cash, asof, bills, incomes, round(rng.uniform(0, 250), 2), 35)
        )
        labels.append("held-out test" if idx >= 350 else "development")
    return scenarios, labels


EVALUATION_CACHE: tuple[pd.DataFrame, pd.DataFrame] | None = None


def evaluate_benchmarks(force: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    global EVALUATION_CACHE
    if EVALUATION_CACHE is not None and not force:
        return EVALUATION_CACHE
    scenarios, labels = generate_evaluation_scenarios()
    rows = []
    # Performance reporting is exclusively held-out; development scenarios remain separated and are never used for tuning.
    for idx, (s, label) in enumerate(zip(scenarios, labels)):
        if label != "held-out test":
            continue
        for result in run_all_strategies(s):
            rows.append(
                {
                    "scenario_id": f"T{idx-350+1:03d}",
                    "strategy": result.strategy,
                    "harm": result.harm["total_harm"],
                    "late_fees": result.harm["late_fees"],
                    "interest": result.harm["interest"],
                    "critical_harm": result.harm["critical_harm"],
                    "critical_count": result.critical_count,
                    "unpaid": result.unpaid,
                    "allocated": result.total_allocated,
                    "remaining_cash": result.remaining_cash,
                    "feasible": bool(result.feasible and result.unpaid < 0.01),
                }
            )
    detail = pd.DataFrame(rows)
    baseline_mean = detail[detail.strategy == "Earliest Due Date"].harm.mean()
    summary = detail.groupby("strategy", as_index=False).agg(
        average_modeled_harm=("harm", "mean"),
        average_late_fees=("late_fees", "mean"),
        average_interest=("interest", "mean"),
        average_critical_harm=("critical_harm", "mean"),
        critical_consequence_count=("critical_count", "sum"),
        average_unpaid=("unpaid", "mean"),
        feasibility_rate=("feasible", "mean"),
        average_cash_allocated=("allocated", "mean"),
    )
    summary["relative_harm_reduction_vs_earliest_due"] = (
        baseline_mean - summary.average_modeled_harm
    ) / max(baseline_mean, 1e-9)
    EVALUATION_CACHE = (summary, detail)
    return summary, detail


def extraction_test_suite() -> tuple[pd.DataFrame, dict[str, float]]:
    examples = [
        (
            "ComEd\nAmount Due: $148.60\nDue Date: 11/16/2026\nMinimum Payment: $25.00\nLate Fee: $18.00\nAPR: 18%\n5 day grace period",
            {
                "amount": 148.60,
                "due_date": "2026-11-16",
                "minimum_payment": 25.0,
                "late_fee": 18.0,
                "apr": 0.18,
                "grace_days": 5,
            },
        ),
        (
            "Harbor Bank Card Statement\nBalance Due: $426.20\nPayment Due: November 28, 2026\nMinimum Payment: $45.00\nLate fee: $35.00\nInterest rate: 24.9%",
            {
                "amount": 426.20,
                "due_date": "2026-11-28",
                "minimum_payment": 45.0,
                "late_fee": 35.0,
                "apr": 0.249,
            },
        ),
        (
            "Clinic Invoice\nAmount Due $82.00\nDue: 12/02/2026\nPayment arrangement available by calling provider",
            {"amount": 82.0, "due_date": "2026-12-02"},
        ),
        (
            "Utility Statement\nAmount Due: $140 or $160\nDue Date: 11/30/2026\nLate fee: not shown",
            {"amount": None, "due_date": "2026-11-30"},
        ),
        (
            "Unusual account\nBalance Due: $0.00\nDue date: 13/45/2026\nMinimum Payment $0.00",
            {"amount": 0.0, "due_date": None, "minimum_payment": 0.0},
        ),
    ]
    rows = []
    correct = total = 0
    for i, (text, truth) in enumerate(examples, 1):
        result = extract_bill_fields(text)["fields"]
        for key, expected in truth.items():
            got = result.get(key)
            ok = got == expected
            rows.append(
                {
                    "sample": i,
                    "field": key,
                    "expected": expected,
                    "extracted": got,
                    "correct": ok,
                }
            )
            correct += int(ok)
            total += 1
    df = pd.DataFrame(rows)
    return df, {"field_accuracy": correct / max(1, total), "fields_tested": total}


# ------------------------------- reporting ---------------------------------
def personal_report(account: AccountStore, days: int | None = 365) -> pd.DataFrame:
    tx = account.transactions.copy()
    if days is not None:
        tx = tx[tx.date >= pd.Timestamp(AS_OF - dt.timedelta(days=days))]
    tx["month"] = tx.date.dt.to_period("M").astype(str)
    tx["income"] = np.where((tx.category == "Income") & (tx.amount > 0), tx.amount, 0)
    tx["expense"] = np.where(
        (tx.amount < 0) & (~tx.category.isin(["Transfers", "Income"])), -tx.amount, 0
    )
    out = tx.groupby("month", as_index=False).agg(
        income=("income", "sum"), expenses=("expense", "sum")
    )
    out["net_cash_flow"] = out.income - out.expenses
    balances = account.records["balance_history"].copy()
    debts = account.records["debt_history"].copy()
    balances["month"] = balances.month.dt.to_period("M").astype(str)
    debts["month"] = debts.month.dt.to_period("M").astype(str)
    out = out.merge(
        balances[["month", "checking", "savings", "total_cash"]], on="month", how="left"
    ).merge(
        debts[["month", "total_debt", "Credit Card", "Auto Loan", "Student Loan"]],
        on="month",
        how="left",
    )
    hist = account.records["bill_history"].copy()
    if not hist.empty:
        hist["month"] = (
            pd.to_datetime(hist.payment_date, errors="coerce")
            .dt.to_period("M")
            .astype(str)
        )
        late = (
            hist[hist.status.str.contains("late", case=False, na=False)]
            .groupby("month")
            .size()
            .rename("late_payments")
            .reset_index()
        )
        out = out.merge(late, on="month", how="left")
    if "late_payments" not in out:
        out["late_payments"] = 0
    out["late_payments"] = out.late_payments.fillna(0).astype(int)
    return out


def report_support_tables(account: AccountStore, days: int | None):
    start = (
        AS_OF - dt.timedelta(days=days) if days is not None else dt.date(2024, 11, 15)
    )
    cats = category_spending(account, start, AS_OF)
    hist = account.records["bill_history"].copy()
    if not hist.empty:
        dates = pd.to_datetime(hist.payment_date, errors="coerce").dt.date
        hist = hist[(dates.isna()) | (dates >= start)]
    _score, factors, explanation = health_assessment(account)
    return (
        cats,
        (
            hist.sort_values("due_date", ascending=False).head(200)
            if not hist.empty
            else hist
        ),
        upcoming_frame(account),
        factors,
        financial_insights(account),
        explanation,
    )


def export_personal_csv(account: AccountStore, days: int | None) -> str:
    report = personal_report(account, days)
    path = os.path.join(
        tempfile.gettempdir(), f"solvra-personal-report-{uuid.uuid4().hex[:7]}.csv"
    )
    report.to_csv(path, index=False)
    return path


def export_category_csv(account: AccountStore, days: int | None) -> str:
    start = (
        AS_OF - dt.timedelta(days=days) if days is not None else dt.date(2024, 11, 15)
    )
    out = category_spending(account, start, AS_OF)
    path = os.path.join(
        tempfile.gettempdir(), f"solvra-category-report-{uuid.uuid4().hex[:7]}.csv"
    )
    out.to_csv(path, index=False)
    return path


def export_personal_pdf(account: AccountStore, days: int | None) -> str:
    path = os.path.join(
        tempfile.gettempdir(), f"solvra-personal-report-{uuid.uuid4().hex[:7]}.pdf"
    )
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(path, pagesize=letter)
        y = 750
        c.setFont("Helvetica-Bold", 16)
        c.drawString(48, y, "Solvra — Synthetic personal financial report")
        y -= 24
        c.setFont("Helvetica", 9)
        c.drawString(48, y, f"As of {AS_OF.isoformat()} | {DISCLAIMER}")
        y -= 24
        c.drawString(
            48,
            y,
            f"Checking ${account.balance('Checking'):,.2f} | Savings ${account.balance('Savings'):,.2f} | Debt ${sum(account.debts().values()):,.2f}",
        )
        y -= 22
        score, _, _health_text = health_assessment(account)
        c.drawString(
            48,
            y,
            f"Health index {score}/100 (transparent weighted prototype assessment; not credit score)",
        )
        y -= 16
        c.drawString(
            48, y, "Monthly cash flow, balances, debt trend, and late payment counts:"
        )
        y -= 15
        for _, r in personal_report(account, days).tail(16).iterrows():
            c.drawString(
                48,
                y,
                f"{r['month']}: income ${r['income']:,.0f} | expenses ${r['expenses']:,.0f} | net ${r['net_cash_flow']:,.0f} | savings ${r['savings'] if pd.notna(r['savings']) else 0:,.0f} | debt ${r['total_debt'] if pd.notna(r['total_debt']) else 0:,.0f} | late bills {r['late_payments']}",
            )
            y -= 14
            if y < 80:
                c.showPage()
                y = 750
                c.setFont("Helvetica", 9)
        if y < 180:
            c.showPage()
            y = 750
            c.setFont("Helvetica", 9)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(48, y, "Spending categories and upcoming obligations")
        y -= 18
        c.setFont("Helvetica", 9)
        cats, history, upcoming, _factors, _insights, _explanation = (
            report_support_tables(account, days)
        )
        for _, r in cats.head(10).iterrows():
            c.drawString(48, y, f"{r['category']}: ${r['spending']:,.2f}")
            y -= 13
        for _, r in upcoming.head(9).iterrows():
            if y < 70:
                c.showPage()
                y = 750
                c.setFont("Helvetica", 9)
            c.drawString(
                48,
                y,
                f"Due {r['Due']}: {r['Bill']} ${r['Amount']:,.2f} ({r['Days']} days)",
            )
            y -= 13
        c.drawString(
            48,
            max(50, y - 8),
            f"Historical late payments recorded: {int(history.status.str.contains('late', case=False, na=False).sum())}",
        )
        c.save()
    except Exception as e:
        # Still provide a valid text report if reportlab isn't installed.
        with open(path, "w") as f:
            f.write(
                f"Solvra financial report\n{DISCLAIMER}\n{e}\n"
                + personal_report(account, days).to_string(index=False)
            )
    return path


# ---------------------------- interface helpers -----------------------------
def money(x):
    return f"${float(x):,.2f}"


def dashboard_kpis(account: AccountStore, days: int = 90) -> str:
    checking = account.balance("Checking")
    savings = account.balance("Savings")
    debts = account.debts()
    monthly = monthly_summary(account)
    cur = monthly[monthly.month.dt.to_period("M") == pd.Period(AS_OF, freq="M")]
    if cur.empty:
        cur = monthly.tail(1)
    mi = float(cur.income.iloc[0]) if not cur.empty else 0
    me = float(cur.expenses.iloc[0]) if not cur.empty else 0
    obligations = sum(b.amount for b in current_open_bills(account))
    emergency = essential_monthly_expense(account)
    score, _, _ = health_assessment(account)
    items = [
        ("Checking", money(checking)),
        ("Savings", money(savings)),
        ("Total available cash", money(checking + savings)),
        ("Monthly income", money(mi)),
        ("Monthly expenses", money(me)),
        ("Remaining monthly cash flow", money(mi - me)),
        ("Outstanding debt", money(sum(debts.values()))),
        ("Upcoming obligations", money(obligations)),
        ("Emergency savings", money(savings)),
        ("Savings coverage", f"{savings/max(emergency,1):.1f} months"),
        ("Health index", f"{score}/100"),
    ]
    return (
        "<div class='kpi-grid'>"
        + "".join(
            f"<div class='kpi'><div class='kpi-label'>{a}</div><div class='kpi-value'>{b}</div></div>"
            for a, b in items
        )
        + "</div>"
    )


def _period_start(series: pd.Series, days: int | None) -> pd.Series:
    """Use daily bins for 30 days, weekly bins for 90 days, and months otherwise."""
    if days is not None and days <= 30:
        return series.dt.floor("D")
    if days is not None and days <= 90:
        return series.dt.to_period("W-SUN").dt.start_time
    return series.dt.to_period("M").dt.start_time


def _activity_for_range(account: AccountStore, days: int | None) -> pd.DataFrame:
    tx = account.transactions.copy()
    if days is not None:
        cutoff = pd.Timestamp(AS_OF - dt.timedelta(days=days - 1))
        tx = tx[(tx.date >= cutoff) & (tx.date <= pd.Timestamp(AS_OF))]
    tx["income"] = np.where((tx.category == "Income") & (tx.amount > 0), tx.amount, 0.0)
    tx["expenses"] = np.where(
        (tx.amount < 0) & (~tx.category.isin(["Transfers", "Income"])), -tx.amount, 0.0
    )
    tx["period"] = _period_start(tx.date, days)
    result = tx.groupby("period", as_index=False).agg(
        income=("income", "sum"), expenses=("expenses", "sum")
    )
    result["net"] = result.income - result.expenses
    return result.sort_values("period")


def _cash_history_for_range(account: AccountStore, days: int | None) -> pd.DataFrame:
    if days is None or days > 90:
        history = account.records["balance_history"].copy()
        if days is not None:
            cutoff = pd.Timestamp(AS_OF - dt.timedelta(days=days - 1))
            before = history[history.month < cutoff].tail(1)
            after = history[history.month >= cutoff]
            history = (
                pd.concat([before, after]).drop_duplicates("month").sort_values("month")
            )
        return history.rename(columns={"month": "date"})

    first_day = AS_OF - dt.timedelta(days=days - 1)
    dates = pd.date_range(first_day, AS_OF, freq="D")
    tx = account.transactions.copy()
    result = pd.DataFrame({"date": dates})
    for ledger_name, column in (("Checking", "checking"), ("Savings", "savings")):
        ledger = tx[tx.account == ledger_name]
        starting = (
            account.records["opening"][ledger_name]
            + ledger.loc[ledger.date.dt.date < first_day, "amount"].sum()
        )
        daily = (
            ledger[ledger.date.dt.date >= first_day]
            .groupby(ledger.date.dt.floor("D"))
            .amount.sum()
        )
        result[column] = float(starting) + result.date.map(daily).fillna(0).cumsum()
    result["total_cash"] = result.checking + result.savings
    return result


def _debt_history_for_range(account: AccountStore, days: int | None) -> pd.DataFrame:
    history = account.records["debt_history"].copy()
    if days is not None and days <= 90:
        cutoff = pd.Timestamp(AS_OF - dt.timedelta(days=days - 1))
        before = history[history.month < cutoff].tail(1)
        after = history[history.month >= cutoff]
        history = (
            pd.concat([before, after]).drop_duplicates("month").sort_values("month")
        )
    elif days is not None:
        cutoff = (
            pd.Timestamp(AS_OF - dt.timedelta(days=days - 1))
            .to_period("M")
            .to_timestamp()
        )
        before = history[history.month < cutoff].tail(1)
        history = pd.concat([before, history[history.month >= cutoff]])
    return history.rename(columns={"month": "date"})


def dashboard_charts(account: AccountStore, range_name: str):
    """Return six charts whose filters use exact dates and whose bins match the selected range."""
    days = {
        "Last 30 days": 30,
        "Last 90 days": 90,
        "Last 6 months": 183,
        "Last 12 months": 365,
        "Entire 24-month history": None,
    }.get(range_name, 90)
    start = (
        AS_OF - dt.timedelta(days=days - 1)
        if days is not None
        else dt.date(2024, 11, 15)
    )
    activity = _activity_for_range(account, days)
    categories = category_spending(account, start, AS_OF)
    palette = [
        "#147D73",
        "#E27B60",
        "#5475C8",
        "#9A83C8",
        "#D3A34F",
        "#5E9BA3",
        "#C96A88",
    ]

    cashflow = go.Figure()
    cashflow.add_trace(
        go.Bar(
            x=activity.period, y=activity.income, name="Income", marker_color="#168C7E"
        )
    )
    cashflow.add_trace(
        go.Bar(
            x=activity.period,
            y=activity.expenses,
            name="Expenses",
            marker_color="#E27B60",
        )
    )
    cashflow.add_trace(
        go.Scatter(
            x=activity.period,
            y=activity.net,
            name="Net",
            mode="lines+markers",
            line={"color": "#526BC4", "width": 2.5},
            marker={"size": 6},
            yaxis="y2",
        )
    )
    cashflow.update_layout(
        title=f"Income, expenses & net · {range_name.lower()}",
        template="plotly_white",
        barmode="group",
        height=340,
        margin={"l": 24, "r": 24, "t": 62, "b": 35},
        legend={"orientation": "h", "y": 1.12, "x": 0},
        yaxis={
            "title": "Income / expenses",
            "tickprefix": "$",
            "gridcolor": "#E8EDF2",
            "rangemode": "tozero",
        },
        yaxis2={
            "title": "Net",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "tickprefix": "$",
        },
        hovermode="x unified",
        font={"family": "Inter, sans-serif", "color": "#29394D"},
    )

    if categories.empty:
        spending_pie = go.Figure().add_annotation(
            text="No recorded spending in this period", showarrow=False
        )
    else:
        spending_pie = px.pie(
            categories,
            names="category",
            values="spending",
            hole=0.58,
            color_discrete_sequence=palette,
            title="Spending mix",
        )
        spending_pie.update_traces(
            textposition="inside",
            textinfo="percent",
            hovertemplate="%{label}<br>$%{value:,.0f} · %{percent}<extra></extra>",
        )
        spending_pie.add_annotation(
            text=f"{money(categories.spending.sum())}<br><sup>total</sup>",
            showarrow=False,
            font={"size": 17, "color": "#203247"},
        )
    spending_pie.update_layout(
        template="plotly_white",
        height=340,
        margin={"l": 14, "r": 14, "t": 56, "b": 18},
        legend={"orientation": "h", "y": -0.08},
        font={"family": "Inter, sans-serif", "color": "#29394D"},
    )

    cash_history = _cash_history_for_range(account, days)
    cash_chart = go.Figure()
    cash_chart.add_trace(
        go.Scatter(
            x=cash_history.date,
            y=cash_history.checking,
            name="Checking",
            mode="lines",
            line={"color": "#5475C8", "width": 2.5},
            fill="tozeroy",
            fillcolor="rgba(84,117,200,.09)",
        )
    )
    cash_chart.add_trace(
        go.Scatter(
            x=cash_history.date,
            y=cash_history.savings,
            name="Savings",
            mode="lines",
            line={"color": "#168C7E", "width": 2.5},
            fill="tozeroy",
            fillcolor="rgba(22,140,126,.08)",
        )
    )
    cash_chart.update_layout(
        title="Checking & savings balances",
        template="plotly_white",
        height=310,
        margin={"l": 24, "r": 15, "t": 56, "b": 32},
        hovermode="x unified",
        yaxis={"tickprefix": "$", "gridcolor": "#E8EDF2", "rangemode": "tozero"},
        legend={"orientation": "h", "y": 1.1},
        font={"family": "Inter, sans-serif", "color": "#29394D"},
    )

    debt_history = _debt_history_for_range(account, days)
    debt_chart = go.Figure()
    for column, color in (
        ("Credit Card", "#E27B60"),
        ("Auto Loan", "#5475C8"),
        ("Student Loan", "#9A83C8"),
    ):
        debt_chart.add_trace(
            go.Scatter(
                x=debt_history.date,
                y=debt_history[column],
                name=column,
                mode="lines+markers",
                line={"color": color, "width": 2.5},
                marker={"size": 5},
            )
        )
    debt_chart.update_layout(
        title="Outstanding debt by account",
        template="plotly_white",
        height=310,
        margin={"l": 24, "r": 15, "t": 56, "b": 32},
        hovermode="x unified",
        yaxis={"tickprefix": "$", "gridcolor": "#E8EDF2", "rangemode": "tozero"},
        legend={"orientation": "h", "y": 1.1},
        font={"family": "Inter, sans-serif", "color": "#29394D"},
    )

    if categories.empty:
        category_bars = go.Figure().add_annotation(
            text="No recorded spending in this period", showarrow=False
        )
    else:
        category_bars = px.bar(
            categories.sort_values("spending"),
            x="spending",
            y="category",
            orientation="h",
            color="category",
            color_discrete_sequence=palette,
            title="Category totals",
        )
        category_bars.update_traces(hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>")
    category_bars.update_layout(
        template="plotly_white",
        height=310,
        showlegend=False,
        margin={"l": 12, "r": 18, "t": 56, "b": 26},
        xaxis={"tickprefix": "$", "gridcolor": "#E8EDF2", "rangemode": "tozero"},
        font={"family": "Inter, sans-serif", "color": "#29394D"},
    )

    expenses = account.transactions.copy()
    if days is not None:
        expenses = expenses[
            (expenses.date.dt.date >= start) & (expenses.date.dt.date <= AS_OF)
        ]
    expenses = expenses[
        (expenses.amount < 0) & (~expenses.category.isin(["Transfers", "Income"]))
    ].copy()
    essentials = {
        "Housing",
        "Utilities",
        "Groceries",
        "Transportation",
        "Insurance",
        "Debt payments",
        "Medical",
    }
    expenses["period"] = _period_start(expenses.date, days)
    expenses["kind"] = np.where(
        expenses.category.isin(essentials), "Essential", "Discretionary"
    )
    stacked = expenses.groupby(["period", "kind"], as_index=False).amount.sum()
    stacked["spending"] = -stacked.amount
    essential_chart = go.Figure()
    for kind, color in (("Essential", "#168C7E"), ("Discretionary", "#D3A34F")):
        part = stacked[stacked.kind == kind]
        essential_chart.add_trace(
            go.Bar(x=part.period, y=part.spending, name=kind, marker_color=color)
        )
    essential_chart.update_layout(
        title="Essential vs discretionary spending",
        template="plotly_white",
        barmode="stack",
        height=310,
        margin={"l": 24, "r": 15, "t": 56, "b": 32},
        yaxis={"tickprefix": "$", "gridcolor": "#E8EDF2", "rangemode": "tozero"},
        legend={"orientation": "h", "y": 1.1},
        font={"family": "Inter, sans-serif", "color": "#29394D"},
    )
    return (
        cashflow,
        spending_pie,
        cash_chart,
        debt_chart,
        category_bars,
        essential_chart,
    )


def financial_insights(account: AccountStore) -> str:
    tx = account.transactions.copy()
    insights = []
    cur_start, cur_end = _last_month_bounds()
    prev_end = cur_start - dt.timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    for cat in ["Groceries", "Utilities", "Housing", "Transportation"]:
        vals = []
        for a, b in [(prev_start, prev_end), (cur_start, cur_end)]:
            mask = (
                (tx.date.dt.date >= a)
                & (tx.date.dt.date <= b)
                & (tx.category == cat)
                & (tx.amount < 0)
            )
            vals.append(-tx.loc[mask, "amount"].sum())
        if vals[0] > 0:
            pct = (vals[1] - vals[0]) / vals[0] * 100
            insights.append(
                f"{cat} spending was ${vals[1]:,.0f} last month, {abs(pct):.0f}% {'higher' if pct>=0 else 'lower'} than the prior month (${vals[0]:,.0f})."
            )
    # Small, explainable scikit-learn linear trend over the six most recent utility-spend months.
    recent = tx[
        (tx.category == "Utilities") & (tx.amount < 0) & (tx.date.dt.date <= AS_OF)
    ].copy()
    recent["month"] = recent.date.dt.to_period("M").dt.to_timestamp()
    util = recent.groupby("month").amount.sum().abs().tail(6)
    if len(util) >= 3:
        model = LinearRegression().fit(np.arange(len(util)).reshape(-1, 1), util.values)
        slope = float(model.coef_[0])
        if abs(slope) >= 2:
            insights.append(
                f"A simple six-month linear trend estimates utility spending is changing by about ${abs(slope):,.0f}/month ({'up' if slope>0 else 'down'}); this is descriptive, not a forecast."
            )
    hist = account.records["balance_history"].tail(4)
    if len(hist) >= 2:
        delta = hist.savings.iloc[-1] - hist.savings.iloc[0]
        insights.append(
            f"Savings changed by ${delta:,.0f} across the last four monthly snapshots."
        )
    debt = account.records["debt_history"]
    if len(debt) >= 7:
        d = debt.iloc[-7].total_debt - debt.iloc[-1].total_debt
        insights.append(
            f"Recorded total debt {'fell' if d>=0 else 'rose'} by ${abs(d):,.0f} over six months."
        )
    months = account.balance("Savings") / max(essential_monthly_expense(account), 1)
    insights.append(
        f"Current synthetic savings balance covers about {months:.1f} months of recorded essential expenses at the recent six-month average."
    )
    return "\n".join(f"• {x}" for x in insights)


def bill_df(account: AccountStore) -> pd.DataFrame:
    rows = []
    for b in account.bills:
        rows.append(
            {
                "ID": b.bill_id,
                "Bill": b.name,
                "Provider": b.provider,
                "Category": b.category,
                "Amount": b.amount,
                "Due date": b.effective_due.isoformat(),
                "Minimum": b.minimum_payment,
                "Late fee": b.late_fee,
                "APR": b.apr,
                "Grace days": b.grace_days,
                "Partial allowed": b.partial_allowed,
                "Confirmed extension": b.confirmed_extension,
                "Extension terms": b.extension_terms,
                "Status": b.status,
                "Consequence": b.consequence,
                "Data source": b.source,
            }
        )
    return pd.DataFrame(rows)


def render_plan(result: PlanResult, scenario_bills: list[Bill] | None = None) -> str:
    byid = {
        b.bill_id: b
        for b in (
            scenario_bills if scenario_bills is not None else current_open_bills(DEMO)
        )
    }
    lines = [
        f"### {result.strategy}",
        f"**Total allocated:** ${result.total_allocated:,.2f} &nbsp; **Unallocated cash:** ${result.remaining_cash:,.2f} &nbsp; **Unpaid obligations:** ${result.unpaid:,.2f}",
        f"**Modeled harm:** ${result.harm['total_harm']:,.2f} ($-equivalent) — late fees ${result.harm['late_fees']:,.2f}; estimated interest ${result.harm['interest']:,.2f}; consequence-weight exposure ${result.harm['critical_harm']:,.2f}.",
        "#### Payment schedule",
    ]
    if not result.payments:
        lines.append(
            "No payments allocated; confirm cash inputs, available funds, and bill terms."
        )
    else:
        for p in sorted(result.payments, key=lambda x: (x["date"], x["bill"])):
            b = byid.get(p["bill_id"])
            name = p["bill"]
            due = b.effective_due.isoformat() if b else "scenario due date"
            lines.append(
                f"- **{p['date']} — {name}: ${p['amount']:,.2f}** (due {due}; provider: {p['provider']})."
            )
    lines.append("#### Why / remaining risks")
    lines.extend(
        f"- {x}" for x in result.explanation[: min(12, len(result.explanation))]
    )
    lines.append(
        "**Assumptions:** one-time late fee is prorated by unpaid fraction at the due date plus grace period; APR is simple daily interest on unpaid balance over the simulation horizon; consequence weights are explicit dollar-equivalent user-model inputs, not real loss estimates. Confirmed extensions only are treated as dates. Provider rules, legal protections, reporting, and service actions are uncertain. No payment is sent."
    )
    return "\n".join(lines)


def provider_message(bill: Bill) -> str:
    return (
        f"Hello {bill.provider}, I am contacting you about my {bill.name} bill of ${bill.amount:,.2f}, due {bill.effective_due:%B %d, %Y}. "
        "I am reviewing my available funds and want to avoid missing a payment. Could you tell me whether a short extension, payment arrangement, or partial payment is available, and confirm any fee, interest, service, or reporting consequences in writing? "
        "I will only treat a change as confirmed after you approve the terms. Thank you."
    )


# ----------------------------- gradio interface ----------------------------
CUSTOM_CSS = """
:root {
  --solvra-ink: #203247;
  --solvra-muted: #6b7888;
  --solvra-teal: #167d73;
  --solvra-paper: #f3f6f7;
  --solvra-line: #e4eaed;
}
.gradio-container {
  max-width: 1480px !important;
  background: var(--solvra-paper) !important;
  color: var(--solvra-ink) !important;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif !important;
}
#hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 25px 30px;
  margin: 0 0 15px;
  border: 1px solid rgba(255,255,255,.13);
  border-radius: 20px;
  color: #fff;
  background: linear-gradient(118deg, #18324a 0%, #1c5d61 63%, #258a78 100%);
  box-shadow: 0 12px 28px rgba(28, 59, 69, .12);
}
#hero .hero-eyebrow { margin-bottom: 5px; color: #b9e7dc; font-size: 11px; font-weight: 750; letter-spacing: .15em; }
#hero h1 { margin: 0; font-size: 35px; line-height: 1.12; letter-spacing: -.045em; }
#hero p { margin: 8px 0 0; color: rgba(255,255,255,.82); font-size: 14px; }
#hero .hero-tag {
  flex: 0 0 auto;
  padding: 10px 14px;
  border: 1px solid rgba(255,255,255,.24);
  border-radius: 12px;
  color: #fff;
  background: rgba(255,255,255,.10);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .08em;
  text-align: right;
}
#hero .hero-tag span { display: block; margin-top: 4px; color: rgba(255,255,255,.78); font-size: 12px; font-weight: 500; letter-spacing: 0; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 12px; }
.kpi {
  min-height: 90px;
  padding: 16px 17px;
  border: 1px solid var(--solvra-line);
  border-radius: 15px;
  background: #fff;
  box-shadow: 0 3px 12px rgba(25,48,63,.035);
  transition: transform .18s ease, box-shadow .18s ease;
}
.kpi:hover { transform: translateY(-2px); box-shadow: 0 8px 18px rgba(25,48,63,.08); }
.kpi-label { color: var(--solvra-muted); font-size: 11px; font-weight: 700; letter-spacing: .055em; text-transform: uppercase; }
.kpi-value { margin-top: 8px; color: var(--solvra-ink); font-size: 22px; font-weight: 760; letter-spacing: -.025em; }
.disclaimer { padding: 8px 3px 12px; color: var(--solvra-muted); font-size: 12px; }
.gradio-container button.primary { border: 0 !important; background: var(--solvra-teal) !important; box-shadow: 0 3px 8px rgba(22,125,115,.15); }
.gradio-container button.primary:hover { background: #116a62 !important; }
.gradio-container button.stop { border-radius: 10px !important; }
.gradio-container [role="tab"] { font-weight: 650 !important; }
.gradio-container .block, .gradio-container .form { border-color: var(--solvra-line) !important; }
@media (max-width: 720px) {
  #hero { align-items: flex-start; flex-direction: column; padding: 21px; }
  #hero .hero-tag { text-align: left; }
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi-value { font-size: 19px; }
}
"""


def launch_app(share: bool | None = None):
    import gradio as gr

    share = (
        ("google.colab" in str(getattr(__import__("sys"), "modules", {})))
        if share is None
        else share
    )
    theme = gr.themes.Soft(
        primary_hue="teal",
        secondary_hue="orange",
        neutral_hue="slate",
        radius_size="lg",
        spacing_size="md",
        font=gr.themes.LocalFont("Inter", weights=(400, 600, 700)),
    )
    blocks_kwargs = {"title": "Solvra — Financial decision support"}
    if int(gr.__version__.split(".")[0]) < 6:
        blocks_kwargs.update({"theme": theme, "css": CUSTOM_CSS})
    with gr.Blocks(**blocks_kwargs) as app:
        pending_state = gr.State(None)
        conversation_state = gr.State([])
        gr.HTML(
            f"<div id='hero'><div><div class='hero-eyebrow'>FINANCIAL DECISION SUPPORT</div><h1>Solvra</h1><p>Clearer next steps when available cash and due dates collide.</p></div><div class='hero-tag'>SYNTHETIC DEMO ACCOUNT<span>Snapshot · {AS_OF:%B %d, %Y}</span></div></div>"
        )
        gr.Markdown(
            f"**Synthetic demonstration data — fictional household, not real account records.** &nbsp; {DISCLAIMER}",
            elem_classes="disclaimer",
        )
        with gr.Tabs():
            # 1 Overview
            with gr.Tab("Overview", id="overview"):
                with gr.Row():
                    period = gr.Dropdown(
                        [
                            "Last 30 days",
                            "Last 90 days",
                            "Last 6 months",
                            "Last 12 months",
                            "Entire 24-month history",
                        ],
                        value="Last 90 days",
                        label="Dashboard range",
                    )
                    refresh = gr.Button("Refresh dashboard", variant="primary")
                kpis = gr.HTML(dashboard_kpis(DEMO))
                initial_charts = dashboard_charts(DEMO, "Last 90 days")
                with gr.Row():
                    c_income = gr.Plot(value=initial_charts[0])
                    c_category = gr.Plot(value=initial_charts[1])
                with gr.Row():
                    c_cash = gr.Plot(value=initial_charts[2])
                    c_debt = gr.Plot(value=initial_charts[3])
                with gr.Row():
                    c_catbar = gr.Plot(value=initial_charts[4])
                    c_essential = gr.Plot(value=initial_charts[5])
                with gr.Row():
                    upcoming = gr.Dataframe(
                        value=upcoming_frame(DEMO),
                        label="Upcoming obligations",
                        interactive=False,
                        wrap=True,
                    )
                    health_md = gr.Markdown()
                insights = gr.Markdown(
                    value="### Financial insights\n" + financial_insights(DEMO)
                )
                score, score_factors, score_explain = health_assessment(DEMO)
                health_md.value = (
                    f"### Financial health index: {score}/100\n\n{score_explain}"
                )
                with gr.Accordion("Score components", open=False):
                    gr.Dataframe(value=score_factors, interactive=False)
                dashboard_outputs = [
                    kpis,
                    c_income,
                    c_category,
                    c_cash,
                    c_debt,
                    c_catbar,
                    c_essential,
                    upcoming,
                    health_md,
                    insights,
                ]

                def refresh_dashboard_for(selected_period):
                    hscore, _, hexplain = health_assessment(DEMO)
                    return (
                        dashboard_kpis(DEMO),
                        *dashboard_charts(DEMO, selected_period),
                        upcoming_frame(DEMO),
                        f"### Financial health index: {hscore}/100\n\n{hexplain}",
                        "### Financial insights\n" + financial_insights(DEMO),
                    )

                period.change(
                    refresh_dashboard_for, inputs=period, outputs=dashboard_outputs
                )
                refresh.click(
                    refresh_dashboard_for, inputs=period, outputs=dashboard_outputs
                )
            # 2 Transactions
            with gr.Tab("Transactions", id="transactions"):
                gr.Markdown(
                    "### Transaction ledger\nAround 1,000 generated records with real dates, signed amounts, accounts, recurrence labels, and event-linked descriptions."
                )
                trans_range = gr.Dropdown(
                    [
                        "Last 30 days",
                        "Last 90 days",
                        "Last 6 months",
                        "Last 12 months",
                        "Entire history",
                    ],
                    value="Last 90 days",
                    label="Period",
                )
                trans_table = gr.Dataframe(
                    value=transactions_for_period(DEMO, 90)
                    .sort_values("date", ascending=False)
                    .head(250),
                    interactive=False,
                    wrap=True,
                )
                with gr.Row():
                    add_date = gr.Textbox(
                        value=AS_OF.isoformat(), label="Date (YYYY-MM-DD)"
                    )
                    add_merchant = gr.Textbox(label="Merchant / source")
                    add_category = gr.Dropdown(
                        [
                            "Income",
                            "Housing",
                            "Utilities",
                            "Groceries",
                            "Transportation",
                            "Insurance",
                            "Debt payments",
                            "Medical",
                            "Dining & Entertainment",
                            "Shopping",
                            "Subscriptions",
                            "Other expenses",
                        ],
                        value="Other expenses",
                        label="Category",
                    )
                with gr.Row():
                    add_amount = gr.Number(
                        label="Signed amount (income positive, expense negative)"
                    )
                    add_desc = gr.Textbox(label="Description")
                    add_tx = gr.Button("Add transaction", variant="primary")
                tx_msg = gr.Markdown()

                def filter_tx(rng):
                    d = {
                        "Last 30 days": 30,
                        "Last 90 days": 90,
                        "Last 6 months": 183,
                        "Last 12 months": 365,
                        "Entire history": None,
                    }[rng]
                    return (
                        transactions_for_period(DEMO, d)
                        .sort_values("date", ascending=False)
                        .head(500)
                    )

                trans_range.change(filter_tx, trans_range, trans_table)

                def create_tx(date, merchant, category, amount, desc):
                    try:
                        d = dt.date.fromisoformat(date)
                        amount = float(amount)
                        if amount == 0:
                            raise ValueError("Amount must be non-zero")
                        DEMO.add_transaction(
                            amount,
                            category,
                            merchant or "User entry",
                            desc or "Manually entered",
                            d,
                            account="Checking",
                            tx_type=(
                                "Income"
                                if amount > 0 and category == "Income"
                                else "Expense"
                            ),
                        )
                        return (
                            f"Saved transaction. Current checking: {money(DEMO.balance('Checking'))}.",
                            filter_tx("Entire history"),
                        )
                    except Exception as e:
                        return f"Could not save: {e}", filter_tx("Last 90 days")

                transaction_event = add_tx.click(
                    create_tx,
                    [add_date, add_merchant, add_category, add_amount, add_desc],
                    [tx_msg, trans_table],
                )
            # 3 Bills
            with gr.Tab("Bills", id="bills"):
                gr.Markdown(
                    "### Obligation register\nEdit the synthetic account's open obligations. Confirmed extensions are distinguished from requests; payment entries do not initiate bank transfers."
                )
                bills_table = gr.Dataframe(
                    value=bill_df(DEMO), interactive=False, wrap=True
                )
                bill_history_table = gr.Dataframe(
                    value=DEMO.records["bill_history"]
                    .sort_values("due_date", ascending=False)
                    .head(100),
                    label="Historical and current bill payment history (latest 100)",
                    interactive=False,
                    wrap=True,
                )
                with gr.Accordion("Edit an existing bill", open=False):
                    with gr.Row():
                        edit_id = gr.Textbox(label="Bill ID or exact bill name")
                        edit_amount = gr.Number(label="New amount (blank = unchanged)")
                        edit_due = gr.Textbox(
                            label="New due date YYYY-MM-DD (blank = unchanged)"
                        )
                    with gr.Row():
                        edit_minimum = gr.Number(
                            label="New minimum (blank = unchanged)"
                        )
                        edit_late = gr.Number(label="New late fee (blank = unchanged)")
                        edit_apr = gr.Number(
                            label="New APR decimal (blank = unchanged)"
                        )
                        edit_grace = gr.Number(
                            label="New grace days (blank = unchanged)"
                        )
                    with gr.Row():
                        edit_extension = gr.Textbox(
                            label="Extension date YYYY-MM-DD (blank = no change)"
                        )
                        edit_confirmed = gr.Checkbox(
                            label="Provider confirmed extension"
                        )
                        edit_revoke = gr.Checkbox(label="Revoke saved extension")
                        edit_terms = gr.Textbox(label="Extension / arrangement terms")
                        edit_button = gr.Button("Save bill edits", variant="primary")
                with gr.Accordion(
                    "Upload or paste a bill for field extraction", open=False
                ):
                    doc_file = gr.File(
                        label="Bill image or searchable PDF",
                        file_types=["image", ".pdf"],
                        type="filepath",
                    )
                    doc_text = gr.Textbox(
                        label="Or paste bill text",
                        lines=6,
                        placeholder="Provider\nAmount Due: $120.00\nDue Date: 12/01/2026",
                    )
                    extract_button = gr.Button("Extract fields for review")
                    extract_fields = gr.Dataframe(
                        label="Extracted fields and confidence", interactive=False
                    )
                    extract_json = gr.Code(
                        label="Editable structured fields (unknown values stay null)",
                        language="json",
                        lines=12,
                    )
                    extract_msg = gr.Markdown()
                    extract_confirm = gr.Checkbox(
                        label="I reviewed the fields. If optional terms are null, I explicitly accept they remain unknown and will be modeled as zero until confirmed with the provider."
                    )
                    extract_add = gr.Button(
                        "Confirm and add extracted bill", variant="primary"
                    )
                with gr.Accordion("Add a bill", open=False):
                    with gr.Row():
                        new_name = gr.Textbox(label="Bill name")
                        new_provider = gr.Textbox(label="Provider")
                        new_cat = gr.Dropdown(
                            [
                                "Housing",
                                "Utilities",
                                "Groceries",
                                "Transportation",
                                "Insurance",
                                "Debt payments",
                                "Medical",
                                "Subscriptions",
                                "Other",
                            ],
                            value="Utilities",
                            label="Category",
                        )
                    with gr.Row():
                        new_amount = gr.Number(label="Amount owed")
                        new_due = gr.Textbox(
                            value=(AS_OF + dt.timedelta(days=7)).isoformat(),
                            label="Due date YYYY-MM-DD",
                        )
                        new_min = gr.Number(value=0, label="Minimum payment")
                        new_late = gr.Number(value=0, label="Late fee")
                    with gr.Row():
                        new_apr = gr.Number(value=0, label="APR as decimal (e.g. 0.24)")
                        new_grace = gr.Number(value=0, label="Grace days")
                        new_risk = gr.Number(
                            value=0,
                            label="Consequence weight ($-equivalent; model assumption)",
                        )
                        new_risk_days = gr.Number(
                            value=7, label="Risk deadline after due (days)"
                        )
                        new_partial = gr.Checkbox(
                            value=True, label="Partial payment allowed"
                        )
                    new_cons = gr.Textbox(
                        value="Provider terms not yet confirmed",
                        label="Consequences / unknowns",
                    )
                    add_bill_button = gr.Button("Add obligation", variant="primary")
                with gr.Row():
                    delete_id = gr.Textbox(label="Bill ID/name to delete")
                    delete_button = gr.Button("Delete obligation", variant="stop")
                    pay_id = gr.Textbox(label="Bill ID/name to record payment against")
                    pay_amt = gr.Number(label="Payment amount")
                    pay_button = gr.Button("Record payment")
                bill_msg = gr.Markdown()

                def add_bill_cb(
                    name,
                    provider,
                    cat,
                    amount,
                    due,
                    minimum,
                    late,
                    apr,
                    grace,
                    risk,
                    riskdays,
                    partial,
                    cons,
                ):
                    try:
                        if not name or amount is None or float(amount) <= 0:
                            raise ValueError("Name and positive amount are required")
                        b = Bill(
                            f"B-CUSTOM-{uuid.uuid4().hex[:7]}",
                            name,
                            provider or "Unspecified provider",
                            cat,
                            float(amount),
                            dt.date.fromisoformat(due),
                            float(minimum or 0),
                            float(late or 0),
                            float(apr or 0),
                            int(grace or 0),
                            cons or "Unknown",
                            float(risk or 0),
                            int(riskdays or 7),
                            False,
                            None,
                            "",
                            bool(partial),
                            "User-entered; provider terms unverified",
                        )
                        DEMO.add_bill(b)
                        return f"Added {b.name} ({b.bill_id}).", bill_df(DEMO)
                    except Exception as e:
                        return f"Could not add bill: {e}", bill_df(DEMO)

                add_bill_event = add_bill_button.click(
                    add_bill_cb,
                    [
                        new_name,
                        new_provider,
                        new_cat,
                        new_amount,
                        new_due,
                        new_min,
                        new_late,
                        new_apr,
                        new_grace,
                        new_risk,
                        new_risk_days,
                        new_partial,
                        new_cons,
                    ],
                    [bill_msg, bills_table],
                )

                def edit_bill_cb(
                    identifier,
                    amount,
                    due,
                    minimum,
                    late,
                    apr,
                    grace,
                    extension,
                    confirmed,
                    revoke,
                    terms,
                ):
                    b = DEMO.find_bill(identifier)
                    if not b:
                        return "Bill not found.", bill_df(DEMO)
                    try:
                        if amount is not None and float(amount) > 0:
                            b.amount = float(amount)
                        if due and str(due).strip():
                            b.due_date = dt.date.fromisoformat(due)
                        if minimum is not None:
                            b.minimum_payment = float(minimum)
                        if late is not None:
                            b.late_fee = float(late)
                        if apr is not None:
                            b.apr = float(apr)
                        if grace is not None:
                            b.grace_days = int(grace)
                        if revoke:
                            b.confirmed_extension = False
                            b.extension_date = None
                            b.extension_terms = ""
                        elif extension and str(extension).strip():
                            b.extension_date = dt.date.fromisoformat(extension)
                            b.confirmed_extension = bool(confirmed)
                            b.extension_terms = (
                                terms
                                or "User-edited provider-confirmation status; verify documented terms."
                            )
                        elif confirmed and b.extension_date:
                            b.confirmed_extension = True
                            if terms:
                                b.extension_terms = terms
                        elif terms:
                            b.extension_terms = terms
                        DEMO.version += 1
                        return (
                            f"Updated {b.name}; optimizer will use saved values and only confirmed extensions.",
                            bill_df(DEMO),
                        )
                    except Exception as e:
                        return f"Could not edit bill: {e}", bill_df(DEMO)

                edit_bill_event = edit_button.click(
                    edit_bill_cb,
                    [
                        edit_id,
                        edit_amount,
                        edit_due,
                        edit_minimum,
                        edit_late,
                        edit_apr,
                        edit_grace,
                        edit_extension,
                        edit_confirmed,
                        edit_revoke,
                        edit_terms,
                    ],
                    [bill_msg, bills_table],
                )

                def extract_cb(file_path, text):
                    content = (text or "").strip()
                    if not content and file_path:
                        content = read_uploaded_bill(
                            file_path if isinstance(file_path, str) else file_path.name
                        )
                    if not content:
                        return (
                            pd.DataFrame(),
                            "",
                            "Upload a bill or paste its text first.",
                        )
                    result = extract_bill_fields(content)
                    table = pd.DataFrame(
                        [
                            {
                                "field": k,
                                "extracted_value": v,
                                "confidence": result["confidence"][k],
                            }
                            for k, v in result["fields"].items()
                        ]
                    )
                    return (
                        table,
                        json.dumps(result, indent=2),
                        "Review every value. OCR/regex can be wrong; missing fields are null, not zero.",
                    )

                extract_button.click(
                    extract_cb,
                    [doc_file, doc_text],
                    [extract_fields, extract_json, extract_msg],
                )

                def confirm_extracted_bill(payload, confirmed):
                    try:
                        if not confirmed:
                            return (
                                "Please confirm your review before adding this bill.",
                                bill_df(DEMO),
                            )
                        result = json.loads(payload)
                        fields = result.get("fields", result)
                        amount = fields.get("amount")
                        due = fields.get("due_date")
                        if amount is None or due is None:
                            raise ValueError(
                                "Amount and due date are required; fill them in the editable JSON before confirming."
                            )
                        provider = fields.get("provider") or "Unidentified provider"
                        missing = [
                            k
                            for k in (
                                "minimum_payment",
                                "late_fee",
                                "apr",
                                "grace_days",
                            )
                            if fields.get(k) is None
                        ]
                        note = (
                            (
                                "Unknown terms: "
                                + ", ".join(missing)
                                + ". Explicitly left unknown by reviewer; verify with provider. "
                            )
                            if missing
                            else ""
                        )
                        b = Bill(
                            f"B-OCR-{uuid.uuid4().hex[:7]}",
                            provider,
                            provider,
                            "Other",
                            float(amount),
                            dt.date.fromisoformat(str(due)),
                            float(fields.get("minimum_payment") or 0),
                            float(fields.get("late_fee") or 0),
                            float(fields.get("apr") or 0),
                            int(fields.get("grace_days") or 0),
                            note
                            + (
                                "Provider terms extracted from document; confirm directly."
                            ),
                            0,
                            7,
                            False,
                            None,
                            str(fields.get("extension_terms") or ""),
                            True,
                            "Document extraction reviewed; synthetic prototype",
                        )
                        DEMO.add_bill(b)
                        return (
                            f"Added reviewed obligation {b.name} ({b.bill_id}). Unknown terms are disclosed and currently modeled as zero; update the bill once verified.",
                            bill_df(DEMO),
                        )
                    except Exception as e:
                        return f"Bill not added: {e}", bill_df(DEMO)

                extracted_bill_event = extract_add.click(
                    confirm_extracted_bill,
                    [extract_json, extract_confirm],
                    [extract_msg, bills_table],
                )

                def delete_bill_cb(identifier):
                    ok = DEMO.delete_bill(identifier)
                    return (
                        "Deleted obligation from this session; historical payment records remain."
                        if ok
                        else "Bill not found; check the ID/name."
                    ), bill_df(DEMO)

                delete_button.click(delete_bill_cb, delete_id, [bill_msg, bills_table])

                def pay_bill_cb(identifier, amount):
                    b = DEMO.find_bill(identifier)
                    try:
                        if not b:
                            raise ValueError("Bill not found")
                        amount = float(amount)
                        if amount <= 0 or amount > DEMO.balance("Checking"):
                            raise ValueError(
                                "Payment must be positive and no greater than recorded checking cash"
                            )
                        if amount > b.amount:
                            raise ValueError("Payment exceeds outstanding bill amount")
                        DEMO.add_transaction(
                            -amount,
                            (
                                "Transfers"
                                if b.category == "Debt payments"
                                else b.category
                            ),
                            b.provider,
                            f"Payment recorded: {b.name}",
                            account="Checking",
                            tx_type="Payment",
                            method="Manual entry",
                        )
                        if b.name == "Credit Card Minimum":
                            DEMO.adjust_debt("Credit Card", -amount)
                        elif b.name == "Auto Loan":
                            DEMO.adjust_debt("Auto Loan", -amount * 0.76)
                        elif b.name == "Student Loan":
                            DEMO.adjust_debt("Student Loan", -amount * 0.88)
                        DEMO.record_bill_payment(b, amount)
                        b.amount = round(b.amount - amount, 2)
                        b.status = "Paid" if b.amount < 0.01 else "Partially paid"
                        DEMO.version += 1
                        return (
                            f"Recorded ${amount:,.2f}; remaining obligation ${b.amount:,.2f}.",
                            bill_df(DEMO),
                            DEMO.records["bill_history"]
                            .sort_values("due_date", ascending=False)
                            .head(100),
                        )
                    except Exception as e:
                        return (
                            f"Payment not recorded: {e}",
                            bill_df(DEMO),
                            DEMO.records["bill_history"]
                            .sort_values("due_date", ascending=False)
                            .head(100),
                        )

                payment_event = pay_button.click(
                    pay_bill_cb,
                    [pay_id, pay_amt],
                    [bill_msg, bills_table, bill_history_table],
                )
            # 4 Financial situation
            with gr.Tab("Financial Situation", id="situation"):
                gr.Markdown(
                    "### Scenario inputs\nChecking is the default spendable balance; savings is shown separately and is not automatically drawn into a plan. Include any savings you are willing to use in the available-cash override, then set the reserve you want to protect. Overrides are planning-only until separately recorded."
                )

                def situation_snapshot_text():
                    return (
                        f"**Ledger snapshot — {AS_OF}:** Checking {money(DEMO.balance('Checking'))} · savings {money(DEMO.balance('Savings'))} · "
                        f"total recorded debt {money(sum(DEMO.debts().values()))} · open bill obligations {money(sum(b.amount for b in current_open_bills(DEMO)))}. "
                        "Expected income is a scenario input, not a deposit."
                    )

                situation_snapshot = gr.Markdown(value=situation_snapshot_text())
                refresh_situation = gr.Button("Refresh ledger snapshot")
                refresh_situation.click(
                    situation_snapshot_text, None, situation_snapshot
                )
                situation_checking = gr.Number(
                    value=DEMO.balance("Checking"), label="Available checking cash ($)"
                )
                with gr.Row():
                    paycheck = gr.Number(
                        value=2200, label="Expected paycheck amount ($)"
                    )
                    payday = gr.Textbox(
                        value="2026-11-20", label="Expected paycheck date (YYYY-MM-DD)"
                    )
                    other_income = gr.Number(value=0, label="Other expected income ($)")
                    other_income_date = gr.Textbox(
                        value="2026-11-20", label="Other income date"
                    )
                reserve = gr.Number(
                    value=DEMO.preferences["reserve"],
                    label="Emergency cash reserve to protect ($)",
                )
                priority = gr.Dropdown(
                    [
                        "Protect housing and essential services",
                        "Minimize fees and interest",
                        "Protect transportation and insurance",
                        "User-defined priorities",
                    ],
                    value=DEMO.preferences["financial_priority"],
                    label="Financial priority",
                )
                circumstances = gr.Textbox(
                    value="",
                    label="Special circumstances (context only; explain to provider directly)",
                    lines=2,
                )
                situation_save = gr.Button(
                    "Save planning assumptions", variant="primary"
                )
                situation_msg = gr.Markdown()

                def save_situation(
                    cash, inc, date, other, otherdate, resv, prio, special
                ):
                    try:
                        DEMO.preferences.update(
                            {
                                "planning_cash": float(cash),
                                "paycheck": float(inc or 0),
                                "payday": dt.date.fromisoformat(date),
                                "other_income": float(other or 0),
                                "other_income_date": dt.date.fromisoformat(otherdate),
                                "reserve": float(resv or 0),
                                "financial_priority": prio,
                                "special_circumstances": special or "",
                            }
                        )
                        return "Saved for planning only. Confirm actual income/balance changes separately; expected income is not guaranteed."
                    except Exception as e:
                        return f"Please correct the inputs: {e}"

                situation_event = situation_save.click(
                    save_situation,
                    [
                        situation_checking,
                        paycheck,
                        payday,
                        other_income,
                        other_income_date,
                        reserve,
                        priority,
                        circumstances,
                    ],
                    situation_msg,
                )

            # 5 Smart prioritization
            with gr.Tab("Smart Prioritization", id="prioritize"):
                gr.Markdown(
                    "### Consequence-aware payment plan\nThe transparent SciPy MILP allocates cash only when available, respects minimums and non-partial obligations, and treats provider arrangements as confirmed only when explicitly recorded."
                )
                with gr.Row():
                    opt_cash = gr.Number(
                        value=DEMO.balance("Checking"), label="Available checking cash"
                    )
                    opt_reserve = gr.Number(
                        value=DEMO.preferences["reserve"],
                        label="Cash reserve to protect",
                    )
                with gr.Row():
                    opt_income = gr.Number(
                        value=DEMO.preferences["paycheck"],
                        label="Expected paycheck (not guaranteed)",
                    )
                    opt_date = gr.Textbox(
                        value=DEMO.preferences["payday"].isoformat(),
                        label="Paycheck date YYYY-MM-DD",
                    )
                    opt_other = gr.Number(
                        value=DEMO.preferences["other_income"],
                        label="Other expected income",
                    )
                    opt_other_date = gr.Textbox(
                        value=DEMO.preferences["other_income_date"].isoformat(),
                        label="Other income date",
                    )
                with gr.Row():
                    weight_late = gr.Number(
                        value=1.0, label="Consequence weight: late fee"
                    )
                    weight_interest = gr.Number(
                        value=1.0, label="Consequence weight: interest"
                    )
                    weight_critical = gr.Number(
                        value=1.0, label="Consequence weight: critical risk"
                    )
                    opt_run = gr.Button("Calculate payment strategy", variant="primary")
                opt_output = gr.Markdown()
                provider_pick = gr.Textbox(
                    value="Electricity", label="Bill name for provider message"
                )
                message_button = gr.Button("Draft extension / arrangement request")
                message_output = gr.Textbox(label="Customizable message", lines=5)

                def opt_cb(cash, resv, inc, date, other, otherdate, wlate, wint, wcrit):
                    try:
                        incomes = []
                        if inc and float(inc) > 0:
                            incomes.append(
                                IncomeEvent(
                                    float(inc),
                                    dt.date.fromisoformat(date),
                                    "Expected paycheck",
                                    False,
                                )
                            )
                        if other and float(other) > 0:
                            incomes.append(
                                IncomeEvent(
                                    float(other),
                                    dt.date.fromisoformat(otherdate),
                                    "Other expected income",
                                    False,
                                )
                            )
                        weights = {
                            "late_fee": max(0, float(wlate)),
                            "interest": max(0, float(wint)),
                            "critical": max(0, float(wcrit)),
                        }
                        scenario = Scenario(
                            float(cash),
                            AS_OF,
                            copy.deepcopy(current_open_bills(DEMO)),
                            incomes,
                            float(resv or 0),
                            40,
                        )
                        result = optimize(scenario, weights)
                        context_note = (
                            f"\n\n**Saved priority:** {DEMO.preferences.get('financial_priority','Not specified')} (context only; modeled weights above control the objective). "
                            f"**Special circumstances:** {DEMO.preferences.get('special_circumstances','') or 'None recorded'}. These notes do not alter provider terms or solver constraints."
                        )
                        return render_plan(result) + context_note
                    except Exception as e:
                        return f"Could not calculate: {e}"

                opt_run.click(
                    opt_cb,
                    [
                        opt_cash,
                        opt_reserve,
                        opt_income,
                        opt_date,
                        opt_other,
                        opt_other_date,
                        weight_late,
                        weight_interest,
                        weight_critical,
                    ],
                    opt_output,
                )

                def message_cb(name):
                    b = DEMO.find_bill(name or "")
                    return (
                        provider_message(b)
                        if b
                        else "Bill not found. Enter a bill name, provider, or ID exactly as shown in Bills."
                    )

                message_button.click(message_cb, provider_pick, message_output)
            # 6 Simulations
            with gr.Tab("Simulations", id="simulations"):
                gr.Markdown(
                    "### What-if comparison\nAll four strategies use the same starting cash, reserve, income, bills, and consequence model. Amount/due overrides and simulated extensions are scenario-only."
                )
                with gr.Row():
                    sim_cash = gr.Number(
                        value=DEMO.balance("Checking"), label="Starting cash"
                    )
                    sim_reserve = gr.Number(
                        value=DEMO.preferences["reserve"], label="Protected reserve"
                    )
                    sim_income = gr.Number(
                        value=DEMO.preferences["paycheck"], label="Expected paycheck"
                    )
                    sim_income_date = gr.Textbox(
                        value=DEMO.preferences["payday"].isoformat(),
                        label="Income date",
                    )
                with gr.Row():
                    sim_other = gr.Number(value=0, label="Other expected income")
                    sim_other_date = gr.Textbox(
                        value="2026-11-20", label="Other income date"
                    )
                    sim_weight_late = gr.Number(value=1, label="Late fee weight")
                    sim_weight_interest = gr.Number(value=1, label="Interest weight")
                    sim_weight_critical = gr.Number(
                        value=1, label="Critical consequence weight"
                    )
                with gr.Row():
                    sim_bill = gr.Textbox(label="Optional bill name to modify")
                    sim_amount = gr.Number(label="Amount override (blank = unchanged)")
                    sim_due = gr.Textbox(
                        label="Due date override YYYY-MM-DD (blank = unchanged)"
                    )
                    sim_ext = gr.Checkbox(label="What-if: extension approved (+5 days)")
                sim_button = gr.Button("Run four-way comparison", variant="primary")
                sim_table = gr.Dataframe(interactive=False)
                sim_chart = gr.Plot()
                sim_explain = gr.Markdown()

                def sim_cb(
                    cash,
                    resv,
                    inc,
                    idate,
                    other,
                    otherdate,
                    wlate,
                    wint,
                    wcrit,
                    name,
                    amount,
                    due,
                    ext,
                ):
                    try:
                        bills = copy.deepcopy(current_open_bills(DEMO))
                        key = str(name or "").strip().lower()
                        b = next(
                            (
                                x
                                for x in bills
                                if key
                                and (key in x.name.lower() or key in x.provider.lower())
                            ),
                            None,
                        )
                        if b:
                            if amount is not None and float(amount) > 0:
                                b.amount = float(amount)
                            if due and str(due).strip():
                                b.due_date = dt.date.fromisoformat(due)
                            if ext:
                                b.confirmed_extension = True
                                b.extension_date = b.due_date + dt.timedelta(days=5)
                                b.extension_terms = (
                                    "What-if extension only; not provider confirmed."
                                )
                        incomes = []
                        if inc and float(inc) > 0:
                            incomes.append(
                                IncomeEvent(
                                    float(inc),
                                    dt.date.fromisoformat(idate),
                                    "Expected paycheck",
                                    False,
                                )
                            )
                        if other and float(other) > 0:
                            incomes.append(
                                IncomeEvent(
                                    float(other),
                                    dt.date.fromisoformat(otherdate),
                                    "Other expected income",
                                    False,
                                )
                            )
                        weights = {
                            "late_fee": max(0, float(wlate)),
                            "interest": max(0, float(wint)),
                            "critical": max(0, float(wcrit)),
                        }
                        s = Scenario(
                            float(cash), AS_OF, bills, incomes, float(resv or 0), 40
                        )
                        results = run_all_strategies(s, weights)
                        table = plan_table(results)
                        fig = px.bar(
                            table,
                            x="Strategy",
                            y="Modeled harm ($-equivalent)",
                            color="Strategy",
                            title="Comparable modeled consequence estimate",
                        )
                        fig.update_layout(
                            template="plotly_white", height=350, showlegend=False
                        )
                        text = (
                            "### Optimized plan\n"
                            + render_plan(results[-1], bills)
                            + "\n\nThese are synthetic model estimates; contact providers to confirm terms."
                        )
                        return table, fig, text
                    except Exception as e:
                        return pd.DataFrame(), go.Figure(), f"Simulation error: {e}"

                sim_button.click(
                    sim_cb,
                    [
                        sim_cash,
                        sim_reserve,
                        sim_income,
                        sim_income_date,
                        sim_other,
                        sim_other_date,
                        sim_weight_late,
                        sim_weight_interest,
                        sim_weight_critical,
                        sim_bill,
                        sim_amount,
                        sim_due,
                        sim_ext,
                    ],
                    [sim_table, sim_chart, sim_explain],
                )
            # 7 Voice assistant
            with gr.Tab("Voice Assistant", id="voice"):
                gr.Markdown(
                    "### Ask Solvra\nAsk text or speak. Responses query the synthetic account ledger and/or call the optimizer. Important updates are staged for your confirmation before they change the account."
                )
                audio = gr.Audio(
                    sources=["microphone", "upload"],
                    type="filepath",
                    label="Speak or upload audio",
                )
                transcribe_btn = gr.Button("Transcribe with Faster-Whisper")
                transcript = gr.Textbox(label="Transcript (editable)", lines=2)
                with gr.Row():
                    question = gr.Textbox(
                        label="Your financial question / update",
                        lines=2,
                        placeholder="Which bills should I pay first?",
                    )
                    ask_btn = gr.Button("Ask Solvra", variant="primary")
                answer = gr.Markdown()
                speak = gr.Audio(label="Spoken response (gTTS)", type="filepath")
                with gr.Row():
                    confirm_btn = gr.Button(
                        "Confirm interpreted financial update", variant="primary"
                    )
                    cancel_btn = gr.Button("Cancel update")
                update_msg = gr.Markdown()

                def transcribe(path):
                    text = transcribe_audio(path)
                    return text

                transcribe_btn.click(transcribe, audio, transcript).then(
                    lambda t: t, transcript, question
                )

                def ask_cb(q, history):
                    text, pending = answer_financial_question(q, DEMO, history)
                    history = (history or []) + [
                        {"role": "user", "content": q},
                        {"role": "assistant", "content": text},
                    ]
                    return text, pending, history, speech_file(text)

                ask_btn.click(
                    ask_cb,
                    [question, conversation_state],
                    [answer, pending_state, conversation_state, speak],
                )

                def approve_pending(p):
                    return confirm_account_update(p, True), None

                def cancel_pending(p):
                    return confirm_account_update(p, False), None

                confirmation_event = (
                    confirm_btn.click(
                        approve_pending, pending_state, [update_msg, pending_state]
                    )
                    .then(
                        lambda: (
                            bill_df(DEMO),
                            DEMO.records["bill_history"]
                            .sort_values("due_date", ascending=False)
                            .head(100),
                        ),
                        None,
                        [bills_table, bill_history_table],
                    )
                    .then(
                        refresh_dashboard_for, inputs=period, outputs=dashboard_outputs
                    )
                )
                cancel_btn.click(
                    cancel_pending, pending_state, [update_msg, pending_state]
                )
            # 8 Reports & analytics
            with gr.Tab("Reports & Analytics", id="reports"):
                gr.Markdown(
                    "### Personal report\nHistorical account reports are separate from synthetic optimizer-evaluation results."
                )
                report_range = gr.Dropdown(
                    [
                        "Last 3 months",
                        "Last 6 months",
                        "Last 12 months",
                        "Entire history",
                    ],
                    value="Last 12 months",
                    label="Report range",
                )
                report_initial = report_support_tables(DEMO, 365)
                report_initial_monthly = personal_report(DEMO, 365)
                report_initial_fig = go.Figure()
                report_initial_fig.add_trace(
                    go.Bar(
                        x=report_initial_monthly.month,
                        y=report_initial_monthly.income,
                        name="Income",
                        marker_color="#16a38c",
                    )
                )
                report_initial_fig.add_trace(
                    go.Bar(
                        x=report_initial_monthly.month,
                        y=report_initial_monthly.expenses,
                        name="Expenses",
                        marker_color="#ee825f",
                    )
                )
                report_initial_fig.add_trace(
                    go.Scatter(
                        x=report_initial_monthly.month,
                        y=report_initial_monthly.net_cash_flow,
                        name="Net",
                        mode="lines+markers",
                    )
                )
                report_initial_fig.update_layout(
                    title="Personal monthly report",
                    barmode="group",
                    template="plotly_white",
                    height=340,
                )
                report_table = gr.Dataframe(
                    value=report_initial_monthly, interactive=False
                )
                report_chart = gr.Plot(value=report_initial_fig)
                with gr.Row():
                    report_categories = gr.Dataframe(
                        value=report_initial[0],
                        label="Spending by category",
                        interactive=False,
                    )
                    report_bill_history = gr.Dataframe(
                        value=report_initial[1],
                        label="Payment history / late payments",
                        interactive=False,
                        wrap=True,
                    )
                with gr.Row():
                    report_upcoming = gr.Dataframe(
                        value=report_initial[2],
                        label="Upcoming obligations",
                        interactive=False,
                    )
                    report_health = gr.Dataframe(
                        value=report_initial[3],
                        label="Health trend score factors",
                        interactive=False,
                    )
                report_insights = gr.Markdown(
                    value="### Account insights\n"
                    + report_initial[4]
                    + "\n\n"
                    + report_initial[5]
                )
                with gr.Row():
                    report_csv = gr.Button("Create monthly / balances CSV")
                    report_category_csv = gr.Button("Create category spending CSV")
                    report_pdf = gr.Button("Create personal PDF")
                report_file = gr.File(label="Monthly financial report download")
                report_category_file = gr.File(label="Category spending CSV download")

                def report_show(r):
                    d = {
                        "Last 3 months": 90,
                        "Last 6 months": 183,
                        "Last 12 months": 365,
                        "Entire history": None,
                    }[r]
                    df = personal_report(DEMO, d)
                    fig = go.Figure()
                    fig.add_trace(
                        go.Bar(
                            x=df.month,
                            y=df.income,
                            name="Income",
                            marker_color="#16a38c",
                        )
                    )
                    fig.add_trace(
                        go.Bar(
                            x=df.month,
                            y=df.expenses,
                            name="Expenses",
                            marker_color="#ee825f",
                        )
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=df.month,
                            y=df.net_cash_flow,
                            name="Net",
                            mode="lines+markers",
                        )
                    )
                    fig.update_layout(
                        title="Personal monthly report",
                        barmode="group",
                        template="plotly_white",
                        height=340,
                    )
                    cats, hist, upcoming_df, factors, insights, explanation = (
                        report_support_tables(DEMO, d)
                    )
                    return (
                        df,
                        fig,
                        cats,
                        hist,
                        upcoming_df,
                        factors,
                        "### Account insights\n" + insights + "\n\n" + explanation,
                    )

                report_range.change(
                    report_show,
                    report_range,
                    [
                        report_table,
                        report_chart,
                        report_categories,
                        report_bill_history,
                        report_upcoming,
                        report_health,
                        report_insights,
                    ],
                )

                def gen_csv(r):
                    return export_personal_csv(
                        DEMO,
                        {
                            "Last 3 months": 90,
                            "Last 6 months": 183,
                            "Last 12 months": 365,
                            "Entire history": None,
                        }[r],
                    )

                def gen_pdf(r):
                    return export_personal_pdf(
                        DEMO,
                        {
                            "Last 3 months": 90,
                            "Last 6 months": 183,
                            "Last 12 months": 365,
                            "Entire history": None,
                        }[r],
                    )

                def gen_category_csv(r):
                    return export_category_csv(
                        DEMO,
                        {
                            "Last 3 months": 90,
                            "Last 6 months": 183,
                            "Last 12 months": 365,
                            "Entire history": None,
                        }[r],
                    )

                report_csv.click(gen_csv, report_range, report_file)
                report_pdf.click(gen_pdf, report_range, report_file)
                report_category_csv.click(
                    gen_category_csv, report_range, report_category_file
                )
                gr.Markdown(
                    "### Strategy evaluation — synthetic held-out test (150 scenarios)\n350 development and 150 held-out scenarios are generated separately. Reported metrics use only held-out scenarios; no performance claim is hardcoded. Cost weights and scenario generation are documented in code."
                )
                eval_button = gr.Button(
                    "Run held-out evaluation (may take a short while)",
                    variant="primary",
                )
                eval_summary = gr.Dataframe(interactive=False)
                eval_chart = gr.Plot()
                eval_download = gr.File(label="Evaluation rows CSV")

                def eval_cb():
                    summary, detail = evaluate_benchmarks()
                    fig = px.bar(
                        summary,
                        x="strategy",
                        y="average_modeled_harm",
                        color="strategy",
                        title="Mean modeled harm on 150 synthetic test cases",
                    )
                    fig.update_layout(
                        template="plotly_white", height=350, showlegend=False
                    )
                    path = os.path.join(
                        tempfile.gettempdir(), "solvra-heldout-evaluation.csv"
                    )
                    detail.to_csv(path, index=False)
                    return summary, fig, path

                eval_button.click(
                    eval_cb, None, [eval_summary, eval_chart, eval_download]
                )
                gr.Markdown(
                    "### Extraction field-level test\nTests known fictional samples, including missing and ambiguous data; unknown values remain null and need review."
                )
                extract_test_btn = gr.Button("Run extraction tests")
                extract_test_table = gr.Dataframe(interactive=False)
                extract_accuracy = gr.Markdown()

                def show_extraction_test_results():
                    results, metrics = extraction_test_suite()
                    message = (
                        f"Field accuracy: {metrics['field_accuracy']:.1%} "
                        f"({metrics['fields_tested']} synthetic fields). "
                        "This small test set is illustrative, not a production accuracy guarantee."
                    )
                    return results, message

                extract_test_btn.click(
                    show_extraction_test_results,
                    None,
                    [extract_test_table, extract_accuracy],
                )
            # 9 Settings
            with gr.Tab("Settings", id="settings"):
                gr.Markdown(
                    "### Demo account settings\nAll records are fictional and generated deterministically once for this process. Reset restores the same synthetic baseline, removing session changes."
                )

                def current_account_summary():
                    return (
                        f"**Synthetic account:** Jordan Lee · one-person Chicago household\n\n**History:** {DEMO.transactions.date.min().date()} through {AS_OF} · {len(DEMO.transactions):,} transactions · {len(DEMO.records['bill_history']):,} bill records.\n\n"
                        f"**Checking:** {money(DEMO.balance('Checking'))} · **Savings:** {money(DEMO.balance('Savings'))} · **Debt:** {money(sum(DEMO.debts().values()))}.\n\n"
                        f"Latest debt split: {DEMO.debts()}. Values refresh from the underlying synthetic ledger."
                    )

                with gr.Row():
                    reset_btn = gr.Button("Reset demo account", variant="stop")
                    settings_refresh = gr.Button("Refresh account summary")
                    account_summary = gr.Markdown(value=current_account_summary())

                def reset_demo():
                    DEMO.reset()
                    return (
                        current_account_summary(),
                        bill_df(DEMO),
                        dashboard_kpis(DEMO),
                        transactions_for_period(DEMO, 90),
                        DEMO.records["bill_history"]
                        .sort_values("due_date", ascending=False)
                        .head(100),
                    )

                settings_refresh.click(
                    lambda: current_account_summary(), None, account_summary
                )
                reset_event = (
                    reset_btn.click(
                        reset_demo,
                        None,
                        [
                            account_summary,
                            bills_table,
                            kpis,
                            trans_table,
                            bill_history_table,
                        ],
                    )
                    .then(
                        refresh_dashboard_for, inputs=period, outputs=dashboard_outputs
                    )
                    .then(
                        report_show,
                        inputs=report_range,
                        outputs=[
                            report_table,
                            report_chart,
                            report_categories,
                            report_bill_history,
                            report_upcoming,
                            report_health,
                            report_insights,
                        ],
                    )
                )

                def refresh_after_account_change():
                    return (
                        bill_df(DEMO),
                        DEMO.records["bill_history"]
                        .sort_values("due_date", ascending=False)
                        .head(100),
                        situation_snapshot_text(),
                        transactions_for_period(DEMO, 90),
                    )

                def refresh_planning_controls():
                    preferences = DEMO.preferences
                    return (
                        preferences["planning_cash"],
                        preferences["reserve"],
                        preferences["paycheck"],
                        preferences["payday"].isoformat(),
                        preferences["other_income"],
                        preferences["other_income_date"].isoformat(),
                    )

                report_outputs = [
                    report_table,
                    report_chart,
                    report_categories,
                    report_bill_history,
                    report_upcoming,
                    report_health,
                    report_insights,
                ]
                account_update_events = (
                    transaction_event,
                    add_bill_event,
                    edit_bill_event,
                    extracted_bill_event,
                    payment_event,
                    confirmation_event,
                    reset_event,
                )
                for event in account_update_events:
                    event.then(
                        refresh_after_account_change,
                        None,
                        [
                            bills_table,
                            bill_history_table,
                            situation_snapshot,
                            trans_table,
                        ],
                    ).then(
                        refresh_dashboard_for,
                        inputs=period,
                        outputs=dashboard_outputs,
                    ).then(
                        report_show, inputs=report_range, outputs=report_outputs
                    ).then(
                        refresh_planning_controls,
                        None,
                        [
                            opt_cash,
                            opt_reserve,
                            opt_income,
                            opt_date,
                            opt_other,
                            opt_other_date,
                        ],
                    )
                delete_button.click(
                    delete_bill_cb, delete_id, [bill_msg, bills_table]
                ).then(
                    refresh_after_account_change,
                    None,
                    [bills_table, bill_history_table, situation_snapshot, trans_table],
                ).then(
                    refresh_dashboard_for,
                    inputs=period,
                    outputs=dashboard_outputs,
                ).then(
                    report_show, inputs=report_range, outputs=report_outputs
                )
                situation_event.then(
                    situation_snapshot_text, None, situation_snapshot
                ).then(
                    refresh_planning_controls,
                    None,
                    [
                        opt_cash,
                        opt_reserve,
                        opt_income,
                        opt_date,
                        opt_other,
                        opt_other_date,
                    ],
                )

                gr.Markdown(
                    "#### Safety and data notes\n- Synthetic demonstration account only; never enter real credentials or bank data.\n- No payments are initiated and no provider is contacted.\n- Extraction values must be reviewed and confirmed. Unknown fields remain unknown.\n- Provider terms, legal protections, fees, service interruption, and credit reporting are uncertain.\n- **"
                    + DISCLAIMER
                    + "**"
                )
    app._solvra_theme = theme
    app._solvra_css = CUSTOM_CSS
    return app


# ---------------------------- application launch ----------------------------
def main():
    app = launch_app()
    # In Colab, Gradio's share tunnel provides a browser-accessible URL; elsewhere bind for preview/local access.
    in_colab = "google.colab" in __import__("sys").modules
    launch_kwargs = {
        "share": in_colab,
        "server_name": "0.0.0.0",
        "show_error": True,
        "debug": False,
    }
    import gradio as gr

    if int(gr.__version__.split(".")[0]) >= 6:
        launch_kwargs.update({"theme": app._solvra_theme, "css": app._solvra_css})
    app.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
