"""Session-isolated UI boundary. The browser cannot supply an executable pending action."""

from __future__ import annotations

import copy
import csv
import io
import math
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import solvra_ai as ai
import solvra_app as f
import solvra_profiles as profiles
from solvra_assistant import conversation_turn, result
from solvra_insights import (
    dashboard,
    delay_preview,
    payment_plan,
    period_transactions,
    reporting_period,
    transaction_dict,
)
from solvra_speech import PREVIEW, speech_chunks, synthesize
from solvra_speech import capabilities as speech_capabilities
from solvra_voice import capabilities

SESSION_TTL = 8 * 60 * 60
MAX_SESSIONS = 64
MAX_HISTORY = 80
MAX_GUARDRAIL_HISTORY = 50
# The browser verifies this before enabling the monitor. It prevents a newer
# guardrails UI from silently accepting decisions supplied by an older runtime.
GUARDRAIL_POLICY_VERSION = "finance-topic-v2"
_LOCK = threading.RLock()
_SESSIONS: dict[str, Session] = {}


class LoginRequired(ValueError):
    """A demo profile must be selected; this is not production authentication."""


@dataclass
class Session:
    account: profiles.DemoAccount
    workspace: str
    active: bool = True
    history: list = field(default_factory=list)
    guardrail_history: list[dict[str, str]] = field(default_factory=list)
    pending: dict | None = None
    last_question: str = ""
    ai_turn: dict | None = None
    period: str = "month"
    touched: float = field(default_factory=time.monotonic)
    requests: OrderedDict = field(default_factory=OrderedDict)
    lock: Any = field(default_factory=threading.RLock)


@dataclass
class DemoWorkspace:
    people: dict[str, Session] = field(default_factory=dict)
    token: str | None = None
    touched: float = field(default_factory=time.monotonic)


_WORKSPACES: dict[str, DemoWorkspace] = {}


def require_login(session: Session):
    if not session.active:
        raise LoginRequired("This demo login ended. Choose a person and log in again.")


def guardrail_view(session: Session) -> dict[str, Any]:
    """Return display-only guardrail activity for the selected demo session."""
    history = copy.deepcopy(session.guardrail_history)
    blocked = sum(item.get("decision") == "block" for item in history)
    return {
        "policy_version": GUARDRAIL_POLICY_VERSION,
        "history": history,
        "requests": len(history),
        "blocked": blocked,
        "allowed": len(history) - blocked,
    }


def guardrail_check(session: Session, prompt: Any) -> dict[str, Any]:
    text = " ".join(str(prompt or "").split())
    if not 1 <= len(text) <= 3000:
        raise ValueError("Enter a prompt between 1 and 3,000 characters to test the guardrails.")
    verdict = ai.guardrail_decision(text, session.account.profile)
    item = {
        "id": secrets.token_urlsafe(8),
        "time": time.strftime("%H:%M:%S", time.localtime()),
        "account": session.account.profile["name"],
        "prompt": text,
        **verdict,
    }
    session.guardrail_history.insert(0, item)
    del session.guardrail_history[MAX_GUARDRAIL_HISTORY:]
    return {"result": copy.deepcopy(item), "guardrails": guardrail_view(session)}


def revoke(workspace: DemoWorkspace):
    # Registry -> session lock is the sole lock order. Normal account actions never
    # acquire the registry while holding their session lock.
    old = _SESSIONS.pop(workspace.token, None)
    if old:
        with old.lock:
            old.active = False
            old.pending = old.ai_turn = None
            old.requests.clear()
    workspace.token = None


def prune_workspaces():
    now = time.monotonic()
    for key, workspace in list(_WORKSPACES.items()):
        if now - workspace.touched > SESSION_TTL:
            revoke(workspace)
            del _WORKSPACES[key]


def workspace_for(key: Any) -> tuple[str, DemoWorkspace]:
    # Caller holds _LOCK. The workspace key preserves this tab's *fictional* profiles;
    # it cannot retrieve finances without a separate active login token.
    prune_workspaces()
    if not isinstance(key, str) or key not in _WORKSPACES:
        if len(_WORKSPACES) >= MAX_SESSIONS:
            oldest = min(_WORKSPACES, key=lambda k: _WORKSPACES[k].touched)
            revoke(_WORKSPACES.pop(oldest))
        key = secrets.token_urlsafe(32)
        _WORKSPACES[key] = DemoWorkspace()
    workspace = _WORKSPACES[key]
    workspace.touched = time.monotonic()
    return key, workspace


