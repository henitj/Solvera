"""Four fictional households for the live demo. No passwords or real bank connection.

Maya retains the original reproducible account. The other households have their own
seeded ledgers, pay patterns, providers, arrears, savings drawdowns and debt histories.
"""

from __future__ import annotations

import calendar
import datetime as dt
import random
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

import solvra_app as f


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: str
    story: str
    goal: str
    household: str
    checking_suffix: str
    savings_suffix: str
    paycheck: float
    payday: int
    reserve: float

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "first_name": self.name.split()[0],
            "initials": "".join(part[0] for part in self.name.split()),
            "role": self.role,
            "story": self.story,
            "goal": self.goal,
            "household": self.household,
            "checking_suffix": self.checking_suffix,
            "savings_suffix": self.savings_suffix,
            "fictional": True,
        }


PEOPLE = {
    p.id: p
    for p in (
        Person(
            "maya",
            "Maya Chen",
            "Operations analyst",
            "A steady paycheck and a growing cushion. Ready to make a longer-term plan.",
            "Build a three-month emergency fund while reducing debt.",
            "One adult",
            "4821",
            "9016",
            2200,
            20,
            1000,
        ),
        Person(
            "jordan",
            "Jordan Reyes",
            "Freelance designer",
            "Client invoices vary, student debt is substantial, and savings bridge quieter weeks.",
            "Smooth irregular income and choose a debt payoff strategy.",
            "One adult, self-employed",
            "3174",
            "8062",
            1950,
            24,
            1500,
        ),
        Person(
            "aisha",
            "Aisha Patel",
            "Medical assistant & parent",
            "Reliable wages meet a tight household budget, medical expenses, and an overdue utility bill.",
            "Protect household essentials and rebuild cash reserves.",
            "One adult and one child",
            "6653",
            "1948",
            1710,
            15,
            500,
        ),
        Person(
            "marcus",
            "Marcus Bennett",
            "Warehouse associate",
            "Reduced shifts and an unexpected car repair have left rent and essential services overdue.",
            "Triage overdue essentials and contact providers before borrowing more.",
            "One adult",
            "2097",
            "7425",
            900,
            15,
            100,
        ),
    )
}


def person(profile_id: str) -> Person:
    if not isinstance(profile_id, str) or profile_id not in PEOPLE:
        raise ValueError("Choose one of the fictional demo people.")
    return PEOPLE[profile_id]


def catalog() -> list[dict]:
    return [p.public() for p in PEOPLE.values()]


