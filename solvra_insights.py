"""Ledger-derived views and explainable recommendations. No invented account facts."""

from __future__ import annotations

import calendar
import copy
import datetime as dt
from dataclasses import dataclass
from typing import Any

import pandas as pd

import solvra_app as f
from solvra_savings_model import (
    CATEGORIES as SAVINGS_CATEGORIES,
    recommend as savings_recommendation,
)


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def previous(self) -> Period:
        # Compare a partial month to the same days, not to a complete month.
        if self.start == self.end.replace(day=1):
            end = self.start - dt.timedelta(days=1)
            start = end.replace(day=1)
            if self.end.day < calendar.monthrange(self.end.year, self.end.month)[1]:
                end = end.replace(day=min(self.end.day, end.day))
            return Period(start, end, f"{start:%b} {start.day}–{end.day}")
        end = self.start - dt.timedelta(days=1)
        start = end - dt.timedelta(days=self.days - 1)
        return Period(start, end, f"{start:%b %d}–{end:%b %d}")


def reporting_period(key: str = "month") -> Period:
    if key == "last_month":
        start, end = f._last_month_bounds()
        return Period(start, end, f"{start:%B %Y}")
    if key == "90days":
        return Period(f.AS_OF - dt.timedelta(days=89), f.AS_OF, "Last 90 days")
    return Period(f.AS_OF.replace(day=1), f.AS_OF, "November so far")


def period_transactions(account: f.AccountStore, period: Period) -> pd.DataFrame:
    tx = account.transactions
    return tx.loc[(tx.date.dt.date >= period.start) & (tx.date.dt.date <= period.end)]


def spending_rows(account: f.AccountStore, period: Period) -> pd.DataFrame:
    tx = period_transactions(account, period)
    return tx.loc[(tx.amount < 0) & ~tx.category.isin(["Transfers", "Income"])]


def totals(account: f.AccountStore, period: Period) -> dict[str, float]:
    tx = period_transactions(account, period)
    income = float(tx.loc[(tx.amount > 0) & tx.category.eq("Income"), "amount"].sum())
    spent = float(-spending_rows(account, period).amount.sum())
    return {
        "income": round(income, 2),
        "spending": round(spent, 2),
        "net": round(income - spent, 2),
    }


def planning_buffer(account: f.AccountStore, reserve: float | None = None) -> dict[str, float]:
    """Conservative, explicitly modeled 30-day headroom. Expected income is excluded."""
    checking = account.balance("Checking")
    bills = sum(b.amount for b in f.current_open_bills(account, 30))
    reserve = float(account.preferences.get("reserve", 1000) if reserve is None else reserve)
    history = spending_rows(account, reporting_period("90days"))
    variable = history.loc[
        history.category.isin(
            [
                "Groceries",
                "Transportation",
                "Medical",
                "Dining & Entertainment",
                "Shopping",
            ]
        )
    ]
    allowance = round(float(-variable.amount.sum()) / 90 * 30, 2)
    return {
        "checking": checking,
        "bills": round(bills, 2),
        "reserve": reserve,
        "everyday_allowance": allowance,
        "headroom": round(checking - bills - reserve - allowance, 2),
    }


def bill_dict(bill: f.Bill) -> dict[str, Any]:
    return {
        "id": bill.bill_id,
        "name": bill.name,
        "provider": bill.provider,
        "category": bill.category,
        "amount": bill.amount,
        "due": bill.effective_due.isoformat(),
        "days": (bill.effective_due - f.AS_OF).days,
        "minimum": bill.minimum_payment,
        "late_fee": bill.late_fee,
        "grace_days": bill.grace_days,
        "apr": bill.apr,
        "consequence": bill.consequence,
        "partial_allowed": bill.partial_allowed,
        "extended": bill.confirmed_extension,
        "status": bill.status,
    }


def transaction_dict(row: dict) -> dict:
    return {
        "id": str(row["transaction_id"]),
        "date": pd.Timestamp(row["date"]).date().isoformat(),
        "merchant": str(row["merchant"]),
        "amount": round(float(row["amount"]), 2),
        "category": str(row["category"]),
        "account": str(row["account"]),
        "description": str(row["description"]),
        "type": str(row["transaction_type"]),
        "method": str(row.get("payment_method", "Recorded")),
    }


