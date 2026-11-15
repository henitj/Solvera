import copy
import csv
import datetime as dt
import io
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import solvra_app as f
import solvra_workspace as w
from solvra_assistant import amount_in, answer_question, period_for
from solvra_insights import (
    dashboard,
    payment_plan,
    planning_buffer,
    reporting_period,
    spending_rows,
)
from solvra_voice import capabilities, decode_pcm, transcribe


@pytest.fixture
def account():
    return f.AccountStore(f.generate_demo_records())


@pytest.fixture
def session():
    response = w.workspace_action({"op": "login", "profile_id": "maya"})
    assert "error" not in response
    yield response
    with w._LOCK:
        w._SESSIONS.pop(response["session"], None)


def chat(session, text, **extra):
    return w.chat_turn({"session": session["session"], "text": text, **extra})


def test_partial_month_compares_like_for_like(account):
    period = reporting_period("month")
    assert period.days == 14
    assert period.previous.start == dt.date(2026, 10, 1)
    assert period.previous.end == dt.date(2026, 10, 14)
    data = dashboard(account)
    assert data["totals"]["spending"] == pytest.approx(-spending_rows(account, period).amount.sum())
    assert data["previous"]["spending"] == pytest.approx(
        -spending_rows(account, period.previous).amount.sum()
    )
    assert sum(c["amount"] for c in data["categories"]) == pytest.approx(data["totals"]["spending"])
    assert data["chart"][-1]["partial"] is True
    assert data["chart"][-2]["partial"] is False


def test_suggestions_have_account_evidence_and_honest_comparisons(account):
    data = dashboard(account)
    for insight in data["insights"]:
        assert insight["evidence"] and insight["prompt"]
        response = answer_question(insight["prompt"], account)
        assert response["intent"] != "help"
        assert response["sources"]
    pattern = next(i for i in data["insights"] if i["id"] == "spending")
    assert "2026-10-01" in " ".join(pattern["evidence"])
    assert "2026-10-14" in " ".join(pattern["evidence"])
    assert "covered" in data["insights"][0]["title"]
    account.add_transaction(
        -19000,
        "Other expenses",
        "Cash adjustment",
        "Testing a real shortfall",
        "Adjustment",
    )
    assert "gap" in dashboard(account)["insights"][0]["title"]


def test_spending_is_category_and_merchant_specific(account):
    groceries = answer_question("How much did I spend on groceries last month?", account)
    assert "$752.85" in groceries["reply"]
    assert "$3,562.54" not in groceries["reply"]
    assert "12 recorded transactions" in groceries["reply"]
    merchant = answer_question("How much did I spend at Aldi last month?", account)
    expected = (
        -spending_rows(account, reporting_period("last_month"))
        .query('merchant == "Aldi"')
        .amount.sum()
    )
    assert f.money(expected) in merchant["reply"]
    electricity = answer_question("How much did I spend on electricity last month?", account)
    assert "$119.97" in electricity["reply"]


def test_multi_turn_spending_retains_category_and_dates(session):
    first = chat(session, "How much did I spend on groceries last month?")
    second = chat(session, "Compare that with the previous period.")
    third = chat(session, "Why?")
    for response in (first, second, third):
        assert "groceries" in response["reply"]
        assert "$752.85" in response["reply"]
        assert "October" in response["reply"] or "Oct" in response["reply"]
    assert "September" in second["reply"] or "Sep" in second["reply"]
    assert len(second["sources"]) == 2
    followup = chat(session, "What about dining?")
    assert "$187.69" in followup["reply"] and "groceries" not in followup["reply"]


def test_followup_period_and_explicit_period_comparison(account):
    response = answer_question("Compare groceries spending in October versus September", account)
    assert "$752.85" in response["reply"]
    assert response["sources"][1]["detail"].startswith("2026-09-01 to 2026-09-30")
    assert period_for("spending since 2026-10-01").start == dt.date(2026, 10, 1)
    assert period_for("spending since 2026-10-01").end == f.AS_OF
    future = answer_question("How much did I spend from 2027-01-01 to 2027-01-10?", account)
    assert "ledger ends" in future["reply"]
    invalid = answer_question("How much did I spend from 2026-02-31 to 2026-03-10?", account)
    assert "not valid" in invalid["reply"]


def test_multiple_read_only_questions_are_answered(account):
    response = answer_question("How much is in checking and what bills are due this week?", account)
    assert f.money(account.balance("Checking")) in response["reply"]
    assert "Electricity" in response["reply"]
    assert response["intent"] == "combined"
    assert response["pending"] is None


