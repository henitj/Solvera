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
        history.bill_name.eq("Electricity") & history.due_date.astype(str).str.startswith("2025-08")
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
        len(whole_bill_payments) == 1 and whole_bill_payments[0]["amount"] == pytest.approx(200)
    )


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


def test_account_updates_require_confirmation_and_sync_the_ledger():
    store = app.AccountStore(app.generate_demo_records())
    initial_balance = store.balance("Checking")
    message, pending = app.answer_financial_question("I just received $200", store)

    assert pending and "Confirm" in message
    assert store.balance("Checking") == initial_balance
    app.confirm_account_update(pending, False, store)
    assert store.balance("Checking") == initial_balance

    confirmation = app.confirm_account_update(pending, True, store)
    assert confirmation.startswith("Done")
    assert store.balance("Checking") == pytest.approx(initial_balance + 200)
    assert store.records["income_history"].iloc[-1].amount == 200


def test_editable_transaction_ledger_saves_valid_edits_and_adds_records():
    original = app.DEMO.records["transactions"].copy(deep=True)
    try:
        edited = app.transaction_table()
        edited.loc[0, "description"] = "Updated from table"
        saved, message, _ = app.save_transaction_table(edited)
        assert message == "Changes saved."
        assert saved.loc[0, "description"] == "Updated from table"

        before = len(saved)
        added, message, _ = app.add_manual_transaction(12.34, "Other", "Smoke test", "", "Purchase")
        assert message == "Transaction added."
        assert len(added) == before + 1
    finally:
        app.DEMO.records["transactions"] = original


def test_live_chat_followups_keep_context_and_explain_the_right_topic():
    store = app.AccountStore(app.generate_demo_records())
    first = app.assistant_turn("How much money do I have?", account=store)
    assert "in total" in first["reply"]

    why = app.assistant_turn("Why?", last_question="How much money do I have?", account=store)
    assert "Together, checking" in why["reply"]
    assert f"${store.balance('Checking') + store.balance('Savings'):,.2f}" in why["reply"]

    followup = app.assistant_turn(
        "And savings?", last_question="How much money do I have?", account=store
    )
    assert f"${store.balance('Savings'):,.2f}" in followup["reply"]
    assert "due soonest" not in why["reply"]

    unrelated_why = app.assistant_turn("Why?", last_question="When is rent due?", account=store)
    assert "listed come from" in unrelated_why["reply"]
    assert "due soonest" not in unrelated_why["reply"]


def test_live_chat_answers_varied_finance_questions_and_rejects_unrelated():
    store = app.AccountStore(app.generate_demo_records())

    checking, pending = app.answer_financial_question("How much is in my checking account?", store)
    assert f"${store.balance('Checking'):,.2f}" in checking
    assert pending is None

    savings, pending = app.answer_financial_question("What is my savings balance?", store)
    assert f"${store.balance('Savings'):,.2f}" in savings
    assert pending is None

    debt, pending = app.answer_financial_question("How much debt do I have?", store)
    assert f"${sum(store.debts().values()):,.0f}" in debt
    assert pending is None

    bills, pending = app.answer_financial_question("What bills are due this week?", store)
    assert "due in the next 7 days" in bills or "Nothing is due in the next 7 days" in bills
    assert pending is None

    unrelated, pending = app.answer_financial_question(
        "Can you tell me a joke about penguins?", store
    )
    assert "only help with personal-finance questions" in unrelated
    assert pending is None


def test_server_port_configuration_falls_back_or_honors_an_explicit_port(monkeypatch):
    monkeypatch.delenv("GRADIO_SERVER_PORT", raising=False)
    assert app.configured_server_port() is None

    monkeypatch.setenv("GRADIO_SERVER_PORT", "   ")
    assert app.configured_server_port() is None

    monkeypatch.setenv("GRADIO_SERVER_PORT", "7861")
    assert app.configured_server_port() == 7861

    monkeypatch.setenv("GRADIO_SERVER_PORT", "not-a-port")
    with pytest.raises(ValueError, match="1 to 65535"):
        app.configured_server_port()

    monkeypatch.setenv("GRADIO_SERVER_PORT", "65536")
    with pytest.raises(ValueError, match="1 to 65535"):
        app.configured_server_port()


def test_gradio_interface_has_the_financial_workspace_and_voice_transport():

    interface = app.launch_app()
    blocks = list(interface.blocks.values())
    workspace = next(b for b in blocks if getattr(b, "elem_id", None) == "sv-workspace")
    assert {fn.__name__ for fn in workspace.server_fns} == {
        "live_turn",
        "transcribe_clip",
        "workspace_action",
    }
    assert "VoiceController" in workspace.js_on_load
    assert 'data-view="transactions"' in workspace.value
    assert "voice-transcript" in workspace.value
    reply = app.live_turn({"text": "How much money do I have?", "pending": None, "last": ""})
    assert reply["code"] == "login_required"
    import solvra_workspace as workspace

    login = workspace.workspace_action({"op": "login", "profile_id": "maya"})
    try:
        reply = app.live_turn({"session": login["session"], "text": "How much money do I have?"})
        assert "checking" in reply["reply"] and reply["pending"] is None
    finally:
        workspace.workspace_action({"op": "logout", "session": login["session"]})
    options = app.launch_options()
    assert {"theme", "css", "js"} <= set(options)
    # Dark mode must not change any colour (it made labels invisible before).
    theme = options["theme"]
    assert theme.body_text_color_dark == theme.body_text_color
    assert theme.body_background_fill_dark == theme.body_background_fill