def insights(account: f.AccountStore, period: Period | None = None) -> list[dict]:
    period = period or reporting_period()
    result = []
    bills = f.current_open_bills(account)
    if bills:
        first = bills[0]
        due = sum(b.amount for b in f.current_open_bills(account, 14))
        covered = account.balance("Checking") >= due
        result.append(
            {
                "id": "bills",
                "icon": "calendar",
                "tone": "sage" if covered else "amber",
                "eyebrow": "OVERDUE & UPCOMING"
                if first.effective_due < f.AS_OF
                else "UPCOMING BILLS",
                "title": "An overdue essential needs attention"
                if first.effective_due < f.AS_OF
                else "Your next bills are covered"
                if covered
                else "A bill gap needs a plan",
                "description": f"{f.money(due)} due through the next 14 days, including arrears. "
                + (
                    f"{first.name} was due {f._spoken_date(first.effective_due)}."
                    if first.effective_due < f.AS_OF
                    else f"{first.name} is next, on {f._spoken_date(first.effective_due)}."
                ),
                "metric": f.money(due),
                "prompt": "Build my bill payment plan and explain the order.",
                "evidence": [
                    f"Checking ledger: {f.money(account.balance('Checking'))}",
                    f"{len(f.current_open_bills(account, 14))} unpaid bills due through {f._spoken_date(f.AS_OF + dt.timedelta(days=14))}",
                ],
            }
        )
    now = spending_rows(account, period).groupby("category").amount.sum().abs()
    prev = spending_rows(account, period.previous).groupby("category").amount.sum().abs()
    changes = [
        (c, float(v), float(prev.get(c, 0)), float(v - prev.get(c, 0))) for c, v in now.items()
    ]
    changes = [
        x for x in changes if x[2] >= 20 and x[0] not in {"Housing", "Debt payments", "Fees"}
    ]
    if changes:
        c, value, before, delta = max(changes, key=lambda x: abs(x[3]))
        direction = "up" if delta > 0 else "down"
        result.append(
            {
                "id": "spending",
                "icon": "trend",
                "tone": "peach" if delta > 0 else "sage",
                "eyebrow": "SPENDING PATTERN",
                "title": f"{c} is {direction} {abs(delta / before * 100):.0f}%",
                "description": f"{f.money(value)} versus {f.money(before)} over the comparable previous period.",
                "metric": f"{abs(delta / before * 100):.0f}%",
                "prompt": f"Compare my {c.lower()} spending from {period.start.isoformat()} to {period.end.isoformat()} with the previous period.",
                "evidence": [
                    f"Current window: {period.start.isoformat()} – {period.end.isoformat()}",
                    f"Comparison: {period.previous.start.isoformat()} – {period.previous.end.isoformat()}",
                    "Purchases and bill payments; transfers excluded.",
                ],
            }
        )
    essentials = f.essential_monthly_expense(account)
    savings = account.balance("Savings")
    coverage = savings / max(essentials, 1)
    gap = max(0, essentials * 3 - savings)
    result.append(
        {
            "id": "savings",
            "icon": "shield",
            "tone": "lavender",
            "eyebrow": "YOUR SAFETY NET",
            "title": f"{coverage:.1f} months of breathing room",
            "description": f"Savings cover {coverage:.1f} months of recent essentials. "
            + (
                f"Another {f.money(gap)} would reach a modeled 3-month buffer."
                if gap > 0
                else "Your modeled 3-month buffer is covered."
            ),
            "metric": f"{coverage:.1f} mo",
            "prompt": "How can I build a stronger emergency fund?",
            "evidence": [
                f"Savings ledger: {f.money(savings)}",
                f"6-month average essentials: {f.money(essentials)}/month",
                "3 months is a planning target, not a guarantee.",
            ],
        }
    )
    return result


TRIAGE_SCALE = [
    {
        "rank": 1,
        "level": "critical",
        "label": "Critical",
        "min": 70,
        "max": 100,
        "action": "Act now: protect essentials and contact providers.",
    },
    {
        "rank": 2,
        "level": "high",
        "label": "High",
        "min": 40,
        "max": 69,
        "action": "Make a plan this week; resolve overdue essentials first.",
    },
    {
        "rank": 3,
        "level": "watch",
        "label": "Watch",
        "min": 20,
        "max": 39,
        "action": "Watch cash timing and rebuild a buffer.",
    },
    {
        "rank": 4,
        "level": "stable",
        "label": "Stable",
        "min": 0,
        "max": 19,
        "action": "Keep building savings and review debt goals.",
    },
]