def test_recent_transaction_query_returns_entries_not_a_total(account):
    response = answer_question("Show my last 3 transactions", account)
    assert response["intent"] == "transactions"
    assert response["reply"].count("•") == 3
    assert "Target Grocery" in response["reply"]
    assert "-$75.49" in response["reply"]


def test_buffer_explains_every_deduction_and_excludes_expected_pay(account):
    buffer = planning_buffer(account)
    assert buffer["headroom"] == pytest.approx(
        buffer["checking"] - buffer["bills"] - buffer["reserve"] - buffer["everyday_allowance"]
    )
    response = answer_question("Can I afford a $200 purchase?", account)
    assert f.money(buffer["headroom"] - 200) in response["reply"]
    for field in ("checking", "bills", "reserve", "everyday_allowance"):
        assert f.money(buffer[field]) in response["reply"]
    before = copy.deepcopy(buffer)
    account.preferences["paycheck"] = 999999
    assert planning_buffer(account) == before
    too_much = answer_question("Can I afford a $900000 purchase?", account)
    assert "exceed" in too_much["reply"]


def test_every_affordable_bill_is_included_even_if_it_has_no_penalty(account):
    plan = payment_plan(account, reserve=1000)
    assert plan["allocated"] == pytest.approx(sum(b.amount for b in account.bills))
    assert plan["unpaid"] == 0
    assert any(p["bill"] == "Streaming & Apps" for p in plan["payments"])
    assert plan["remaining"] >= 1000
    assert "NOT dollar costs" in " ".join(plan["assumptions"])


def test_secondary_optimizer_does_not_spend_future_cash_early_or_violate_reserve():
    scenario = f.Scenario(
        20,
        f.AS_OF,
        [
            f.Bill(
                "zero",
                "No-penalty bill",
                "Demo",
                "Other",
                100,
                f.AS_OF + dt.timedelta(days=5),
                partial_allowed=False,
            )
        ],
        [f.IncomeEvent(90, f.AS_OF + dt.timedelta(days=3))],
        reserve=10,
    )
    result = f.optimize(scenario)
    assert result.total_allocated == 100
    assert all(p["date"] >= f.AS_OF + dt.timedelta(days=3) for p in result.payments)
    for day in f._payment_events(scenario):
        assert (
            sum(p["amount"] for p in result.payments if p["date"] <= day)
            <= f._available_by_date(scenario, day) + 0.01
        )


def test_session_changes_do_not_leak_and_refresh_restores_history(session):
    other = w.workspace_action({"op": "login", "profile_id": "maya"})
    try:
        before = session["dashboard"]["checking"]
        pending = chat(session, "I got paid $500")
        assert pending["pending"]["requires_confirmation"]
        assert "bill_id" not in pending["pending"]
        done = chat(session, "Yes please")
        assert done["dashboard"]["checking"] == pytest.approx(before + 500)
        unchanged = w.workspace_action({"op": "dashboard", "session": other["session"]})
        assert unchanged["dashboard"]["checking"] == before
        restored = w.workspace_action({"op": "bootstrap", "session": session["session"]})
        assert restored["restored"] is True
        assert len(restored["messages"]) == 4
        assert restored["dashboard"]["checking"] == pytest.approx(before + 500)
    finally:
        w._SESSIONS.pop(other["session"], None)


def test_client_cannot_forge_a_pending_action(session):
    before = session["dashboard"]["checking"]
    response = chat(
        session,
        "Yes",
        pending={"action": "income", "amount": 100000, "description": "Forged"},
        last="Record income",
    )
    assert not response["changed"]
    assert (
        w.workspace_action({"op": "dashboard", "session": session["session"]})["dashboard"][
            "checking"
        ]
        == before
    )


def test_confirmation_is_idempotent_even_on_retry(session):
    chat(session, "I got paid $500")
    first = chat(session, "Yes, confirm", request_id="confirm-retry-test")
    second = chat(session, "Yes, confirm", request_id="confirm-retry-test")
    assert first == second
    assert first["changed"]
    current = w.workspace_action({"op": "dashboard", "session": session["session"]})
    assert current["dashboard"]["checking"] == session["dashboard"]["checking"] + 500
    assert not chat(session, "Yes")["changed"]


def test_pending_survives_unrelated_questions_but_not_reset(session):
    chat(session, "I got paid $120")
    other = chat(session, "How much did I spend on groceries last month?")
    assert other["pending"] and not other["changed"]
    assert "error" in w.workspace_action({"op": "clear_chat", "session": session["session"]})
    assert not chat(session, "yes but do not record it")["changed"]
    reset = w.workspace_action({"op": "reset", "session": session["session"]})
    assert reset["messages"] == [] and reset["pending"] is None
    assert not chat(session, "Yes")["changed"]