def session_for(token: str | None) -> tuple[str, Session, bool]:
    with _LOCK:
        prune_workspaces()
        if isinstance(token, str) and token in _SESSIONS:
            session = _SESSIONS[token]
            require_login(session)
            if time.monotonic() - session.touched > SESSION_TTL:
                revoke(_WORKSPACES[session.workspace])
            else:
                session.touched = _WORKSPACES[session.workspace].touched = time.monotonic()
                return token, session, True
        raise LoginRequired("Your demo session expired or ended. Choose a person and log in again.")


def login_action(data: dict) -> dict:
    op = data["op"]
    if op == "login":
        selected = profiles.person(data.get("profile_id"))
    with _LOCK:
        # An active token can restore its own workspace on refresh without the
        # optional saved workspace key; an explicit mismatched key cannot do so.
        token = data.get("session")
        existing = _SESSIONS.get(token) if isinstance(token, str) else None
        if existing and time.monotonic() - existing.touched > SESSION_TTL:
            revoke(_WORKSPACES[existing.workspace])
            existing = None
        key, workspace = workspace_for(
            data.get("workspace") or (existing.workspace if existing else None)
        )
        if existing and existing.workspace != key:
            existing = None
        if op == "logout":
            if existing:
                revoke(workspace)
            return {
                "authenticated": False,
                "session": None,
                "workspace": key,
                "profiles": profiles.catalog(),
            }
        if op == "login":
            revoke(workspace)
            saved = workspace.people.get(selected.id)
            session = Session(
                account=saved.account if saved else profiles.DemoAccount(selected.id),
                workspace=key,
                history=copy.deepcopy(saved.history) if saved else [],
                guardrail_history=copy.deepcopy(saved.guardrail_history) if saved else [],
                last_question=saved.last_question if saved else "",
                period=saved.period if saved else "month",
            )
            token = secrets.token_urlsafe(32)
            workspace.people[selected.id] = _SESSIONS[token] = session
            workspace.token = token
        elif not existing or not existing.active or workspace.token != token:
            return {
                "authenticated": False,
                "session": None,
                "workspace": key,
                "profiles": profiles.catalog(),
                "expired": bool(token),
            }
        else:
            session = existing
            session.touched = time.monotonic()
        with session.lock:
            require_login(session)
            return {
                "authenticated": True,
                "session": token,
                "workspace": key,
                "profile": session.account.profile,
                "profiles": profiles.catalog(),
                "restored": op == "bootstrap",
                "ai": {"model": ai.MODEL, "provider": "Puter / xAI", "requires_sign_in": True},
                "dashboard": dashboard(session.account, session.period),
                "messages": copy.deepcopy(session.history),
                "pending": pending_view(session.pending),
                "guardrails": guardrail_view(session),
                "voice": {**capabilities(), "speech": speech_capabilities()},
            }


def pending_view(pending: dict | None) -> dict | None:
    if not pending:
        return None
    # A display-only summary. Clients cannot forge or replace the server-side action.
    return {
        "action": pending.get("action"),
        "amount": pending.get("amount"),
        "requires_confirmation": True,
    }


def remembered(session: Session, request_id: str) -> dict | None:
    if request_id and request_id in session.requests:
        return copy.deepcopy(session.requests[request_id])
    return None


def remember(session: Session, request_id: str, response: dict) -> dict:
    if request_id:
        session.requests[request_id] = copy.deepcopy(response)
        while len(session.requests) > 32:
            session.requests.popitem(last=False)
    return response


def assistant_record(response: dict) -> dict:
    response.setdefault("message_id", secrets.token_urlsafe(12))
    response.setdefault("engine", "local")
    response["speech_chunks"] = speech_chunks(response["reply"])
    response["speech"] = " ".join(response["speech_chunks"])
    return {
        "role": "assistant",
        "id": response["message_id"],
        "content": response["reply"],
        **{
            key: response.get(key)
            for key in (
                "speech",
                "speech_chunks",
                "sources",
                "suggestions",
                "intent",
                "engine",
                "model",
                "notice",
            )
        },
    }


def record_response(session: Session, text: str, response: dict) -> dict:
    session.pending = response.get("pending")
    session.last_question = response.get("context_question", session.last_question)
    response["pending"] = pending_view(session.pending)
    session.history.extend([{"role": "user", "content": text}, assistant_record(response)])
    session.history = session.history[-MAX_HISTORY:]
    if response.get("changed"):
        response["dashboard"] = dashboard(session.account, session.period)
    return response