def financial_trouble(account: f.AccountStore) -> dict:
    """Deterministic triage v1: pressure points, not a probability or credit score.

    Fixed snapshot windows deliberately ignore the dashboard's reporting selector.
    Safety floors prevent a funded long-term average from hiding urgent arrears.
    No other person's finances participate in this assessment.
    """
    bills = f.current_open_bills(account)
    checking, savings = account.balance("Checking"), account.balance("Savings")
    due14 = sum(b.amount for b in f.current_open_bills(account, 14))
    gap14 = max(0, due14 - checking)
    overdue = [b for b in bills if b.effective_due < f.AS_OF]
    essentials = [b for b in overdue if b.category in {"Housing", "Utilities", "Insurance"}]
    max_age = max(((f.AS_OF - b.effective_due).days for b in essentials), default=0)
    essential_arrears = sum(b.amount for b in essentials)
    buffer = planning_buffer(account)
    monthly = f.monthly_summary(account)
    completed = monthly.loc[monthly.month.dt.date < f.AS_OF.replace(day=1)].tail(3)
    income = float(completed.income.mean()) if not completed.empty else 0
    spending = float(completed.expenses.mean()) if not completed.empty else 0
    deficit = max(0, spending - income)
    expense = f.essential_monthly_expense(account)
    coverage = max(0, savings) / max(expense, 1)
    # One current cycle of required debt service, not total principal / income.
    # A paid bill may no longer be open, so use the most recent recorded cycle.
    history = account.records["bill_history"]
    debt_rows = history.loc[history.category.eq("Debt payments")].copy()
    debt_rows["cycle"] = pd.to_datetime(debt_rows.due_date).dt.to_period("M")
    cycle = pd.Period(f.AS_OF, freq="M")
    debt_rows = debt_rows.loc[debt_rows.cycle.eq(cycle)]
    service = float(debt_rows.groupby("bill_name").original_amount.max().sum())
    debt_ratio = service / max(income, 1)

    def factor(name, weight, severity, evidence, rule):
        return {
            "name": name,
            "max_points": weight,
            "points": round(weight * max(0, min(severity, 1)), 1),
            "evidence": evidence,
            "rule": rule,
        }

    factors = [
        factor(
            "Overdue essentials",
            30,
            min(30, 10 + 5 * len(essentials) + min(max_age, 10)) / 30 if essentials else 0,
            f"{len(essentials)} overdue housing, utility or insurance bills; {f.money(essential_arrears)} outstanding; oldest {max_age} days overdue.",
            "If any: 10 + 5 per overdue essential + up to 10 days of age; capped at 30.",
        ),
        factor(
            "14-day bill shortfall",
            25,
            gap14 / max(due14, 1),
            f"{f.money(due14)} due within 14 days (including arrears), against {f.money(checking)} in checking; gap {f.money(gap14)}.",
            "25 × uncovered share of 14-day bills; checking only.",
        ),
        factor(
            "30-day headroom pressure",
            15,
            max(0, -buffer["headroom"]) / max(income, 1),
            f"{f.money(buffer['headroom'])} after recorded bills, everyday allowance and a {f.money(buffer['reserve'])} reserve. Future income and savings excluded.",
            "15 × negative headroom / recent average monthly recorded income; capped at 15.",
        ),
        factor(
            "Recent cash-flow deficit",
            15,
            deficit / max(income * 0.2, 1),
            f"Last {len(completed)} completed months: average income {f.money(income)}, spending {f.money(spending)}, deficit {f.money(deficit)} per month.",
            "15 × monthly deficit / 20% of income; capped at 15. Transfers excluded.",
        ),
        factor(
            "Emergency savings gap",
            10,
            1 - min(coverage / 3, 1),
            f"{f.money(savings)} savings / {f.money(expense)} recent monthly essentials = {coverage:.2f} months.",
            "10 × shortfall from a modeled three-month savings buffer.",
        ),
        factor(
            "Required debt-service load",
            5,
            debt_ratio / 0.4,
            f"{f.money(service)} required debt payments / {f.money(income)} recent monthly income = {debt_ratio:.1%}. Recorded-income proxy, not lender DTI.",
            "5 × required debt service / 40% of recorded income; capped at 5.",
        ),
    ]
    raw = round(sum(x["points"] for x in factors))
    floor, override = 0, None
    if essentials:
        floor, override = (
            40,
            "An essential bill is overdue: urgency is at least High, even if the weighted total is lower.",
        )
    housing = [
        b
        for b in essentials
        if b.category == "Housing" and (f.AS_OF - b.effective_due).days > b.grace_days
    ]
    if housing and checking < essential_arrears:
        floor, override = (
            70,
            "Housing is overdue beyond its recorded grace period and checking cannot cover overdue essentials: urgency is at least Critical. This is not an eviction prediction.",
        )
    score = min(100, max(raw, floor))
    band = next(b for b in TRIAGE_SCALE if b["min"] <= score <= b["max"])
    priorities = sorted((x for x in factors if x["points"] > 0), key=lambda x: -x["points"])
    return {
        "version": "solvra-triage-v1",
        "as_of": f.AS_OF.isoformat(),
        **band,
        "score": score,
        "raw_score": raw,
        "floor": floor,
        "override": override,
        "factors": factors,
        "scale": TRIAGE_SCALE,
        "drivers": priorities[:3],
        "metrics": {
            "checking": checking,
            "savings": savings,
            "bills_14_days": round(due14, 2),
            "bill_gap_14_days": round(gap14, 2),
            "overdue_total": round(sum(b.amount for b in overdue), 2),
            "overdue_essentials": round(essential_arrears, 2),
            "monthly_income": round(income, 2),
            "monthly_spending": round(spending, 2),
            "emergency_months": round(coverage, 2),
            "debt_service": round(service, 2),
        },
        "limits": "A fictional, rules-based planning triage, not a credit score, probability of default, diagnosis, lender DTI, or prediction of eviction or disconnection. Higher points mean more pressure; priority 1 is most urgent. Recorded terms and incomplete data may differ from real life. Expected income is unconfirmed; savings are not automatically spent. No comparison with other people is used.",
    }