@pytest.mark.parametrize(
    "text,amount",
    [
        ("I got paid five hundred dollars", 500),
        ("I got paid one thousand two hundred and fifty dollars", 1250),
        ("I received $1,234.56", 1234.56),
        ("I paid electricity on November 12", None),
        ("I paid electricity on 2026-11-12", None),
    ],
)
def test_spoken_amounts_do_not_confuse_dates_with_money(text, amount):
    assert amount_in(text.lower()) == amount


@pytest.mark.parametrize("amount", [math.nan, math.inf, -math.inf, -1, 0, 1000001])
def test_invalid_confirmed_income_is_rejected_without_mutation(account, amount):
    before = account.balance("Checking")
    reply = f.confirm_account_update(
        {"action": "income", "amount": amount, "description": "Invalid"}, True, account
    )
    assert not reply.startswith("Done")
    assert account.balance("Checking") == before


@pytest.mark.parametrize(
    "text",
    [
        "I paid -50 for electricity",
        "I got paid minus five hundred dollars",
        "I got paid $2000000",
    ],
)
def test_bad_spoken_amounts_are_not_staged(account, text):
    assert answer_question(text, account)["pending"] is None


def test_partial_bill_payment_reduces_remaining_minimum(account):
    bill = next(b for b in account.bills if b.name == "Credit Card Minimum")
    before_minimum, before_balance = bill.minimum_payment, account.balance("Checking")
    response = f.confirm_account_update(
        {"action": "payment", "bill_id": bill.bill_id, "amount": 20}, True, account
    )
    assert response.startswith("Done")
    assert bill.minimum_payment == before_minimum - 20
    assert account.balance("Checking") == pytest.approx(before_balance - 20)


def test_stage_transaction_uses_server_confirmation_and_syncs_dashboard(session):
    token = session["session"]
    staged = w.workspace_action(
        {
            "op": "stage_transaction",
            "session": token,
            "kind": "expense",
            "merchant": "Test cafe",
            "category": "Dining & Entertainment",
            "amount": 12.34,
        }
    )
    assert staged["pending"] and not staged["changed"]
    assert (
        w.workspace_action({"op": "dashboard", "session": token})["dashboard"]["transaction_count"]
        == 897
    )
    confirmed = chat(session, "Confirm")
    assert confirmed["changed"]
    assert confirmed["dashboard"]["transaction_count"] == 898
    assert confirmed["dashboard"]["checking"] == pytest.approx(
        session["dashboard"]["checking"] - 12.34
    )
    assert confirmed["dashboard"]["totals"]["spending"] == pytest.approx(
        session["dashboard"]["totals"]["spending"] + 12.34
    )


def test_transaction_filtering_pagination_and_csv_formula_protection(session):
    token = session["session"]
    response = w.workspace_action(
        {
            "op": "transactions",
            "session": token,
            "search": "jewel",
            "period": "last_month",
            "category": "Groceries",
            "size": 2,
        }
    )
    assert response["total"] > 2 and len(response["items"]) == 2
    assert all(
        r["merchant"] == "Jewel-Osco" and r["date"].startswith("2026-10") for r in response["items"]
    )
    empty = w.workspace_action(
        {
            "op": "transactions",
            "session": token,
            "search": "merchant-that-does-not-exist",
            "page": 9999,
        }
    )
    assert empty["total"] == 0 and empty["page"] == 1
    w.workspace_action(
        {
            "op": "stage_transaction",
            "session": token,
            "kind": "expense",
            "merchant": "=HYPERLINK(1)",
            "category": "Other expenses",
            "amount": 1,
        }
    )
    chat(session, "Yes")
    exported = w.workspace_action({"op": "export", "session": token, "search": "HYPERLINK"})
    rows = list(csv.DictReader(io.StringIO(exported["csv"])))
    assert len(rows) == 1
    assert rows[0]["merchant"].startswith("'=")
    assert float(rows[0]["amount"]) == -1


def test_what_ifs_never_mutate_and_risk_is_not_presented_as_a_fee(account):
    before_tx = account.transactions.copy(deep=True)
    before_bills = copy.deepcopy(account.bills)
    response = answer_question("What if I pay electricity 20 days late?", account)
    assert "Modeled late fees: $18.00" in response["reply"]
    assert response["pending"] is None
    assert "360.00" not in response["reply"]  # non-monetary consequence weight
    assert "what-if" in answer_question("What if I receive $500 tomorrow?", account)["reply"]
    pd.testing.assert_frame_equal(account.transactions, before_tx)
    assert account.bills == before_bills