def test_live_turn_handles_voice_confirmation_and_small_talk():
    store = app.AccountStore(app.generate_demo_records())
    start = store.balance("Checking")

    turn = app.assistant_turn("Hey Solvra, I got paid $500 today", None, "", store)
    assert turn["pending"]["action"] == "income" and turn["pending"]["amount"] == 500
    assert store.balance("Checking") == start

    declined = app.assistant_turn("no thanks", turn["pending"], "", store)
    assert declined["pending"] is None and not declined["changed"]
    assert store.balance("Checking") == start

    turn = app.assistant_turn("I got paid $500 today", None, "", store)
    # A new question while an update is pending must never confirm it by accident.
    other = app.assistant_turn("okay what should I pay first", turn["pending"], "", store)
    assert not other["changed"] and store.balance("Checking") == start

    confirmed = app.assistant_turn("Yes please", turn["pending"], "", store)
    assert confirmed["changed"] and confirmed["pending"] is None
    assert store.balance("Checking") == pytest.approx(start + 500)

    assert "Solvra" in app.assistant_turn("hello", None, "", store)["reply"]
    assert app.assistant_turn("goodbye", None, "", store)["end"] is True
    assert "pay first" in app.assistant_turn("what can you do", None, "", store)["reply"]


def test_common_spoken_questions_get_direct_answers():
    store = app.AccountStore(app.generate_demo_records())
    ask = lambda q: app.assistant_turn(q, None, "", store)["reply"]

    assert "Dec 1" in ask("When is rent due?")
    assert "T-Mobile" in ask("how much is my phone bill")
    assert ask("What should I pay first?").startswith("Here's what I'd pay first")
    assert "due in the next 7 days" in ask("What bills are due this week?")
    assert "out of 100" in ask("Am I okay financially?")
    assert "late fees" in ask("What if I pay electricity 5 days late?")
    assert "not sure" in ask("tell me a joke")


def test_speech_text_reads_naturally():
    spoken = app.speech_text("**Rent** is $1,425.00, due 2026-12-01; gas is $58.00 & tax $19.99.")
    assert spoken == (
        "Rent is one thousand, four hundred and twenty-five dollars, due December first, "
        "twenty twenty-six; gas is fifty-eight dollars and tax nineteen dollars and ninety-nine cents."
    )


def test_account_panel_and_transcription_guard():
    panel = app.account_panel_html(app.DEMO)
    assert "Checking" in panel and "Electricity" in panel and "<script" not in panel
    blocked = app.transcribe_clip({"path": "/etc/passwd"})
    assert blocked["text"] == "" and blocked["error"]


def test_payment_plan_and_what_ifs_stay_within_cash():
    store = app.AccountStore(app.generate_demo_records())
    plan = app.optimize(app.scenario_from_account(store))
    assert plan.total_allocated <= store.balance("Checking") + 0.01
    assert plan.harm["total_harm"] >= 0 and plan.unpaid >= 0

    tight = app.scenario_from_account(store)
    tight.available_cash = 150
    tight_plan = app.optimize(tight)
    assert tight_plan.total_allocated <= 150.01
    assert tight_plan.unpaid > plan.unpaid

    rent = next(b for b in store.bills if b.name == "Rent")
    delayed = app.simulate_delay(app.scenario_from_account(store), rent.bill_id, 3)
    assert delayed.total_allocated <= store.balance("Checking") + 0.01
    assert rent.effective_due == dt.date(2026, 12, 1)  # the real bill is untouched

    electricity = next(b for b in store.bills if b.name == "Electricity")
    on_time = app.simulate_late_payment(electricity, 0)
    late = app.simulate_late_payment(electricity, 30)
    assert late.harm["total_harm"] > on_time.harm["total_harm"]


def test_health_score_is_bounded_and_weighted():
    score, factors = app.health_assessment(app.DEMO)
    assert 0 <= score <= 100
    assert len(factors) == 7
    assert factors.weight.sum() == pytest.approx(1.0)


def test_reset_restores_the_demo_account():
    store = app.AccountStore(app.generate_demo_records())
    start = store.balance("Checking")
    pending = app.answer_financial_question("I got paid $250", store)[1]
    app.confirm_account_update(pending, True, store)
    assert store.balance("Checking") == pytest.approx(start + 250)
    store.reset()
    assert store.balance("Checking") == pytest.approx(start)