def dashboard(account: f.AccountStore, period_key: str = "month") -> dict[str, Any]:
    period = reporting_period(period_key)
    current, previous = totals(account, period), totals(account, period.previous)
    bills = f.current_open_bills(account)
    cats = f.category_spending(account, period.start, period.end)
    monthly = f.monthly_summary(account).tail(6)
    balances = account.records["balance_history"].tail(6)
    score, factors = f.health_assessment(account)
    recent = account.transactions.sort_values(["date", "transaction_id"], ascending=False).head(6)
    model_period = reporting_period("90days")
    model_spend = spending_rows(account, model_period).groupby("category").amount.sum().abs()
    monthly_spend = {
        category: float(model_spend.get(category, 0.0)) * 30.0 / model_period.days
        for category in SAVINGS_CATEGORIES
    }
    monthly_income = max(0.0, float(current["income"])) * 30.0 / period.days
    savings_model = savings_recommendation(monthly_income, monthly_spend)
    return {
        "as_of": f.AS_OF.isoformat(),
        "period_key": period_key,
        "period": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "label": period.label,
            "previous_start": period.previous.start.isoformat(),
            "previous_end": period.previous.end.isoformat(),
        },
        "checking": account.balance("Checking"),
        "savings": account.balance("Savings"),
        "debt": account.debts(),
        "totals": current,
        "previous": previous,
        "buffer": planning_buffer(account),
        "savings_model": savings_model,
        "bills": [bill_dict(b) for b in bills],
        "bill_total": round(sum(b.amount for b in bills), 2),
        "categories": [
            {"name": r.category, "amount": round(float(r.spending), 2)} for r in cats.itertuples()
        ],
        "chart": [
            {
                "month": pd.Timestamp(r.month).strftime("%b"),
                "date": pd.Timestamp(r.month).date().isoformat(),
                "income": round(float(r.income), 2),
                "spending": round(float(r.expenses), 2),
                "partial": pd.Timestamp(r.month).month == f.AS_OF.month
                and pd.Timestamp(r.month).year == f.AS_OF.year,
            }
            for r in monthly.itertuples()
        ],
        "balances": [
            {
                "month": pd.Timestamp(r.month).strftime("%b"),
                "checking": round(float(r.checking), 2),
                "savings": round(float(r.savings), 2),
            }
            for r in balances.itertuples()
        ],
        "health": {"score": score, "factors": factors.to_dict("records")},
        "trouble": financial_trouble(account),
        "insights": insights(account, period),
        "recent": [transaction_dict(r) for r in recent.to_dict("records")],
        "transaction_count": len(account.transactions),
        "categories_all": sorted(set(account.transactions.category)),
        "accounts": sorted(set(account.transactions.account)),
        "paycheck": {
            "amount": float(account.preferences.get("paycheck", 2200)),
            "date": str(account.preferences.get("payday", f.AS_OF)),
            "confirmed": False,
        },
    }