def test_expired_tokens_do_not_silently_create_mutable_accounts(session):
    with w._LOCK:
        w._SESSIONS[session["session"]].touched -= w.SESSION_TTL + 1
    response = chat(session, "Yes")
    assert "expired" in response["error"]
    restored = w.workspace_action({"op": "bootstrap", "session": session["session"]})
    assert restored["session"] != session["session"]
    w._SESSIONS.pop(restored["session"], None)


def test_real_offline_audio_is_transcribed_without_network_or_api_keys(monkeypatch):
    monkeypatch.delenv("SOLVRA_WHISPER_MODEL", raising=False)
    assert capabilities()["offline"] is True
    assert capabilities()["review_required"] is True
    fixture = Path(__file__).parent / "fixtures" / "goforward.flac"
    assert transcribe(str(fixture)) == "go forward ten meters"


def test_silence_and_long_audio_are_rejected(tmp_path):
    import av

    def write_audio(path, seconds, silent):
        data = np.zeros((1, int(16000 * seconds)), dtype=np.int16)
        if not silent:
            data[0] = (np.sin(np.arange(data.shape[1]) / 20) * 5000).astype(np.int16)
        with av.open(str(path), "w") as out:
            stream = out.add_stream("pcm_s16le", rate=16000)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(data, format="s16", layout="mono")
            frame.sample_rate = 16000
            for packet in stream.encode(frame):
                out.mux(packet)
            for packet in stream.encode():
                out.mux(packet)

    silent = tmp_path / "silence.wav"
    write_audio(silent, 2, True)
    with pytest.raises(ValueError, match="silent"):
        decode_pcm(str(silent))
    long = tmp_path / "long.wav"
    write_audio(long, 46, False)
    with pytest.raises(ValueError, match="45 seconds"):
        decode_pcm(str(long))


def test_upload_guard_rejects_traversal_symlinks_and_non_audio(tmp_path, monkeypatch):
    from gradio import utils

    monkeypatch.setattr(utils, "get_upload_folder", lambda: str(tmp_path))
    outside = tmp_path.parent / "solvra-private-test.txt"
    outside.write_text("not audio")
    try:
        (tmp_path / "symlink.wav").symlink_to(outside)
        (tmp_path / "test.txt").write_text("not audio")
        for path in (
            outside,
            tmp_path / "symlink.wav",
            tmp_path / "test.txt",
            tmp_path / "../solvra-private-test.txt",
        ):
            assert f.transcribe_clip({"path": str(path)})["error"]
        assert not f.transcribe_clip({"path": str(tmp_path / "../solvra-private-test.txt")})["text"]
    finally:
        outside.unlink()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I received a hundred dollars", 100),
        ("I received fifty dollars and twenty five cents", 50.25),
        ("I received 100 dollars and 25 cents", 100.25),
    ],
)
def test_additional_common_spoken_currency_forms(text, expected):
    assert amount_in(text.lower()) == expected


def test_spelled_days_and_purchase_what_if_are_not_silently_misinterpreted(account):
    response = answer_question("What if I pay electricity ten days late?", account)
    assert "10 days" in response["reply"] and "$18.00" in response["reply"]
    purchase = answer_question("What if I spent $200?", account)
    assert purchase["intent"] == "affordability"
    assert "no expense was recorded" in purchase["reply"]
    assert purchase["pending"] is None
    paid_on_date = answer_question("I paid electricity on 2026-11-12", account)
    assert paid_on_date["pending"]["amount"] == 148.6


def test_income_outside_planner_horizon_is_not_added_to_remaining_cash(account):
    account.preferences["payday"] = f.AS_OF + dt.timedelta(days=70)
    with_income = payment_plan(account, include_income=True)
    no_income = payment_plan(account, include_income=False)
    assert with_income["remaining"] == no_income["remaining"]
    assert any("outside the 40-day horizon" in a for a in with_income["assumptions"])


def test_health_income_factors_use_completed_months_not_the_partial_current_one(
    account,
):
    _, before = f.health_assessment(account)
    account.add_transaction(20000, "Income", "Test employer", "Current-month income", "Income")
    _, after = f.health_assessment(account)
    pd.testing.assert_frame_equal(before, after)


def test_read_aloud_never_rounds_away_recorded_cents():
    assert (
        f.speech_text("Checking is $19,259.44 and electricity is $148.60.")
        == "Checking is nineteen thousand, two hundred and fifty-nine dollars and forty-four cents "
        "and electricity is one hundred and forty-eight dollars and sixty cents."
    )