# Monthly invoices/paychecks from May through the partial November snapshot.
RECIPES = {
    "jordan": {
        "seed": 3174,
        "cash": 2750,
        "savings": 900,
        "withdraw": 250,
        "income": [3200, 4850, 2800, 4600, 3100, 4300, 1600],
        "employer": "Reyes Studio client invoices",
        "debts": [13800, 0, 19000],
        "variables": [540, 150, 260, 160, 85],
        "grocer": "Green Basket Co-op",
        "bills": [
            ("Rent", "Maple Court Apartments", "Housing", 1550, 1, 50, 5, 900, 10, 0),
            ("Electricity", "Metro Electric", "Utilities", 128, 18, 20, 5, 250, 14, 0),
            ("Natural Gas", "City Gas", "Utilities", 64, 19, 12, 5, 200, 14, 0),
            ("Internet", "Fiber Lane", "Utilities", 85, 23, 10, 3, 70, 14, 0),
            ("Mobile Phone", "Clear Mobile", "Utilities", 75, 21, 10, 3, 80, 14, 0),
            ("Auto Insurance", "Metro Mutual", "Insurance", 105, 22, 15, 0, 450, 3, 0),
            (
                "Credit Card Minimum",
                "Civic Credit",
                "Debt payments",
                420,
                17,
                35,
                0,
                160,
                15,
                0.259,
            ),
            ("Student Loan", "Education Path", "Debt payments", 350, 25, 0, 15, 80, 30, 0.061),
            ("Streaming & Apps", "Design Cloud & Music", "Subscriptions", 24, 27, 0, 0, 0, 30, 0),
        ],
    },
    "aisha": {
        "seed": 6653,
        "cash": 980,
        "savings": 2100,
        "withdraw": 400,
        "income": [3420, 3460, 3400, 3480, 3450, 3420, 1710],
        "employer": "Riverbend Medical Center payroll",
        "debts": [8700, 6800, 1200],
        "variables": [660, 160, 75, 55, 140],
        "grocer": "Family Fresh Market",
        "bills": [
            ("Rent", "Cedar Grove Homes", "Housing", 1600, 1, 65, 5, 1100, 10, 0),
            ("Electricity", "River Power", "Utilities", 186, 8, 22, 5, 350, 12, 0),
            ("Natural Gas", "Community Gas", "Utilities", 92, 19, 15, 5, 240, 14, 0),
            ("Internet", "HomeLink", "Utilities", 68, 20, 10, 3, 70, 14, 0),
            ("Mobile Phone", "Family Wireless", "Utilities", 112, 22, 12, 3, 100, 14, 0),
            ("Auto Insurance", "Oak Shield", "Insurance", 196, 17, 20, 0, 600, 3, 0),
            (
                "Auto Loan",
                "Community Auto Finance",
                "Debt payments",
                320,
                18,
                25,
                7,
                500,
                20,
                0.079,
            ),
            (
                "Credit Card Minimum",
                "Harbor Family Card",
                "Debt payments",
                240,
                16,
                35,
                0,
                170,
                15,
                0.279,
            ),
            ("Student Loan", "Campus Servicing", "Debt payments", 100, 26, 0, 15, 70, 30, 0.052),
            ("Streaming & Apps", "Family Film", "Subscriptions", 12, 28, 0, 0, 0, 30, 0),
        ],
    },
    "marcus": {
        "seed": 2097,
        "cash": 215,
        "savings": 75,
        "withdraw": 350,
        "income": [4300, 4100, 3800, 2800, 2600, 2450, 900],
        "employer": "Pineworks Logistics payroll",
        "debts": [19850, 14800, 0],
        "variables": [420, 210, 110, 35, 65],
        "grocer": "Value Pantry",
        "bills": [
            ("Rent", "Eastbank Rentals", "Housing", 1725, 1, 85, 5, 1300, 10, 0),
            ("Electricity", "County Energy", "Utilities", 248, 5, 25, 3, 400, 7, 0),
            ("Natural Gas", "North County Gas", "Utilities", 135, 19, 18, 5, 250, 14, 0),
            ("Internet", "Broadway Broadband", "Utilities", 85, 22, 12, 3, 80, 14, 0),
            ("Mobile Phone", "Metro Talk", "Utilities", 124, 9, 15, 3, 150, 10, 0),
            ("Auto Insurance", "Roadsafe Mutual", "Insurance", 225, 20, 25, 0, 700, 3, 0),
            ("Auto Loan", "Summit Auto Credit", "Debt payments", 440, 17, 35, 5, 650, 14, 0.119),
            (
                "Credit Card Minimum",
                "Capital Bridge Card",
                "Debt payments",
                585,
                18,
                40,
                0,
                200,
                15,
                0.299,
            ),
        ],
    },
}