def payment_plan(
    account: f.AccountStore, reserve: float = 1000, include_income: bool = False
) -> dict:
    scenario = f.scenario_from_account(account)
    scenario.reserve = reserve
    if include_income:
        date = account.preferences.get("payday", f.AS_OF)
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)
        if f.AS_OF <= date <= f.AS_OF + dt.timedelta(days=scenario.horizon_days):
            scenario.incomes = [
                f.IncomeEvent(
                    float(account.preferences.get("paycheck", 2200)),
                    date,
                    "Expected paycheck",
                    False,
                )
            ]
    result = f.optimize(scenario)
    paid: dict[str, float] = {}
    for p in result.payments:
        paid[p["bill_id"]] = paid.get(p["bill_id"], 0) + p["amount"]
    rows = []
    for p in sorted(
        result.payments,
        key=lambda x: (
            x["date"],
            account.find_bill(x["bill_id"]).effective_due,
            x["bill"],
        ),
    ):
        b = account.find_bill(p["bill_id"])
        rows.append(
            {
                "bill_id": b.bill_id,
                "bill": b.name,
                "date": p["date"].isoformat(),
                "amount": round(p["amount"], 2),
                "due": b.effective_due.isoformat(),
                "late": p["date"] > b.effective_due,
                "reason": f"Due {f._spoken_date(b.effective_due)}. "
                + (
                    f"Recorded late fee: {f.money(b.late_fee)} after {b.grace_days} grace days. "
                    if b.late_fee
                    else "No recorded late fee. "
                )
                + b.consequence
                + ".",
            }
        )
    return {
        "payments": rows,
        "allocated": round(result.total_allocated, 2),
        "unpaid": round(result.unpaid, 2),
        "remaining": round(
            account.balance("Checking")
            + sum(i.amount for i in scenario.incomes)
            - result.total_allocated,
            2,
        ),
        "reserve": reserve,
        "include_income": include_income,
        "late_fees": round(result.harm["late_fees"], 2),
        "interest": round(result.harm["interest"], 2),
        "risk_points": round(result.harm["critical_harm"], 2),
        "uncovered": [
            {
                "name": b.name,
                "amount": round(b.amount - paid.get(b.bill_id, 0), 2),
                "reason": b.consequence,
            }
            for b in scenario.bills
            if b.amount - paid.get(b.bill_id, 0) > 0.01
        ],
        "assumptions": [
            "Checking only; savings are untouched.",
            f"{f.money(reserve)} held back from bill payments.",
            (
                "Expected paycheck is included but unconfirmed."
                if scenario.incomes
                else "Expected paycheck is outside the 40-day horizon and is not counted."
            )
            if include_income
            else "Expected future income is not counted.",
            "Risk points are prioritization weights, NOT dollar costs. Provider terms may differ.",
            "A preview only. No money is moved and no payments are scheduled.",
        ],
    }


def delay_preview(account: f.AccountStore, bill_id: str, days: int) -> dict:
    bill = account.find_bill(bill_id)
    if not bill or bill.status == "Paid":
        raise ValueError("Choose an unpaid bill.")
    result = f.simulate_late_payment(copy.deepcopy(bill), days)
    return {
        "bill": bill.name,
        "days": days,
        "date": (bill.effective_due + dt.timedelta(days=days)).isoformat(),
        "late_fees": round(result.harm["late_fees"], 2),
        "interest": round(result.harm["interest"], 2),
        "risk": result.harm["critical_harm"] > 0,
        "consequence": bill.consequence,
        "provider": bill.provider,
        "unchanged": True,
    }