@pytest.mark.parametrize("fail_model", [False, True])
def test_optional_whisper_is_local_only_and_bad_models_fall_back(monkeypatch, tmp_path, fail_model):
    import importlib.machinery
    import sys
    import types

    import solvra_voice as voice

    (tmp_path / "model.bin").write_bytes(b"test fixture, not actual model weights")
    (tmp_path / "config.json").write_text("{}")
    calls = []
    transcriptions = []

    class FakeModel:
        def __init__(self, path, **options):
            calls.append(options)
            if fail_model:
                raise OSError("Invalid local model")

        def transcribe(self, audio, **options):
            transcriptions.append(options)
            return iter([types.SimpleNamespace(text="What is my balance?")]), None

    module = types.ModuleType("faster_whisper")
    module.__spec__ = importlib.machinery.ModuleSpec("faster_whisper", loader=None)
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(voice, "_WHISPER", None)
    monkeypatch.setattr(voice, "_WHISPER_FAILED", "")
    monkeypatch.setenv("SOLVRA_WHISPER_MODEL", str(tmp_path))
    assert voice.capabilities()["engine"] == "Local Whisper"
    text = voice.transcribe(str(Path(__file__).parent / "fixtures" / "goforward.flac"))
    assert calls[0]["local_files_only"] is True
    assert text == ("go forward ten meters" if fail_model else "What is my balance?")
    if not fail_model:
        assert transcriptions[0]["condition_on_previous_text"] is False
        assert transcriptions[0]["initial_prompt"] == voice._WHISPER_INITIAL_PROMPT
    assert voice.capabilities()["engine"] == ("Offline English" if fail_model else "Local Whisper")
    assert voice.capabilities()["review_required"] is True


@pytest.mark.parametrize(
    "start,end",
    [(dt.date(2026, 9, 1), dt.date(2026, 11, 29)), (dt.date(2026, 1, 1), f.AS_OF)],
)
def test_multi_month_comparisons_keep_the_full_window(start, end):
    from solvra_insights import Period

    period = Period(start, end, "Multi-month window")
    assert period.previous.days == period.days
    assert period.previous.end == start - dt.timedelta(days=1)


def test_fractional_speech_passage_and_simulation_days_are_rejected(session, monkeypatch):
    monkeypatch.setattr(w, "synthesize", lambda *args: {"audio": "test"})
    for args in ({"op": "speech", "preview": True, "index": 0.5}, {"op": "simulate", "days": 1.5}):
        result = w.workspace_action({"session": session["session"], **args})
        assert "whole number" in result["error"]


def test_expanded_conversational_questions_are_answered(account):
    paid = answer_question("When do I get paid?", account)
    assert paid["intent"] == "income" and "paycheck" in paid["reply"].lower()

    flow = answer_question("Where does my money go?", account)
    assert flow["intent"] == "spending" and "cash flow" in flow["reply"].lower()

    phone = answer_question("Can I buy a new phone?", account)
    assert phone["intent"] == "affordability" and "spending room" in phone["reply"].lower()

    dinner = answer_question("Can I spend $50 on dinner?", account)
    assert dinner["intent"] == "affordability" and "$50.00" in dinner["reply"]

    save = answer_question("Can I save $500?", account)
    assert save["intent"] == "affordability" and "savings is safe" in save["reply"].lower()

    advice = answer_question("What should I do?", account)
    assert advice["intent"] == "advice" and "prioritized financial plan" in advice["reply"].lower()

    subs = answer_question("What are my subscriptions?", account)
    assert subs["intent"] == "subscriptions" and "subscriptions" in subs["reply"].lower()

    big = answer_question("What is my biggest expense?", account)
    assert big["intent"] == "spending" and "largest" in big["reply"].lower()

    greeting = answer_question("Hello", account)
    assert greeting["intent"] == "greeting" and "Solvra" in greeting["reply"]

    unrelated = answer_question("tell me a joke about penguins", account)
    assert unrelated["intent"] == "help" and "only help with personal-finance questions" in unrelated["reply"]


def test_trim_silence_strips_leading_trailing_energy():
    import numpy as np

    import solvra_voice as voice

    silence = np.zeros(16000, dtype=np.int16)
    speech = (np.sin(np.linspace(0, 100, 16000)) * 10000).astype(np.int16)
    full = np.concatenate([silence, speech, silence])
    trimmed = voice.trim_silence(full)
    assert len(trimmed) < len(full)
    assert len(trimmed) > 0
    trimmed_bytes = voice.trim_silence(full.tobytes())
    assert isinstance(trimmed_bytes, bytes)
    assert len(trimmed_bytes) < len(full.tobytes())