def ai_job(session: Session, ticket: Any) -> dict:
    job = session.ai_turn
    if not job or not isinstance(ticket, str) or not secrets.compare_digest(job["ticket"], ticket):
        raise ValueError("That AI request is no longer active. Ask your question again.")
    if not session.history or session.history[-1].get("id") != job["fallback"]["message_id"]:
        raise ValueError("The conversation changed while Grok was working. Ask again.")
    return job


def finish_ai(session: Session, job: dict, answer: dict) -> dict:
    # Replace only this provisional, read-only answer. Never trust model-supplied actions.
    response = {**job["fallback"], **answer}
    response.pop("ai_job", None)
    response["pending"] = pending_view(session.pending)
    session.history[-1] = assistant_record(response)
    if response["intent"] == "scope":
        session.last_question = job["prior"]
    elif response["engine"] == "puter":
        session.last_question = (
            job["question"]
            if job["fallback"]["intent"] == "help"
            else response.get("context_question") or job["question"]
        )
    session.ai_turn = None
    return remember(session, job["request_id"], response)


def ai_action(session: Session, data: dict) -> dict:
    job = ai_job(session, data.get("ticket"))
    stale = ai.account_stamp(session.account) != job["stamp"]
    if data["op"] == "ai_abort":
        answer = {"engine": "local", "notice": ai.FALLBACK_NOTICE}
        if stale:
            answer.update(
                reply="Your account changed while Grok was working. Ask again to use the latest figures.",
                sources=[],
                intent="help",
            )
        return finish_ai(session, job, answer)
    if stale or time.monotonic() - job["created"] > ai.JOB_TTL:
        raise ValueError(
            "The AI context expired or your account changed. Ask again for current figures."
        )
    if data["op"] == "ai_context":
        verdict = ai.parse_object(data.get("verdict"), {"scope"})
        if verdict["scope"] != "finance":
            return {
                "response": finish_ai(session, job, result(ai.REFUSAL, "scope", suggestions=[]))
            }
        messages, catalog = ai.context_messages(
            session.account, session.history, job["question"], job["fallback"]
        )
        job["catalog"] = catalog
        return {"messages": messages, "output_format": ai.ANSWER_FORMAT, "model": ai.MODEL}
    if "catalog" not in job:
        raise ValueError("The finance topic check must finish before AI guidance can be accepted.")
    return finish_ai(session, job, ai.validated_answer(data.get("completion"), job["catalog"]))


def chat_turn(payload: Any) -> dict:
    try:
        data = payload if isinstance(payload, dict) else {"text": str(payload or "")}
        # No implicit login; client-supplied profile/pending/last are never authority.
        token, session, _ = session_for(data.get("session"))
        text = str(data.get("text") or "").strip()
        if not text or len(text) > 3000:
            raise ValueError("Enter a question between 1 and 3,000 characters.")
        request_id = str(data.get("request_id") or "")[:100]
        with session.lock:
            require_login(session)
            cached = remembered(session, request_id)
            if cached:
                return cached
            session.ai_turn = None
            prior = session.last_question
            refusal = ai.question_guardrail(text, session.account.profile)
            response = (
                result(
                    refusal,
                    "scope",
                    pending=session.pending,
                    changed=False,
                    end=False,
                    context_question=prior,
                    suggestions=[],
                )
                if refusal
                else conversation_turn(
                    text, session.pending, prior, session.account, session.history
                )
            )
            response = record_response(session, text, response)
            response["session"] = token
            if (
                data.get("ai") is True
                and request_id
                and not session.pending
                and response["intent"] not in {"scope", "update", "greeting", "goodbye"}
                and not response.get("changed")
                and not response.get("end")
                and not (
                    response["intent"] == "help"
                    and response.get("context_question") == prior
                    and text.lower().strip(" .!?")
                    in {"help", "who are you", "what can you do", "how does this work"}
                )
            ):
                ticket = secrets.token_urlsafe(24)
                session.ai_turn = {
                    "ticket": ticket,
                    "request_id": request_id,
                    "question": text,
                    "prior": prior,
                    "created": time.monotonic(),
                    "stamp": ai.account_stamp(session.account),
                    "fallback": copy.deepcopy(response),
                }
                response["ai_job"] = {
                    "ticket": ticket,
                    "model": ai.MODEL,
                    "messages": ai.guard_messages(text, prior),
                    "output_format": ai.GUARD_FORMAT,
                }
            return remember(session, request_id, response)
    except LoginRequired as exc:
        return {"error": str(exc), "code": "login_required"}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Chat turn failed")
        return {
            "error": "That question could not be processed. Nothing was automatically confirmed. Please try again."
        }


