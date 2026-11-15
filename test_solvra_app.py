import datetime as dt

import pandas as pd
import pytest

import solvra_app as app


def test_demo_is_populated_reproducible_and_ledger_backed():
    first = app.generate_demo_records()
    second = app.generate_demo_records()

    assert 800 <= len(first["transactions"]) <= 1200
    assert first["transactions"].transaction_id.is_unique
    pd.testing.assert_frame_equal(first["transactions"], second["transactions"])
    assert first["transactions"].date.min().date() == dt.date(2024, 11, 15)
    assert first["transactions"].date.max().date() == app.AS_OF
    assert len(first["income_history"]) >= 48

    for account, balance_column in (("Checking", "checking"), ("Savings", "savings")):
        ledger = first["transactions"].query("account == @account").sort_values("date")
        ending_balance = first["opening"][account] + ledger.amount.sum()
        assert ending_balance >= 0
        assert ending_balance == pytest.approx(
            first["balance_history"].iloc[-1][balance_column], abs=0.02
        )

    statuses = set(first["bill_history"].status)
    assert {"Paid on time", "Paid late", "Upcoming"}.issubset(statuses)


def test_synthetic_bill_terms_and_installment_ledger_are_consistent():
    records = app.generate_demo_records()
    history = records["bill_history"]
    required_terms = {
        "late_fee_terms",
        "interest_rate_apr",
        "grace_period_days",
        "consequence",
        "modeled_consequence_weight",
        "risk_deadline_days",
        "partial_allowed",
        "extension_terms",
    }
    assert required_terms.issubset(history.columns)

    electricity = history.loc[
        history.bill_name.eq("Electricity")
        & history.due_date.astype(str).str.startswith("2025-08")
    ].iloc[0]
    assert electricity.status == "Paid late (installments)"
    assert electricity.amount_paid == pytest.approx(electricity.original_amount)
    assert electricity.payment_date == dt.date(2025, 9, 4)

    ledger = records["transactions"]
    payment_rows = ledger.loc[
        ledger.description.str.contains("Electricity", case=False)
        & ledger.description.str.contains("payment|catch-up", case=False)
        & ledger.date.dt.date.isin([dt.date(2025, 8, 24), dt.date(2025, 9, 4)])
    ]
    assert -payment_rows.amount.sum() == pytest.approx(electricity.original_amount)
    assert payment_rows.description.str.contains("catch-up").any()


def test_optimizer_respects_cash_timing_minimum_and_all_or_nothing():
    scenario = app.Scenario(
        available_cash=30,
        as_of=dt.date(2026, 11, 14),
        bills=[
            app.Bill(
                "card",
                "Card minimum",
                "Issuer",
                "Debt payments",
                100,
                dt.date(2026, 11, 15),
                50,
                30,
                0.24,
                0,
                "credit risk",
                150,
                14,
                partial_allowed=True,
            ),
            app.Bill(
                "whole",
                "One payment",
                "Provider",
                "Housing",
                200,
                dt.date(2026, 11, 16),
                0,
                40,
                0,
                0,
                "housing risk",
                600,
                4,
                partial_allowed=False,
            ),
        ],
        incomes=[app.IncomeEvent(270, dt.date(2026, 11, 17))],
        reserve=0,
        horizon_days=35,
    )

    result = app.optimize(scenario)
    assert result.feasible
    for payment_date in app._payment_events(scenario):
        spent = sum(p["amount"] for p in result.payments if p["date"] <= payment_date)
        assert spent <= app._available_by_date(scenario, payment_date) + 0.02

    card_paid_by_due = sum(
        p["amount"]
        for p in result.payments
        if p["bill_id"] == "card" and p["date"] <= dt.date(2026, 11, 15)
    )
    assert card_paid_by_due == 0 or card_paid_by_due >= 49.98
    whole_bill_payments = [p for p in result.payments if p["bill_id"] == "whole"]
    assert not whole_bill_payments or (
        len(whole_bill_payments) == 1
        and whole_bill_payments[0]["amount"] == pytest.approx(200)
    )


def test_baselines_and_optimizer_use_the_same_constraints():
    scenario = app.Scenario(
        available_cash=420,
        as_of=dt.date(2026, 11, 14),
        bills=[
            app.Bill(
                "a",
                "Small",
                "Provider",
                "Utilities",
                75,
                dt.date(2026, 11, 16),
                0,
                20,
                0.1,
                2,
                "service",
                100,
                7,
                partial_allowed=True,
            ),
            app.Bill(
                "b",
                "Critical",
                "Landlord",
                "Housing",
                500,
                dt.date(2026, 11, 15),
                0,
                0,
                0,
                0,
                "housing",
                800,
                2,
                partial_allowed=False,
            ),
        ],
        incomes=[app.IncomeEvent(100, dt.date(2026, 11, 18))],
        reserve=0,
        horizon_days=35,
    )

    results = app.run_all_strategies(scenario)
    assert len(results) == 4
    for result in results:
        assert result.feasible
        assert result.total_allocated <= 520.02
        assert result.unpaid >= 0


def test_only_confirmed_extensions_change_the_optimizer_deadline():
    bill = app.Bill(
        "utility",
        "Electricity",
        "Provider",
        "Utilities",
        100,
        dt.date(2026, 11, 20),
        confirmed_extension=False,
        extension_date=dt.date(2026, 11, 25),
    )
    assert bill.effective_due == dt.date(2026, 11, 20)
    bill.confirmed_extension = True
    assert bill.effective_due == dt.date(2026, 11, 25)