def _seeded_records(profile_id: str) -> dict:
    p, recipe = person(profile_id), RECIPES[profile_id]
    rng = random.Random(recipe["seed"])
    tx, bill_history, income_history = [], [], []
    current_bills = []

    def entry(date, merchant, amount, category, description, account="Checking", recurring=False):
        tx.append(
            {
                "transaction_id": f"TX-{profile_id.upper()}-{len(tx) + 1:05d}",
                "date": pd.Timestamp(date),
                "merchant": merchant,
                "amount": round(float(amount), 2),
                "category": category,
                "transaction_type": "Income"
                if category == "Income"
                else "Transfer"
                if category == "Transfers"
                else "Payment"
                if recurring
                else "Purchase",
                "payment_method": ("Client ACH" if profile_id == "jordan" else "Direct deposit")
                if category == "Income"
                else ("Internal transfer" if merchant == "Internal transfer" else "Card payment")
                if category == "Transfers"
                else "Bank payment"
                if recurring
                else "Credit card"
                if account == "Credit Card"
                else "Debit card",
                "description": description,
                "recurrence": "Recurring" if recurring else "One-time",
                "account": account,
            }
        )

    for month in range(5, 12):
        end = min(dt.date(2026, month, calendar.monthrange(2026, month)[1]), f.AS_OF)
        monthly_income = recipe["income"][month - 5]
        paydays = (3 + month % 5, 20 + month % 8) if profile_id == "jordan" else (1, 15)
        for i, day in enumerate(paydays):
            share = (0.65, 0.35)[i] if profile_id == "jordan" else 0.5
            amount = monthly_income if month == 11 and i == 0 else round(monthly_income * share, 2)
            date = dt.date(2026, month, day)
            if date > end:
                continue
            entry(
                date,
                recipe["employer"],
                amount,
                "Income",
                "Client invoice settled" if profile_id == "jordan" else "Net wages received",
                recurring=True,
            )
            income_history.append(
                {
                    "date": pd.Timestamp(date),
                    "amount": amount,
                    "source": recipe["employer"],
                    "type": "Net income",
                    "scheduled_date": date,
                    "delayed": False,
                }
            )
        for name, provider, category, amount, day, fee, grace, risk, riskdays, apr in recipe[
            "bills"
        ]:
            due = dt.date(2026, month, day)
            overdue_now = month == 11 and (
                (profile_id == "aisha" and name == "Electricity")
                or (profile_id == "marcus" and name in {"Rent", "Electricity", "Mobile Phone"})
            )
            paid_date = due + dt.timedelta(
                days=(
                    3 + month % 4
                    if profile_id == "marcus"
                    else 2
                    if profile_id == "jordan" and month in {7, 9}
                    else 0
                )
            )
            paid = paid_date <= end and not overdue_now
            status = (
                "Paid late"
                if paid and paid_date > due
                else "Paid on time"
                if paid
                else "Unpaid overdue"
                if due < end
                else "Upcoming"
            )
            if paid:
                category_paid = "Transfers" if name == "Credit Card Minimum" else category
                entry(
                    paid_date, provider, -amount, category_paid, name + " payment", recurring=True
                )
                if name == "Credit Card Minimum":
                    entry(
                        paid_date,
                        provider,
                        amount,
                        "Transfers",
                        "Card payment received",
                        "Credit Card",
                        True,
                    )
            bill_history.append(
                {
                    "bill_id": f"B-{profile_id}-{month:02d}-{name.replace(' ', '-')}",
                    "provider": provider,
                    "bill_name": name,
                    "category": category,
                    "original_amount": amount,
                    "due_date": due,
                    "payment_date": paid_date if paid else None,
                    "amount_paid": amount if paid else 0.0,
                    "status": status,
                    "late_fee_paid": 0.0,
                    "minimum_payment": amount if category == "Debt payments" else 0,
                    "grace_period_days": grace,
                    "confirmed_arrangement": False,
                    "extension_days": 0,
                    "partial_payment": False,
                }
            )
            if month == 11 and not paid:
                consequence = (
                    "Housing stability risk; contact the property manager"
                    if category == "Housing"
                    else "Possible service interruption; verify provider notices"
                    if category == "Utilities"
                    else "Coverage lapse risk; confirm insurer terms"
                    if category == "Insurance"
                    else "Interest and payment-history risk; confirm lender terms"
                    if category == "Debt payments"
                    else "Service may pause; confirm terms"
                )
                current_bills.append(
                    f.Bill(
                        f"B-{profile_id}-{name.replace(' ', '-')}",
                        name,
                        provider,
                        category,
                        amount,
                        due,
                        amount if category == "Debt payments" else 0,
                        fee,
                        apr,
                        grace,
                        consequence,
                        risk,
                        riskdays,
                        partial_allowed=name
                        in {"Credit Card Minimum", "Auto Loan", "Student Loan"},
                        status="Overdue" if overdue_now else "Upcoming",
                    )
                )
        # The next fixed lease obligation exists even when last month's rent is
        # still unpaid; arrears must not hide another rent inside the 30-day window.
        if month == 11:
            name, provider, category, amount, _, fee, grace, risk, riskdays, apr = recipe["bills"][
                0
            ]
            current_bills.append(
                f.Bill(
                    f"B-{profile_id}-RENT-DEC",
                    name,
                    provider,
                    category,
                    amount,
                    dt.date(2026, 12, 1),
                    0,
                    fee,
                    apr,
                    grace,
                    "Housing stability risk; contact the property manager",
                    risk,
                    riskdays,
                    partial_allowed=False,
                )
            )
        for category, budget, count, merchants in (
            (
                "Groceries",
                recipe["variables"][0],
                10,
                [recipe["grocer"], recipe["grocer"] + " Local"],
            ),
            (
                "Transportation",
                recipe["variables"][1],
                4,
                ["City Metro" if profile_id == "jordan" else "Main Street Fuel"],
            ),
            (
                "Dining & Entertainment",
                recipe["variables"][2],
                6,
                ["Corner Kitchen" if profile_id == "jordan" else "Community Cafe"],
            ),
            (
                "Shopping",
                recipe["variables"][3],
                2,
                ["Studio Supply" if profile_id == "jordan" else "Neighborhood Essentials"],
            ),
            (
                "Medical",
                recipe["variables"][4],
                2,
                ["Family Pharmacy" if profile_id == "aisha" else "Carewell Pharmacy"],
            ),
        ):
            for i in range(count):
                date = dt.date(2026, month, min(2 + round(i * 26 / max(count - 1, 1)), 28))
                if date <= end:
                    amount = round(budget / count * rng.uniform(0.86, 1.14), 2)
                    account = (
                        "Credit Card"
                        if rng.random() < (0.08 if profile_id == "aisha" else 0.12)
                        else "Checking"
                    )
                    entry(
                        date,
                        rng.choice(merchants),
                        -amount,
                        category,
                        f"{category} purchase",
                        account,
                    )
        if month < 11:
            amount = recipe["withdraw"]
            date = dt.date(2026, month, 13)
            for account, signed in (("Checking", amount), ("Savings", -amount)):
                entry(
                    date,
                    "Internal transfer",
                    signed,
                    "Transfers",
                    "Savings used to bridge household cash flow",
                    account,
                )
            card_apr = next(b[-1] for b in recipe["bills"] if b[0] == "Credit Card Minimum")
            entry(
                dt.date(2026, month, 28),
                "Card finance charge",
                -round(recipe["debts"][0] * card_apr / 12, 2),
                "Fees",
                "Recorded credit-card interest",
                "Credit Card",
            )
    if profile_id == "jordan":
        entry(
            dt.date(2026, 8, 11),
            "Studio Laptop Repair",
            -390,
            "Shopping",
            "Unexpected business laptop repair",
        )
    if profile_id == "aisha":
        entry(
            dt.date(2026, 7, 12),
            "Riverbend Pediatric Clinic",
            -340,
            "Medical",
            "Out-of-pocket medical bill",
        )
    if profile_id == "marcus":
        entry(
            dt.date(2026, 11, 10),
            "Eastside Auto Repair",
            -920,
            "Transportation",
            "Unexpected repair needed to get to work",
        )
    transactions = pd.DataFrame(tx).sort_values(["date", "transaction_id"]).reset_index(drop=True)
    opening = {
        "Checking": round(
            recipe["cash"] - transactions.loc[transactions.account.eq("Checking"), "amount"].sum(),
            2,
        ),
        "Savings": recipe["savings"] + recipe["withdraw"] * 6,
    }
    if opening["Checking"] < 0:
        raise ValueError(f"The {p.name} fixture needs a valid opening cash balance.")
    targets = dict(zip(("Credit Card", "Auto Loan", "Student Loan"), recipe["debts"]))
    loan_terms = {
        name: apr
        for name, _, _, _, _, _, _, _, _, apr in recipe["bills"]
        if name in {"Auto Loan", "Student Loan"}
    }
    initial_debt = {
        "Credit Card": targets["Credit Card"]
        + transactions.loc[transactions.account.eq("Credit Card"), "amount"].sum()
    }
    for loan, apr in loan_terms.items():
        paid = -transactions.loc[transactions.description.eq(loan + " payment"), "amount"].sum()
        initial_debt[loan] = (targets[loan] + paid * 0.85) / (1 + apr / 12) ** 7
    balances, debts = [], []
    for month in range(5, 12):
        end = min(dt.date(2026, month, calendar.monthrange(2026, month)[1]), f.AS_OF)
        subset = transactions.loc[transactions.date.dt.date <= end]
        cash = {
            account: round(
                opening[account] + subset.loc[subset.account.eq(account), "amount"].sum(), 2
            )
            for account in opening
        }
        balances.append(
            {
                "month": pd.Timestamp(end),
                "checking": cash["Checking"],
                "savings": cash["Savings"],
                "total_cash": round(sum(cash.values()), 2),
            }
        )
        debt = {
            "Credit Card": round(
                initial_debt["Credit Card"]
                - subset.loc[subset.account.eq("Credit Card"), "amount"].sum(),
                2,
            ),
            "Auto Loan": 0.0,
            "Student Loan": 0.0,
        }
        for loan, apr in loan_terms.items():
            paid = -subset.loc[subset.description.eq(loan + " payment"), "amount"].sum()
            debt[loan] = round(
                max(0, initial_debt[loan] * (1 + apr / 12) ** (month - 4) - paid * 0.85), 2
            )
        debts.append(
            {"month": pd.Timestamp(end), **debt, "total_debt": round(sum(debt.values()), 2)}
        )
    return {
        "transactions": transactions,
        "bill_history": pd.DataFrame(bill_history),
        "income_history": pd.DataFrame(income_history),
        "balance_history": pd.DataFrame(balances),
        "debt_history": pd.DataFrame(debts),
        "bills": current_bills,
        "opening": opening,
        "opening_debt": initial_debt,
    }


@lru_cache(maxsize=len(PEOPLE))
def _template(profile_id: str) -> dict:
    person(profile_id)
    return f.generate_demo_records() if profile_id == "maya" else _seeded_records(profile_id)


class DemoAccount(f.AccountStore):
    def __init__(self, profile_id: str):
        import copy

        self.profile = person(profile_id).public()
        super().__init__(copy.deepcopy(_template(profile_id)))
        p = person(profile_id)
        self.preferences = {
            "paycheck": p.paycheck,
            "payday": dt.date(2026, 11, p.payday),
            "reserve": p.reserve,
        }

    def reset(self):
        fresh = DemoAccount(self.profile["id"])
        with self.lock:
            self.records, self.preferences = fresh.records, fresh.preferences