def finite_amount(value: Any, low: float = 0, high: float = 1_000_000) -> float:
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Enter a valid amount.") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"Enter an amount between {low:,.2f} and {high:,.2f}.")
    return number


def whole_number(value: Any, low: int, high: int) -> int:
    number = float(value)
    if isinstance(value, bool) or not number.is_integer() or not low <= number <= high:
        raise ValueError(f"Choose a whole number between {low} and {high}.")
    return int(number)


def speech_response(session: Session, data: dict) -> dict:
    # Authorize under the account lock, but never hold it during downloads/inference.
    with session.lock:
        require_login(session)
        passages = (
            speech_chunks(PREVIEW)
            if data.get("preview") is True
            else next(
                (
                    m["speech_chunks"]
                    for m in session.history
                    if m.get("id") == data.get("message_id") and m["role"] == "assistant"
                ),
                [],
            )
        )
        if not passages:
            raise ValueError(
                "That answer is no longer in this session. Ask it again, then try read-aloud."
            )
        index = whole_number(data.get("index", 0), 0, len(passages) - 1)
        text = passages[index]
    audio = synthesize(
        text, str(data.get("voice", "af_heart")), finite_amount(data.get("speed", 1), 0.85, 1.15)
    )
    with session.lock:
        require_login(session)
        return {**audio, "index": index, "chunks": len(passages)}


def filtered_transactions(session: Session, data: dict):
    tx = session.account.transactions.copy()
    key = data.get("period", "all")
    if key in {"month", "last_month", "90days"}:
        tx = period_transactions(session.account, reporting_period(key))
    search = str(data.get("search") or "").strip()[:200]
    if search:
        mask = (
            tx[["merchant", "description", "category", "transaction_id"]]
            .astype(str)
            .apply(lambda s: s.str.contains(search, case=False, regex=False))
            .any(axis=1)
        )
        tx = tx.loc[mask]
    for column in ("category", "account"):
        if data.get(column):
            tx = tx.loc[tx[column].eq(str(data[column]))]
    if data.get("direction") == "out":
        tx = tx.loc[tx.amount < 0]
    if data.get("direction") == "in":
        tx = tx.loc[tx.amount > 0]
    column = "amount" if data.get("sort") == "amount" else "date"
    return tx.sort_values([column, "transaction_id"], ascending=[data.get("order") == "asc", False])


def export_csv(tx) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    columns = [
        "transaction_id",
        "date",
        "merchant",
        "amount",
        "category",
        "account",
        "description",
    ]
    writer.writerow(columns)
    for row in tx.to_dict("records"):
        values = []
        for column in columns:
            value = str(row[column])[:10] if column == "date" else row[column]
            # Spreadsheet formulas in user-entered merchant/description fields must stay text.
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return stream.getvalue()