def test_extraction_handles_known_missing_and_ambiguous_values():
    results, metrics = app.extraction_test_suite()
    assert metrics["field_accuracy"] == 1.0
    assert len(results) > 10

    whole_dollar_bill = app.extract_bill_fields(
        "ComEd\nAmount Due: $100\nDue Date: 11/30/2026"
    )
    assert whole_dollar_bill["fields"]["amount"] == 100.0
    assert whole_dollar_bill["fields"]["provider"] == "ComEd"

    ambiguous = app.extract_bill_fields(
        "Utility Statement\nAmount Due: $140 or $160\nDue Date: 11/30/2026"
    )
    assert ambiguous["fields"]["amount"] is None
    assert "review" in ambiguous["confidence"]["amount"]

    missing = app.extract_bill_fields("A provider\nDue Date: 11/30/2026")
    assert missing["fields"]["amount"] is None
    assert missing["fields"]["late_fee"] is None


def test_account_updates_require_confirmation_and_sync_the_ledger():
    store = app.AccountStore(app.generate_demo_records())
    initial_balance = store.balance("Checking")
    message, pending = app.answer_financial_question("I just received $200", store)

    assert pending and "Confirm" in message
    assert store.balance("Checking") == initial_balance
    app.confirm_account_update(pending, False, store)
    assert store.balance("Checking") == initial_balance

    confirmation = app.confirm_account_update(pending, True, store)
    assert "Confirmed" in confirmation
    assert store.balance("Checking") == pytest.approx(initial_balance + 200)
    assert store.records["income_history"].iloc[-1].amount == 200


def test_dashboard_ranges_use_exact_dates_and_match_ledger_values():
    charts = app.dashboard_charts(app.DEMO, "Last 30 days")
    cashflow, spending_mix, cash_balances, debt, categories, essentials = charts
    cutoff = app.AS_OF - dt.timedelta(days=29)
    x_values = pd.to_datetime(cash_balances.data[0].x)

    assert len(x_values) == 30
    assert x_values[0].date() == cutoff
    assert cash_balances.data[0].y[-1] == pytest.approx(app.DEMO.balance("Checking"))
    assert cash_balances.data[1].y[-1] == pytest.approx(app.DEMO.balance("Savings"))

    tx = app.DEMO.transactions
    recent = tx[(tx.date.dt.date >= cutoff) & (tx.date.dt.date <= app.AS_OF)]
    expected_income = recent.loc[
        (recent.category == "Income") & (recent.amount > 0), "amount"
    ].sum()
    expected_expenses = -recent.loc[
        (recent.amount < 0) & (~recent.category.isin(["Transfers", "Income"])), "amount"
    ].sum()
    assert sum(cashflow.data[0].y) == pytest.approx(expected_income)
    assert sum(cashflow.data[1].y) == pytest.approx(expected_expenses)
    assert sum(spending_mix.data[0].values) == pytest.approx(
        app.category_spending(app.DEMO, cutoff, app.AS_OF).spending.sum()
    )
    assert len(debt.data) == 3
    assert len(categories.data) > 0
    assert len(essentials.data) == 2

    weekly_charts = app.dashboard_charts(app.DEMO, "Last 90 days")
    assert 12 <= len(weekly_charts[0].data[0].x) <= 14


def test_dashboard_report_and_health_score_are_populated():
    assert len(app.DEMO.transactions) >= 800
    assert not app.upcoming_frame(app.DEMO).empty
    assert len(app.dashboard_charts(app.DEMO, "Entire 24-month history")) == 6

    report = app.personal_report(app.DEMO, None)
    assert {
        "income",
        "expenses",
        "net_cash_flow",
        "savings",
        "total_debt",
        "late_payments",
    }.issubset(report.columns)
    score, factors, explanation = app.health_assessment(app.DEMO)
    assert 0 <= score <= 100
    assert len(factors) == 7
    assert factors.weight.sum() == pytest.approx(1.0)
    assert "income-to-expense" in explanation


def test_personal_csv_and_pdf_exports_are_created():
    csv_path = app.export_personal_csv(app.DEMO, 90)
    category_path = app.export_category_csv(app.DEMO, 90)
    pdf_path = app.export_personal_pdf(app.DEMO, 90)

    assert pd.read_csv(csv_path).shape[0] > 0
    assert pd.read_csv(category_path).shape[0] > 0
    with open(pdf_path, "rb") as report:
        assert report.read(4) == b"%PDF"


def test_held_out_evaluation_uses_all_four_strategies():
    scenarios, labels = app.generate_evaluation_scenarios()
    assert len(scenarios) == 500
    assert labels.count("development") == 350
    assert labels.count("held-out test") == 150

    summary, detail = app.evaluate_benchmarks(force=True)
    assert len(detail) == 150 * 4
    assert set(detail.strategy) == {
        "Earliest Due Date",
        "Smallest Bill First",
        "Largest Bill First",
        "Intelligent optimization",
    }
    assert summary.average_modeled_harm.notna().all()
    assert summary.feasibility_rate.between(0, 1).all()


def test_gradio_interface_builds_without_launching_a_tunnel():
    interface = app.launch_app(share=False)
    assert interface is not None
    assert len(interface.blocks) >= 200