def workspace_action(payload: Any) -> dict:
    try:
        if not isinstance(payload, dict):
            raise TypeError("Invalid workspace request.")
        op = payload.get("op", "bootstrap")
        if op in {"bootstrap", "login", "logout"}:
            return login_action({**payload, "op": op})
        _token, session, _ = session_for(payload.get("session"))
        if op == "speech":
            return speech_response(session, payload)
        request_id = str(payload.get("request_id") or "")[:100]
        with session.lock:
            require_login(session)
            cached = remembered(session, request_id)
            if cached:
                return cached
            if op in {"ai_context", "ai_finish", "ai_abort"}:
                return ai_action(session, payload)
            if op == "guardrail_history":
                response = {"guardrails": guardrail_view(session)}
            elif op == "guardrail_check":
                response = guardrail_check(session, payload.get("prompt"))
            elif op == "clear_guardrail_history":
                session.guardrail_history.clear()
                response = {"guardrails": guardrail_view(session)}
            elif op == "dashboard":
                if payload.get("period") not in {None, "month", "last_month", "90days"}:
                    raise ValueError("Choose a supported reporting period.")
                session.period = payload.get("period") or session.period
                response = {"dashboard": dashboard(session.account, session.period)}
            elif op == "transactions":
                tx = filtered_transactions(session, payload)
                page = max(1, min(10000, int(payload.get("page", 1))))
                size = max(1, min(100, int(payload.get("size", 10))))
                page = min(page, max(1, math.ceil(len(tx) / size)))
                response = {
                    "items": [
                        transaction_dict(r)
                        for r in tx.iloc[(page - 1) * size : page * size].to_dict("records")
                    ],
                    "total": len(tx),
                    "page": page,
                    "pages": max(1, math.ceil(len(tx) / size)),
                    "inflow": round(float(tx.loc[tx.amount > 0, "amount"].sum()), 2),
                    "outflow": round(float(-tx.loc[tx.amount < 0, "amount"].sum()), 2),
                }
            elif op == "export":
                tx = filtered_transactions(session, payload)
                response = {
                    "csv": export_csv(tx),
                    "filename": f"solvera-{session.account.profile['id']}-transactions-{f.AS_OF}.csv",
                    "count": len(tx),
                }
            elif op == "plan":
                reserve = finite_amount(
                    payload.get("reserve", session.account.preferences.get("reserve", 1000))
                )
                include_income = payload.get("include_income") is True
                plan = payment_plan(session.account, reserve, include_income)
                session.account.preferences["reserve"] = reserve
                response = {
                    "plan": plan,
                    "dashboard": dashboard(session.account, session.period),
                }
            elif op == "simulate":
                days = whole_number(payload.get("days", 5), 0, 90)
                response = {
                    "simulation": delay_preview(session.account, str(payload.get("bill_id")), days)
                }
            elif op in {"stage_transaction", "stage_payment"}:
                if session.pending:
                    raise ValueError(
                        "Confirm or cancel the pending change in the assistant before recording another one."
                    )
                if op == "stage_payment":
                    bill = session.account.find_bill(str(payload.get("bill_id")))
                    if not bill or bill.status == "Paid":
                        raise ValueError("Choose an unpaid bill.")
                    amount = finite_amount(payload.get("amount", bill.amount), 0.01, bill.amount)
                    pending = {
                        "action": "payment",
                        "bill_id": bill.bill_id,
                        "amount": amount,
                    }
                    description = f"Record {f.money(amount)} already paid to {bill.name}"
                else:
                    amount = finite_amount(payload.get("amount"), 0.01)
                    kind = payload.get("kind")
                    if kind not in {"income", "expense"}:
                        raise ValueError("Choose income or expense.")
                    category = (
                        "Income"
                        if kind == "income"
                        else str(payload.get("category") or "Other expenses")[:80]
                    )
                    if kind == "expense" and category in {"Income", "Transfers"}:
                        raise ValueError("Choose an expense category, not income or transfers.")
                    merchant = str(payload.get("merchant") or "").strip()[:120]
                    if not merchant:
                        raise ValueError("Enter a merchant or income source.")
                    pending = {
                        "action": "transaction",
                        "amount": amount if kind == "income" else -amount,
                        "category": category,
                        "merchant": merchant,
                        "description": str(payload.get("description") or "Manually recorded")[:500],
                        "type": "Income" if kind == "income" else "Purchase",
                    }
                    description = f"Record a {f.money(amount)} {kind} for {merchant}"
                response = result(
                    f"{description}? Confirm in the assistant to add it to this demo's checking ledger. No real money will move.",
                    "update",
                    pending=pending,
                    changed=False,
                    end=False,
                )
                response = record_response(session, description, response)
            elif op in {"clear_chat", "reset"}:
                if op == "clear_chat" and session.pending:
                    raise ValueError(
                        "Confirm or cancel your pending change before clearing the conversation."
                    )
                if op == "reset":
                    session.account.reset()
                    session.pending = None
                    session.requests.clear()
                session.history.clear()
                session.last_question = ""
                session.ai_turn = None
                response = {"messages": [], "pending": None}
                if op == "reset":
                    response["dashboard"] = dashboard(session.account, session.period)
            else:
                raise ValueError("Unknown workspace action.")
            return remember(session, request_id, response)
    except LoginRequired as exc:
        return {"error": str(exc), "code": "login_required"}
    except (ValueError, TypeError, OverflowError) as exc:
        return {"error": str(exc)}
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Workspace action failed")
        return {"error": "The workspace could not complete that request. Please try again."}
