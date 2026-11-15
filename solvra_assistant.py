"""Account-grounded conversational finance engine.

Calculations, sources, follow-ups, and staged changes share the same ledger as the
workspace. This local engine deliberately does not pretend to be a general LLM.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from typing import Any

import solvra_app as f
from solvra_insights import (
    Period,
    delay_preview,
    financial_trouble,
    insights,
    payment_plan,
    planning_buffer,
    reporting_period,
    spending_rows,
    totals,
)

CATEGORY_ALIASES = {
    "grocer": ["Groceries"],
    "grocery": ["Groceries"],
    "food": ["Groceries", "Dining & Entertainment"],
    "dining": ["Dining & Entertainment"],
    "restaurant": ["Dining & Entertainment"],
    "eating out": ["Dining & Entertainment"],
    "entertainment": ["Dining & Entertainment"],
    "transport": ["Transportation"],
    "fuel": ["Transportation"],
    "gasoline": ["Transportation"],
    "shopping": ["Shopping"],
    "medical": ["Medical"],
    "healthcare": ["Medical"],
    "housing": ["Housing"],
    "rent": ["Housing"],
    "utilities": ["Utilities"],
    "subscription": ["Subscriptions"],
    "insurance": ["Insurance"],
    "fees": ["Fees"],
    "debt payments": ["Debt payments"],
}
MONTHS = {
    name.lower(): i
    for i in range(1, 13)
    for name in (calendar.month_name[i], calendar.month_abbr[i])
}
NUMBER_WORDS = {
    word: value
    for value, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "  # noqa: SIM905
        "fourteen fifteen sixteen seventeen eighteen nineteen".split()
    )
} | dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))  # noqa: SIM905


def normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "").replace("’", "'").replace("–", "-")).strip()
    return (
        re.sub(r"^(?:(?:hey|hi|okay|ok)\s+)?solvra[\s,.!?]*", "", text, flags=re.IGNORECASE).strip()
        or text
    )


def amount_in(text: str) -> float | None:
    # Dates are not payment amounts ("I paid electricity on November 12").
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", text)
    month_names = "|".join(MONTHS)
    text = re.sub(
        rf"\b(?:{month_names})\s+\d{{1,2}}(?:,?\s+\d{{4}})?\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    currency_parts = re.split(r"\bdollars?\b", text, maxsplit=1, flags=re.IGNORECASE)
    if len(currency_parts) == 2 and re.search(r"\bcents?\b", currency_parts[1]):
        major = amount_in(currency_parts[0])
        minor = amount_in(currency_parts[1])
        if major is not None and minor is not None and 0 <= minor < 100:
            return round(major + minor / 100, 2)
    match = re.search(
        r"\$\s*([\d,]+(?:\.\d{1,2})?)|\b(\d[\d,]*(?:\.\d{1,2})?)\s*(?:dollars?|bucks?)?\b",
        text,
    )
    if match:
        return float((match.group(1) or match.group(2)).replace(",", ""))
    # Browser recognizers frequently return spelled-out amounts.
    words = re.findall(r"[a-z]+", text.lower().replace("-", " "))
    number = total = 0
    found = False
    for word in words:
        if word in NUMBER_WORDS:
            number += NUMBER_WORDS[word]
            found = True
        elif word == "hundred":
            number = max(number, 1) * 100
            found = True
        elif word == "thousand":
            total += max(number, 1) * 1000
            number = 0
            found = True
        elif word == "and" and found:
            continue
        elif found:
            break
    return float(total + number) if found else None


def days_in(text: str, default: int = 5) -> int:
    match = re.search(r"(\d+)\s*[- ]?days?", text)
    if match:
        return min(90, int(match.group(1)))
    # Spelled numbers are common in browser transcripts: "ten days late".
    words = "|".join([*NUMBER_WORDS, "hundred", "thousand", "and"])
    spoken = re.search(rf"\b((?:{words})(?:[ -]+(?:{words}))*)\s*[- ]?days?\b", text.lower())
    amount = amount_in(spoken.group(1)) if spoken else None
    return min(90, max(0, int(amount))) if amount is not None else default


def period_for(text: str, fallback: str = "") -> Period:
    low = text.lower()
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", low)
    if len(dates) == 1 and any(term in low for term in ("since", "from")):
        try:
            start = dt.date.fromisoformat(dates[0])
            if start <= f.AS_OF:
                return Period(start, f.AS_OF, f"{start:%b %d} through {f.AS_OF:%b %d}")
        except ValueError:
            pass
    if len(dates) >= 2:
        try:
            start, end = (dt.date.fromisoformat(d) for d in dates[:2])
            if start <= end <= f.AS_OF and (end - start).days <= 1096:
                return Period(start, end, f"{start:%b} {start.day}–{end:%b} {end.day}")
        except ValueError:
            pass
    if any(t in low for t in ("this month", "month to date", "so far")):
        return reporting_period()
    if "last month" in low:
        return reporting_period("last_month")
    if re.search(r"(?:last|past)\s+(\d+)\s+days", low):
        days = min(730, max(1, int(re.search(r"(?:last|past)\s+(\d+)\s+days", low).group(1))))
        return Period(f.AS_OF - dt.timedelta(days=days - 1), f.AS_OF, f"the last {days} days")
    if "today" in low:
        return Period(f.AS_OF, f.AS_OF, "today")
    if "yesterday" in low:
        day = f.AS_OF - dt.timedelta(days=1)
        return Period(day, day, "yesterday")
    if "last week" in low:
        end = f.AS_OF - dt.timedelta(days=f.AS_OF.weekday() + 1)
        return Period(end - dt.timedelta(days=6), end, "last week")
    if "this week" in low:
        return Period(f.AS_OF - dt.timedelta(days=f.AS_OF.weekday()), f.AS_OF, "this week so far")
    if "this year" in low:
        return Period(f.AS_OF.replace(month=1, day=1), f.AS_OF, "this year so far")
    for word in re.findall(r"[a-z]+", low):
        if word in MONTHS:
            month = MONTHS[word]
            year_match = re.search(r"\b(202[4-9])\b", low)
            year = (
                int(year_match.group()) if year_match else f.AS_OF.year - int(month > f.AS_OF.month)
            )
            start = dt.date(year, month, 1)
            end = min(f.AS_OF, dt.date(year, month, calendar.monthrange(year, month)[1]))
            if start <= end:
                return Period(start, end, f"{start:%B %Y}")
    return period_for(fallback) if fallback else reporting_period("last_month")


def category_for(text: str) -> list[str]:
    low = text.lower()
    if re.search(r"\bgas\b", low) and "natural gas" not in low and "gas bill" not in low:
        return ["Transportation"]
    # Match specific phrases before the broad food alias.
    for alias, categories in CATEGORY_ALIASES.items():
        if alias in low:
            return categories
    return []


def source(label: str, detail: str) -> dict:
    return {"label": label, "detail": detail}


def result(
    reply: str,
    intent: str,
    sources: list | None = None,
    suggestions: list | None = None,
    pending: dict | None = None,
    **extra,
) -> dict:
    return {
        "reply": reply,
        "intent": intent,
        "sources": sources or [],
        "suggestions": suggestions
        if suggestions is not None
        else [
            "What bills are due this week?",
            "Where can I cut back?",
            "Can I afford a $200 purchase?",
        ],
        "pending": pending,
        **extra,
    }


def spending_answer(text: str, account: f.AccountStore, last: str = "") -> dict:
    period = period_for(text, last)
    date_tokens = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    for token in date_tokens:
        try:
            if dt.date.fromisoformat(token) > f.AS_OF:
                return result(
                    f"The ledger ends on {f._spoken_date(f.AS_OF)}. I can't report actual spending after that snapshot. Ask for an earlier period, or use a what-if for future spending.",
                    "spending",
                )
        except ValueError:
            return result("That date is not valid. Try YYYY-MM-DD or a named month.", "spending")
    categories = category_for(text) or (
        category_for(last)
        if re.match(r"^(and|what about|how about|compare|what changed)", text.lower())
        else []
    )
    rows = spending_rows(account, period)
    if categories:
        rows = rows.loc[rows.category.isin(categories)]
    # Named merchants and individual bills are valid filters as well.
    merchant_label = ""
    if not categories:
        candidates = sorted(set(account.transactions.merchant), key=len, reverse=True)
        named = next(
            (
                m
                for m in candidates
                if re.search(rf"(?<!\w){re.escape(m.lower())}(?!\w)", text.lower())
            ),
            None,
        )
        if named:
            rows = rows.loc[rows.merchant.eq(named)]
            merchant_label = f" at {named}"
        else:
            named_bill = f._find_bill_in_text(text.lower(), account)
            if named_bill:
                rows = rows.loc[
                    rows.merchant.eq(named_bill.provider)
                    | rows.description.str.contains(named_bill.name, case=False, regex=False)
                ]
                merchant_label = f" on {named_bill.name}"
    total = round(float(-rows.amount.sum()), 2)
    label = " on " + " and ".join(categories).lower() if categories else merchant_label
    reply = f"You spent {f.money(total)}{label} in {period.label}, across {len(rows)} recorded transactions."
    is_compare = any(
        w in text.lower()
        for w in (
            "compar",
            "versus",
            " vs ",
            "changed",
            "more than",
            "less than",
            "previous",
            "increase",
        )
    )
    src = [
        source(
            "Transaction ledger",
            f"{period.start} to {period.end}; {len(rows)} matching expenses. Transfers and income excluded.",
        )
    ]
    if is_compare:
        previous_period = period.previous
        # Explicit 'October vs September' comparisons respect both named months.
        month_words = [w for w in re.findall(r"[a-z]+", text.lower()) if w in MONTHS]
        if len(month_words) > 1:
            previous_period = period_for(month_words[1])
        previous = spending_rows(account, previous_period)
        if categories:
            previous = previous.loc[previous.category.isin(categories)]
        if merchant_label:
            if named:
                previous = previous.loc[previous.merchant.eq(named)]
            else:
                previous = previous.loc[
                    previous.merchant.eq(named_bill.provider)
                    | previous.description.str.contains(named_bill.name, case=False, regex=False)
                ]
        before = round(float(-previous.amount.sum()), 2)
        delta = round(total - before, 2)
        percentage = f" ({abs(delta / before * 100):.1f}%)" if before else ""
        reply += f"\n\nThat's {f.money(abs(delta))}{percentage} {'more' if delta >= 0 else 'less'} than {f.money(before)} in {previous_period.label}."
        src.append(
            source(
                "Comparable period",
                f"{previous_period.start} to {previous_period.end}; {len(previous)} matching expenses.",
            )
        )
    if not rows.empty:
        groups = rows.groupby("category").amount.sum().abs().sort_values(ascending=False).head(3)
        if not categories and not merchant_label:
            reply += (
                "\n\nThe biggest categories were "
                + f._join_words([f"{name} ({f.money(value)})" for name, value in groups.items()])
                + "."
            )
        largest = rows.loc[rows.amount.idxmin()]
        reply += f"\n\nLargest transaction: {largest.merchant}, {f.money(-largest.amount)} on {f._spoken_date(largest.date)}."
    else:
        reply += " No matching expenses are recorded; that does not prove no purchases happened outside this demo."
    return result(
        reply,
        "spending",
        src,
        [
            "Compare that with the previous period.",
            "What about groceries?",
            "Where can I cut back?",
        ],
        context_question=f"How much did I spend {'on ' + ' and '.join(categories) if categories else merchant_label} from {period.start} to {period.end}?",
    )


def answer_question(question: str, account: f.AccountStore, context: list | None = None) -> dict:
    q = normalize(question)
    low = q.lower().strip(" .!?")
    last = next(
        (str(x.get("content", "")) for x in reversed(context or []) if x.get("role") == "user"),
        "",
    )
    prior = last.lower()
    if not low:
        return result(
            "Ask about your balance, bills, spending, or a what-if. You can type or use the microphone.",
            "help",
        )

    if re.search(r"^(?:hi|hello|hey|greetings|howdy|good\s+(?:morning|afternoon|evening))\b", low) or low in ("help", "what can you do", "who are you", "what is solvra"):
        p_info = getattr(account, "profile", {})
        name = p_info.get("first_name", "there")
        checking = account.balance("Checking")
        bills = f.current_open_bills(account, 14)
        t = financial_trouble(account)
        reply = (
            f"Hello, {name}! I'm Solvra, your personal finance assistant for this demo account.\n\n"
            f"Here is a quick snapshot of your finances:\n"
            f"• Checking: {f.money(checking)} | Savings: {f.money(account.balance('Savings'))}\n"
            f"• Upcoming bills: {len(bills)} due in the next 14 days ({f.money(sum(b.amount for b in bills))})\n"
            f"• Financial status: {t['label']} ({t['score']}/100 pressure points)\n\n"
            "Ask me anything about your finances—spending by category, whether you can afford a purchase, bill payment planning, or guidance on what to prioritize."
        )
        return result(
            reply,
            "greeting",
            [source("Account ledger", f"Snapshot {f.AS_OF}")],
            ["What bills are due this week?", "Can I afford a $200 purchase?", "Where does my money go?"],
        )

    if any(w in low for w in ("who am i", "my profile", "my story", "tell me about myself", "who is maya", "who is jordan", "who is aisha", "who is marcus")):
        p_info = getattr(account, "profile", {})
        name = p_info.get("name", "Demo User")
        role = p_info.get("role", "Professional")
        story = p_info.get("story", "")
        goal = p_info.get("goal", "")
        reply = (
            f"You are viewing the demo account for {name} ({role}).\n\n"
            f"• Background: {story}\n"
            f"• Financial goal: {goal}\n"
            f"• Current balances: {f.money(account.balance('Checking'))} in checking and {f.money(account.balance('Savings'))} in savings.\n\n"
            "To switch to another fictional person (Maya, Jordan, Aisha, or Marcus), select Log out in Settings."
        )
        return result(
            reply,
            "profile",
            [source("Profile registry", f"{name} ({role})")],
            ["What are my accounts?", "What bills do I have?", "How am I doing financially?"],
        )

    if re.search(
        r"\b(?:financial (?:trouble|pressure|risk|stress)|trouble (?:rank|score)|urgency|triage|risk ranking|how (?:bad|serious)|am i (?:in trouble|at risk)|rank my finances)\b",
        low,
    ):
        t = financial_trouble(account)
        reply = (
            f"Your financial-trouble level is {t['label']}: priority {t['rank']} of 4, with {t['score']} of 100 pressure points. Higher points mean more pressure; priority 1 is most urgent. This is separate from the financial-health score.\n\n"
            + "\n".join(
                f"• {x['name']}: {x['points']:g}/{x['max_points']} points. {x['evidence']}"
                for x in t["factors"]
            )
        )
        if t["override"]:
            reply += f"\n\nSafety floor: {t['override']} Weighted total {t['raw_score']}/100; final pressure {t['score']}/100."
        reply += (
            "\n\nThresholds: Stable 0–19 (priority 4); Watch 20–39 (3); High 40–69 (2); Critical 70–100 (1).\n\n"
            + t["action"]
            + " "
            + t["limits"]
        )
        return result(
            reply,
            "trouble",
            [
                source(
                    "Financial-trouble triage v1",
                    f"Calculated at {f.AS_OF}; six weighted pressure factors and explicit overdue-essential safety floors. Dashboard reporting filters do not change these windows.",
                )
            ],
            [
                "Build my bill payment plan and explain the order.",
                "What bills are overdue?",
                "How can I build a stronger emergency fund?",
            ],
        )

    parts = [
        part.strip(" ?")
        for part in re.split(
            r"(?:\?\s+|\band\s+)(?=(?:what|how|when|can|do|is)\b)",
            q,
            flags=re.IGNORECASE,
        )
        if part.strip(" ?")
    ]
    if len(parts) > 1 and not re.search(r"\b(paid|received|got|record|what if|suppose)\b", low):
        answers = [answer_question(part, account, context) for part in parts[:3]]
        if not any(a.get("pending") for a in answers):
            return result(
                "\n\n".join(a["reply"] for a in answers),
                "combined",
                [source for answer in answers for source in answer["sources"]],
                answers[-1]["suggestions"],
                context_question=answers[-1].get("context_question", parts[-1]),
            )

    if (
        re.search(r"\b(why|explain)\b", low)
        and "order" in low
        and any(term in low for term in ("bill", "payment", "plan"))
    ):
        return answer_question(
            "Why?",
            account,
            [{"role": "user", "content": "Build my bill payment plan."}],
        )

    # Follow-ups retain the original subject AND reporting window.
    if re.fullmatch(
        r"(?:and |what about |how about )?(checking|savings)(?: account| balance)?", low
    ):
        name = "Checking" if "checking" in low else "Savings"
        return result(
            f"Your {name.lower()} balance is {f.money(account.balance(name))}.",
            "balance",
            [
                source(
                    f"{name} ledger",
                    f"Opening balance plus recorded transactions through {f.AS_OF}.",
                )
            ],
        )
    if (
        re.fullmatch(
            r"(?:why|why is that|explain that|how so|tell me more|explain the order)\??",
            low,
        )
        and last
    ):
        if any(
            w in prior for w in ("balance", "money do i have", "cash", "checking", "savings")
        ) and not any(w in prior for w in ("pay", "spend")):
            checking, savings = account.balance("Checking"), account.balance("Savings")
            return result(
                f"Together, checking ({f.money(checking)}) and savings ({f.money(savings)}) total {f.money(checking + savings)}. Each balance is its opening amount plus the signed transactions recorded for that account. Credit-card debt is not spendable cash.",
                "balance",
                [
                    source(
                        "Account ledgers",
                        f"{len(account.transactions)} records through {f.AS_OF}.",
                    )
                ],
                ["Can I afford a $200 purchase?", "What is my total debt?"],
            )
        if any(
            w in prior
            for w in (
                "pay first",
                "payment plan",
                "bill plan",
                "pay my bills",
                "priorit",
                "bill payment",
            )
        ):
            return result(
                "The plan checks available cash on every payment date, holds back your chosen reserve, and prioritizes avoiding recorded late fees, interest, and service or housing consequences. Required minimums and all-or-nothing bill rules are enforced.\n\nWhen every bill is affordable, due-date order is a practical reminder—not a claim that the earliest bill is always the riskiest. Unconfirmed future income is excluded unless you explicitly include it. Risk weights are not dollar costs.",
                "plan",
                [
                    source(
                        "Payment optimizer",
                        "SciPy mixed-integer optimization; recorded bill terms and dated cash constraints.",
                    )
                ],
                ["Build my bill payment plan.", "What if my paycheck is 5 days late?"],
            )
        if any(w in prior for w in ("spend", "grocer", "compar")):
            return spending_answer("Compare that with the previous period.", account, last)
        if "due" in prior or "bill" in prior:
            return result(
                "The bill dates and amounts I listed come from the account's open bills and recorded due dates. A provider balance or change not entered here may differ. Check the provider for current terms.",
                "bills",
                [source("Open bill register", f"Snapshot {f.AS_OF}.")],
            )
        return answer_question(last, account)
    if (
        last
        and re.match(r"^(and|what about|how about|compare that|what changed)", low)
        and (
            category_for(low)
            or any(w in low for w in ("month", "week", "period", "days"))
            or any(m in low.split() for m in MONTHS)
        )
        and any(w in prior for w in ("spend", "compar", "grocer", "expenses"))
    ):
        return spending_answer(q, account, last)

    hypothetical = any(
        w in low for w in ("what if", "what happens if", "suppose", "if i ", "if my ", "would ")
    )
    amount = amount_in(low)
    bill = f._find_bill_in_text(low, account)
    # Updates are staged, never executed while interpreting text.
    # A stated balance/gift inside an advice question is not a request to add income.
    advice = re.search(r"\b(?:how|why|should|explain|recommend|advise|help me)\b", low)
    explicit_record = re.search(r"\b(?:record|log|add|mark|adjust|update)\b", low)
    record_change = not hypothetical and not (advice and not explicit_record)
    update_intent = bool(
        re.search(r"\b(received|got paid|got|earned|deposited|paid|record)\b", low)
    )
    if (
        record_change
        and update_intent
        and (
            re.search(r"(?<![\w\d])-\s*\$?\s*\d|\b(minus|negative)\b", low)
            or (amount is not None and amount > 1_000_000)
        )
    ):
        return result(
            "Please use a positive amount of at most $1,000,000 for a recorded change. Nothing was staged or changed.",
            "update",
        )
    if (
        record_change
        and re.search(r"\b(received|got paid|got|earned|deposited|made)\b", low)
        and amount
    ):
        pending = {
            "action": "income",
            "amount": amount,
            "date": f.AS_OF.isoformat(),
            "description": "User-reported income",
        }
        return result(
            f"Should I add a {f.money(amount)} deposit to your demo checking account? Confirm to record it, or cancel. This will not connect to a bank or move real money.",
            "update",
            pending=pending,
        )
    if record_change and re.search(r"\b(now have|have)\b.*\bless\b", low) and amount:
        return result(
            f"Should I lower your recorded checking balance by {f.money(amount)}? Confirm to record the adjustment, or cancel.",
            "update",
            pending={
                "action": "cash_reduction",
                "amount": amount,
                "description": "User-reported cash adjustment",
            },
        )
    if (
        record_change
        and "extension" in low
        and any(w in low for w in ("approved", "confirmed", "extended"))
        and bill
    ):
        days = days_in(low)
        return result(
            f"Should I record a {days}-day provider-approved extension for {bill.name}? Confirm only if the provider has already agreed.",
            "update",
            pending={"action": "extension", "bill_id": bill.bill_id, "days": days},
        )
    if (
        record_change
        and re.search(
            r"\b(?:i |already |just |record |have )paid\b|\brecord (?:a |my )?payment\b",
            low,
        )
        and bill
    ):
        payment = amount if amount is not None else bill.amount
        if bill.status == "Paid" or bill.amount <= 0:
            return result(f"{bill.name} is already recorded as paid. Nothing changed.", "bills")
        return result(
            f"Should I record a {f.money(min(payment, bill.amount))} payment toward {bill.name}? Confirm only if you have already paid it. This records the payment in the demo; it does not send money.",
            "update",
            pending={"action": "payment", "bill_id": bill.bill_id, "amount": payment},
        )
    if "paycheck" in low and any(w in low for w in ("delay", "late")):
        days = days_in(low)
        payday = account.preferences.get("payday", f.AS_OF)
        if isinstance(payday, str):
            payday = dt.date.fromisoformat(payday)
        new_date = payday + dt.timedelta(days=days)
        if record_change:
            return result(
                f"Should I move the expected paycheck from {f._spoken_date(payday)} to {f._spoken_date(new_date)}? Confirm to change the expectation, or cancel.",
                "update",
                pending={
                    "action": "paycheck_delay",
                    "date": payday.isoformat(),
                    "days": days,
                },
            )
        before = sum(b.amount for b in f.current_open_bills(account) if b.effective_due <= new_date)
        gap = max(0, before - account.balance("Checking"))
        return result(
            f"If your expected {f.money(float(account.preferences.get('paycheck', 2200)))} paycheck arrived {days} days late, on {f._spoken_date(new_date)}, {f.money(before)} of currently open bills would be due by then.\n\n"
            + (
                f"Checking alone covers those bills, leaving {f.money(account.balance('Checking') - before)} before everyday spending."
                if not gap
                else f"Checking would be {f.money(gap)} short before everyday spending. Contact providers before their due dates."
            )
            + "\n\nThis is just a what-if. The paycheck is unconfirmed, savings are excluded, and nothing was recorded.",
            "whatif",
            [
                source("Open bills", f"Unpaid obligations through {new_date}."),
                source("Checking ledger", f.money(account.balance("Checking"))),
            ],
            ["Build my bill payment plan.", "Can I afford a $200 purchase?"],
        )
    if hypothetical and bill and any(w in low for w in ("late", "delay", "push back")):
        days = days_in(low)
        preview = delay_preview(account, bill.bill_id, days)
        return result(
            f"Paying {bill.name} {days} days after its {f._spoken_date(bill.effective_due)} due date would mean paying on {f._spoken_date(preview['date'])}.\n\nModeled late fees: {f.money(preview['late_fees'])}. Modeled interest: {f.money(preview['interest'])}."
            + (
                f"\n\nPossible consequence: {bill.consequence}."
                if preview["risk"]
                else " No modeled service-risk deadline is crossed in this scenario."
            )
            + f"\n\nCheck {bill.provider}'s actual terms. This is not an approved extension; nothing changed.",
            "whatif",
            [
                source(
                    "Recorded bill terms",
                    f"{f.money(bill.late_fee)} late fee, {bill.grace_days} grace days, {bill.apr * 100:.1f}% APR.",
                )
            ],
            [f"When is {bill.name} due?", "Build my bill payment plan."],
        )
    if hypothetical and amount and any(w in low for w in ("receiv", "extra", "got paid")):
        base = planning_buffer(account)
        return result(
            f"An extra {f.money(amount)} would increase modeled 30-day headroom from {f.money(base['headroom'])} to {f.money(base['headroom'] + amount)}, with bills, everyday-spending allowance, and reserve unchanged.\n\nThis is just a what-if. No deposit has been recorded.",
            "whatif",
            [
                source(
                    "30-day planning model",
                    "Checking minus open bills, recent variable spending, and reserve; expected income excluded.",
                )
            ],
        )

    if hypothetical and amount and any(w in low for w in ("spend", "spent", "buy", "purchase")):
        preview = answer_question(f"Can I afford a ${amount:.2f} purchase?", account)
        preview["reply"] += "\n\nThis is a what-if only; no expense was recorded."
        return preview
    if hypothetical:
        return result(
            "I can model an extra deposit, a late paycheck, a purchase, or a bill paid late. Please name the bill and number of days, or give a purchase amount. No due date or balance was changed.",
            "whatif",
        )

    afford_intent = any(
        w in low
        for w in (
            "afford",
            "can i buy",
            "can i purchase",
            "can i get",
            "can i spend",
            "should i buy",
            "is it safe to buy",
            "is it safe to spend",
            "safe to spend",
            "safely spend",
            "left to spend",
            "spending room",
            "headroom",
            "spendable",
            "can i save",
        )
    )
    if afford_intent:
        buffer = planning_buffer(account)
        if re.search(r"\b(?:save|deposit|put aside|set aside)\b", low) and amount is not None:
            reply = (
                f"Setting aside {f.money(amount)} into savings is "
                + (
                    f"safe under your current plan. Your modeled 30-day spending room is {f.money(buffer['headroom'])}, leaving {f.money(buffer['headroom'] - amount)} in headroom after the transfer."
                    if buffer["headroom"] >= amount
                    else f"tight under your current plan. Your modeled 30-day headroom is {f.money(buffer['headroom'])}, so transferring {f.money(amount)} would reduce your checking cash below your recommended 30-day buffer."
                )
                + f"\n\nChecking is currently {f.money(buffer['checking'])}, with {f.money(buffer['bills'])} in 30-day bills and a {f.money(buffer['reserve'])} cash reserve."
            )
            return result(
                reply,
                "affordability",
                [
                    source("Checking ledger", f.money(buffer["checking"])),
                    source("30-day headroom", f.money(buffer["headroom"])),
                ],
                [
                    "Build my bill payment plan.",
                    "How can I build a stronger emergency fund?",
                    "Where can I cut back?",
                ],
            )
        reply = f"Your modeled 30-day spending room is {f.money(max(0, buffer['headroom']))}."
        if amount is not None:
            reply = (
                f"A {f.money(amount)} purchase fits this model, leaving {f.money(buffer['headroom'] - amount)} of headroom."
                if buffer["headroom"] >= amount
                else f"A {f.money(amount)} purchase would exceed modeled headroom by {f.money(amount - buffer['headroom'])}."
            )
        else:
            reply += " You can safely make purchases up to this amount without compromising your 30-day bill obligations or cash reserve."
        reply += (
            f"\n\nStarting with {f.money(buffer['checking'])} in checking, I set aside:\n"
            f"• {f.money(buffer['bills'])} for recorded bills due within 30 days\n"
            f"• {f.money(buffer['everyday_allowance'])} for everyday spending (your last 90 days, scaled to 30)\n"
            f"• {f.money(buffer['reserve'])} as a cash reserve\n\n"
            "Savings and expected income are excluded. This is a planning estimate, not a guarantee; unrecorded expenses can change it."
        )
        return result(
            reply,
            "affordability",
            [
                source("Checking ledger", f.money(buffer["checking"])),
                source("30-day bill register", f.money(buffer["bills"])),
                source(
                    "90-day variable expenses",
                    "Groceries, transport, medical, dining, and shopping.",
                ),
            ],
            [
                "Build my bill payment plan.",
                "Where can I cut back?",
                "What bills are due this week?",
            ],
        )

    if any(
        w in low
        for w in (
            "emergency",
            "safety net",
            "build my savings",
            "build a stronger",
            "save more",
            "saving goal",
        )
    ):
        monthly = f.essential_monthly_expense(account)
        savings = account.balance("Savings")
        gap = max(0, monthly * 3 - savings)
        per_month = gap / 6
        return result(
            f"Savings are {f.money(savings)}, covering about {savings / max(monthly, 1):.1f} months of recent essential expenses ({f.money(monthly)}/month).\n\n"
            + (
                f"A modeled 3-month buffer is {f.money(monthly * 3)}. The gap is {f.money(gap)}; setting aside about {f.money(per_month)} a month would close it in 6 months, before interest. Check that amount against your bills and variable spending first."
                if gap
                else "Your modeled 3-month target is covered. Before increasing it, consider your high-interest debt and any known large expenses."
            )
            + "\n\nThe target is a planning assumption, not personalized financial advice. Nothing is transferred.",
            "savings",
            [
                source("Savings ledger", f.money(savings)),
                source(
                    "6-month essentials",
                    "Housing, utilities, groceries, transport, insurance, debt payments, and medical; divided by six.",
                ),
            ],
            ["Can I afford a $200 purchase?", "What is my total debt?"],
        )
    if "why" in low and "saving" in low:
        h = account.records["balance_history"].tail(4)
        delta = float(h.savings.iloc[-1] - h.savings.iloc[0])
        return result(
            f"Your last four savings snapshots changed by {f.money(delta)}. Savings balances reflect recorded transfers and withdrawals, not just your checking-account spending. This demo does not infer a reason for every transfer.",
            "savings",
            [source("Monthly balance history", "Last four recorded savings snapshots.")],
        )
    if any(
        w in low
        for w in (
            "cut back",
            "reduce spending",
            "save money",
            "recommend",
            "suggest",
            "improve my",
            "insights",
            "budget",
        )
    ):
        period = reporting_period("last_month")
        rows = spending_rows(account, period)
        flexible = rows.loc[
            rows.category.isin(["Dining & Entertainment", "Shopping", "Subscriptions"])
        ]
        potential = float(-flexible.amount.sum())
        groceries = float(-rows.loc[rows.category.eq("Groceries"), "amount"].sum())
        suggestions = insights(account)
        reply = (
            f"Here are specific options from your account—not generic tips:\n\n"
            f"• In {period.label}, dining, shopping, and subscriptions totaled {f.money(potential)}. A hypothetical 20% reduction would free up {f.money(potential * 0.2)}/month. This is a target, not predicted savings.\n"
            f"• Groceries were {f.money(groceries)} that month. A 10% reduction would free up {f.money(groceries * 0.1)}; compare receipts before deciding whether that's realistic.\n"
            f"• {suggestions[-1]['description']}\n\n"
            "Start with a flexible category rather than skipping a bill. I have not changed any budget or canceled anything."
        )
        return result(
            reply,
            "insights",
            [
                source(
                    "Last complete month",
                    f"{period.start} to {period.end}; expense transactions, transfers excluded.",
                ),
                source("Savings coverage", suggestions[-1]["evidence"][1]),
            ],
            [
                "Compare my groceries spending this month with the previous period.",
                "How can I build a stronger emergency fund?",
                "Show my subscriptions spending last month.",
            ],
        )

    if any(
        w in low
        for w in (
            "pay first",
            "what should i pay",
            "which bill",
            "payment plan",
            "bill plan",
            "bill payment plan",
            "priorit",
            "what to pay",
            "pay my bills",
        )
    ):
        plan = payment_plan(account, reserve=float(account.preferences.get("reserve", 1000)))
        if not plan["payments"]:
            return result(
                "There isn't enough allocatable checking cash to cover a payment under the current reserve and bill rules. Lowering the reserve is a trade-off, not extra income. Consider asking providers about an extension before the due date.",
                "plan",
                [
                    source(
                        "Payment optimizer",
                        "Current checking, reserve, and open bill terms.",
                    )
                ],
            )
        lines = [
            f"• {p['bill']}: {f.money(p['amount'])} on {f._spoken_date(p['date'])}"
            for p in plan["payments"]
        ]
        reply = (
            "Here's what I'd pay first, using recorded due dates and bill consequences:\n\n"
            + "\n".join(lines)
        )
        reply += f"\n\nThe plan allocates {f.money(plan['allocated'])}, leaving {f.money(plan['remaining'])} in checking, including the {f.money(plan['reserve'])} reserve. "
        reply += (
            "All open bills can be covered."
            if plan["unpaid"] < 0.01
            else f"{f.money(plan['unpaid'])} remains uncovered. Contact the relevant providers rather than assuming late payment is harmless."
        )
        reply += f" Modeled late fees and interest: {f.money(plan['late_fees'] + plan['interest'])}.\n\nSavings and unconfirmed income are excluded. This is a preview, not a scheduled or recorded payment."
        return result(
            reply,
            "plan",
            [
                source("Checking ledger", f.money(account.balance("Checking"))),
                source(
                    "Open bill terms",
                    f"{len(f.current_open_bills(account))} obligations; minimum and non-partial-payment rules enforced.",
                ),
                source(
                    "SciPy optimizer",
                    "Dated cash constraints; consequence weights are not monetary fees.",
                ),
            ],
            [
                "Why?",
                "What if my paycheck is 5 days late?",
                "Can I afford a $200 purchase?",
            ],
        )

    if any(
        w in low
        for w in (
            "how am i doing",
            "how i'm doing",
            "health",
            "financial health",
            "financial situation",
            "how are my finances",
            "how are my finances looking",
            "okay financially",
            "ok financially",
            "doing financially",
            "financial score",
            "my score",
            "am i okay",
            "am i ok",
            "overview",
            "summarize",
            "summary",
        )
    ):
        score, factors = f.health_assessment(account)
        weakest = factors.sort_values("component_score_0_100").iloc[0].factor
        coverage = account.balance("Savings") / max(f.essential_monthly_expense(account), 1)
        reply = (
            f"Your modeled financial health score is {score} out of 100—not a credit score.\n\n"
            f"• Checking: {f.money(account.balance('Checking'))}\n• Savings: {f.money(account.balance('Savings'))}, about {coverage:.1f} months of essentials\n"
            f"• Recorded debt: {f.money(sum(account.debts().values()))}\n\n"
            f"The weakest modeled factor is {weakest.lower()}. The score combines seven weighted account-history factors and is only as complete as this fictional account."
        )
        return result(
            reply,
            "health",
            [
                source(
                    "Health model",
                    "Seven weighted factors: income stability, positive cash flow, income/expense balance, emergency savings, debt/income, on-time bills, and savings trend. Income factors use completed months; upcoming and partial bills are excluded from on-time payment history.",
                )
            ],
            [
                "How can I build a stronger emergency fund?",
                "Where can I cut back?",
                "Build my bill payment plan.",
            ],
        )

    if any(
        w in low
        for w in (
            "what should i do",
            "what do i do",
            "what should i prioritize",
            "give me advice",
            "financial advice",
            "help me manage my money",
            "how do i improve my finances",
            "how to improve my financial situation",
            "where should i start",
            "what to do first",
            "financial guidance",
            "financial tips",
            "manage my money",
            "advice for me",
        )
    ):
        t = financial_trouble(account)
        rank = t["rank"]
        label = t["label"]
        checking = account.balance("Checking")
        savings = account.balance("Savings")
        overdue = [b for b in account.bills if b.status != "Paid" and b.effective_due < f.AS_OF]
        if rank == 1:
            steps = (
                f"1. Handle immediate arrears: You have {len(overdue)} overdue bills totaling {f.money(sum(b.amount for b in overdue))} (including essential rent/utilities). Contact providers immediately to request hardship arrangements before penalties or disconnection escalate.\n"
                f"2. Guard survival cash: With {f.money(checking)} in checking, conserve every dollar for food and critical medicine.\n"
                f"3. Halt non-essential spending: Pause discretionary purchases until essential shelter and utility obligations are stabilized."
            )
        elif rank == 2:
            steps = (
                f"1. Pay overdue essentials: Bring past-due utilities current to protect vital services.\n"
                f"2. Coordinate with your next paycheck: Plan bill payments around your upcoming payday to avoid cash shortfalls.\n"
                f"3. Reduce discretionary spending: Trim flexible dining and shopping to rebuild a safe buffer."
            )
        elif rank == 3:
            steps = (
                f"1. Buffer irregular cash flow: Keep at least 1–2 months of essentials in cash to weather freelance income gaps.\n"
                f"2. Tackle high-interest debt: Target credit card balances using the debt avalanche method to reduce monthly interest charges.\n"
                f"3. Track invoice payments: Keep expected client receipts organized to anticipate low-income weeks."
            )
        else:
            steps = (
                f"1. Pay down high-interest credit card debt: You have strong cash reserves ({f.money(checking)} checking, {f.money(savings)} savings). Paying off credit card debt will eliminate recurring finance charges.\n"
                f"2. Maintain emergency savings: Your savings covers {savings / max(f.essential_monthly_expense(account), 1):.1f} months of essentials; keep aiming for 3–6 months.\n"
                f"3. Put excess cash to work: Once high-APR debt is cleared, consider high-yield savings or retirement accounts."
            )
        reply = (
            f"Here is a prioritized financial plan based on your current status ({label}, priority {rank} of 4, {t['score']}/100 pressure points):\n\n"
            f"{steps}\n\n"
            "This guidance is grounded in your demo account's recorded balances and bill terms. Nothing was scheduled or changed."
        )
        return result(
            reply,
            "advice",
            [
                source("Financial triage", f"Priority {rank} ({label}), {t['score']}/100 pressure points."),
                source("Account balances", f"Checking {f.money(checking)}, savings {f.money(savings)}."),
            ],
            ["Build my bill payment plan.", "What bills are overdue?", "Can I afford a $200 purchase?"],
        )

    if any(
        w in low
        for w in (
            "where does my money go",
            "where did my money go",
            "where is my money going",
            "cash flow",
            "how is my cash flow",
            "spending breakdown",
            "expense breakdown",
            "monthly expenses",
            "how much do i spend each month",
            "what do i spend each month",
            "breakdown of my spending",
        )
    ):
        p_last = reporting_period("last_month")
        t_last = totals(account, p_last)
        df_cat = f.category_spending(account, p_last.start, p_last.end)
        top_cats = df_cat.head(5)
        lines = [
            f"• {r.category}: {f.money(r.spending)} ({r.spending / max(t_last['spending'], 0.01) * 100:.1f}%)"
            for r in top_cats.itertuples()
        ]
        reply = (
            f"In {p_last.label}, your recorded income was {f.money(t_last['income'])} and total spending was {f.money(t_last['spending'])}, for a net cash flow of {'+' if t_last['net'] >= 0 else ''}{f.money(t_last['net'])}.\n\n"
            f"Top spending categories:\n"
            + "\n".join(lines)
            + "\n\nTransfers between your own checking and savings accounts are excluded from spending."
        )
        return result(
            reply,
            "spending",
            [source(f"Recorded cash flow ({p_last.label})", f"Income {f.money(t_last['income'])}, spending {f.money(t_last['spending'])}.")],
            ["What is my biggest expense?", "Where can I cut back?", "How much did I spend on groceries last month?"],
        )

    if re.search(r"\b(?:subscriptions?|recurring (?:expenses?|charges?|bills?|costs?))\b", low):
        p_last = reporting_period("last_month")
        tx = account.transactions
        sub_tx = tx.loc[(tx.date.dt.date >= p_last.start) & (tx.date.dt.date <= p_last.end) & (tx.category.eq("Subscriptions"))]
        rec_bills = [
            b for b in account.bills
            if b.category in ("Utilities", "Subscriptions") or any(k in b.name.lower() for k in ("phone", "internet", "streaming", "bundle"))
        ]
        sub_total = float(-sub_tx.amount.sum()) if not sub_tx.empty else 0.0
        lines = [f"• {r.merchant}: {f.money(abs(r.amount))} ({r.description})" for r in sub_tx.itertuples()]
        bill_lines = [f"• {b.name} ({b.provider}): {f.money(b.amount)}, due {f._spoken_date(b.effective_due)}" for b in rec_bills]
        reply = "Here are your recorded subscriptions and recurring services:\n\n"
        if lines:
            reply += f"Monthly subscriptions ({f.money(sub_total)}/month):\n" + "\n".join(lines) + "\n\n"
        if bill_lines:
            reply += "Recurring service bills:\n" + "\n".join(bill_lines) + "\n\n"
        if not lines and not bill_lines:
            reply += "No subscription charges are recorded in this account.\n\n"
        reply += "Reviewing and canceling unused subscriptions is an easy way to free up monthly cash."
        return result(
            reply,
            "subscriptions",
            [source("Transaction ledger", f"Category Subscriptions in {p_last.label}"), source("Bill register", f"{len(rec_bills)} recurring service bills")],
            ["Where can I cut back?", "How much did I spend on dining out last month?", "What bills are due this week?"],
        )

    if re.search(r"\b(?:biggest|largest|highest|top|most expensive)\s+(?:expense|spending|bill|cost|category|outflow)\b|\bwhere (?:do|am) i spend(?:ing)? the most\b", low):
        p_last = reporting_period("last_month")
        df_cat = f.category_spending(account, p_last.start, p_last.end)
        top_cat = df_cat.iloc[0] if not df_cat.empty else None
        bills_sorted = sorted(account.bills, key=lambda b: b.amount, reverse=True)
        largest_bill = bills_sorted[0] if bills_sorted else None
        reply = (
            f"Your largest spending category in {p_last.label} was {top_cat.category} at {f.money(top_cat.spending)}."
            + (f" Your single largest open bill is {largest_bill.name} from {largest_bill.provider} ({f.money(largest_bill.amount)})." if largest_bill else "")
            + f"\n\nAcross categories in {p_last.label}:\n"
            + "\n".join(f"• {r.category}: {f.money(r.spending)}" for r in df_cat.head(4).itertuples())
        )
        return result(
            reply,
            "spending",
            [source(f"Category breakdown ({p_last.label})", f"Top category: {top_cat.category if top_cat is not None else 'None'}")],
            ["Where can I cut back?", "Where does my money go?", "Build my bill payment plan."],
        )

    if "emergency fund" in low and any(w in low for w in ("what is", "explain", "how does", "meaning", "definition", "purpose")):
        monthly = f.essential_monthly_expense(account)
        savings = account.balance("Savings")
        months = savings / max(monthly, 1)
        reply = (
            f"An emergency fund is money kept in a liquid, easily accessible savings account to protect against unexpected life events (like medical emergencies, car breakdowns, or job loss).\n\n"
            f"• Guideline: Most financial planners recommend keeping 3 to 6 months of essential living expenses.\n"
            f"• Your numbers: Essential living expenses are about {f.money(monthly)}/month. Your savings balance of {f.money(savings)} covers about {months:.1f} months of essentials.\n\n"
            "An emergency buffer keeps you from needing high-interest credit cards or loans when surprises happen."
        )
        return result(
            reply,
            "education",
            [source("Savings ledger", f.money(savings)), source("Essential expenses", f"{f.money(monthly)}/month")],
            ["How can I build a stronger emergency fund?", "Where can I cut back?"],
        )

    if "apr" in low and any(w in low for w in ("what is", "explain", "how does", "meaning", "definition")):
        debts = account.debts()
        reply = (
            "APR stands for Annual Percentage Rate. It is the yearly cost of borrowing money, including interest and fees, expressed as a percentage.\n\n"
            "• Why it matters: A higher APR means debt grows faster if balances are not paid in full each month. For example, a 20% APR on a $2,000 credit card balance costs roughly $33/month in interest alone.\n"
            f"• Your recorded debt: You currently have {f.money(sum(debts.values()))} in recorded debt across {len(debts)} accounts. Prioritizing payments on high-APR accounts saves the most money over time."
        )
        return result(
            reply,
            "education",
            [source("Debt ledger", f"Snapshot {f.AS_OF}")],
            ["What is my total debt?", "What should I pay first?"],
        )

    if "50/30/20" in low or "50 30 20" in low:
        period = reporting_period("last_month")
        income = totals(account, period)["income"]
        reply = (
            "The 50/30/20 rule is a popular budgeting framework:\n\n"
            "• 50% for Needs: Rent, groceries, utilities, debt minimums, and insurance.\n"
            "• 30% for Wants: Dining out, hobbies, shopping, and entertainment.\n"
            "• 20% for Savings & Extra Debt: Emergency fund, retirement, and accelerated debt payoff.\n\n"
            f"Based on your last month's income ({f.money(income)}), that allocation would be:\n"
            f"• Needs (50%): {f.money(income * 0.50)}\n"
            f"• Wants (30%): {f.money(income * 0.30)}\n"
            f"• Savings/Debt (20%): {f.money(income * 0.20)}"
        )
        return result(
            reply,
            "education",
            [source("Last month's income", f.money(income))],
            ["Where can I cut back?", "How much did I spend on groceries last month?"],
        )

    if any(
        w in low
        for w in (
            "bills due",
            "bills are overdue",
            "overdue bills",
            "due this week",
            "upcoming",
            "due soon",
            "what's due",
            "what is due",
            "next bill",
            "coming up",
            "two weeks",
            "my bills",
            "what bills",
        )
    ):
        days_match = re.search(r"(?:next|within|in)\s+(\d+)\s*days?", low)
        horizon = (
            int(days_match.group(1))
            if days_match
            else (
                14
                if any(
                    w in low
                    for w in (
                        "two weeks",
                        "2 weeks",
                        "upcoming",
                        "coming up",
                        "my bills",
                    )
                )
                else 7
            )
        )
        window = f.current_open_bills(account, min(horizon, 365))
        overdue_only = "overdue" in low
        if overdue_only:
            window = [b for b in window if b.effective_due < f.AS_OF]
        reply = (
            (
                "No overdue bills are recorded."
                if overdue_only
                else f"Nothing is due in the next {horizon} days."
            )
            if not window
            else f"You have {len(window)} {'overdue bills' if overdue_only else f'bills due in the next {horizon} days (including any overdue)'}, totaling {f.money(sum(b.amount for b in window))}:\n\n"
            + "\n".join(
                f"• {b.name}: {f.money(b.amount)}, due {f._spoken_date(b.effective_due)}"
                for b in window
            )
        )
        return result(
            reply,
            "bills",
            [
                source(
                    "Open bill register",
                    f"Unpaid bills through {f._spoken_date(f.AS_OF + dt.timedelta(days=min(horizon, 365)))}.",
                )
            ],
            [
                "Build my bill payment plan.",
                "When is rent due?",
                "What if I pay electricity 5 days late?",
            ],
        )

    if any(w in low for w in ("transactions", "purchases")) and any(
        w in low for w in ("show", "list", "recent", "last")
    ):
        period = (
            period_for(q)
            if any(w in low for w in ("month", "week", "days", "from", "since"))
            else reporting_period("90days")
        )
        tx = account.transactions
        tx = tx.loc[(tx.date.dt.date >= period.start) & (tx.date.dt.date <= period.end)]
        categories = category_for(q)
        if categories:
            tx = tx.loc[tx.category.isin(categories)]
        count_match = re.search(r"(?:last|recent)\s+(\d+)", low)
        count = min(10, max(1, int(count_match.group(1)))) if count_match else 5
        recent = tx.sort_values(["date", "transaction_id"], ascending=False).head(count)
        reply = (
            f"Here are {len(recent)} recent matching transactions in {period.label}:\n\n"
            + "\n".join(
                f"• {f._spoken_date(r.date)} — {r.merchant}: {'+' if r.amount > 0 else '-'}{f.money(abs(r.amount))} ({r.category})"
                for r in recent.itertuples()
            )
        )
        if recent.empty:
            reply = "No matching transactions are recorded in that period. Try a wider reporting window."
        return result(
            reply,
            "transactions",
            [
                source(
                    "Transaction ledger",
                    f"{period.start} to {period.end}. Amounts are signed inflows or outflows.",
                )
            ],
            ["How much did I spend last month?", "What about groceries?"],
            context_question=q,
        )
    spend_intent = any(
        w in low
        for w in (
            "spend",
            "spent",
            "expenses",
            "grocer",
            "transactions",
            "purchases",
            "compar",
        )
    )
    if spend_intent:
        return spending_answer(q, account, last)
    if bill and not any(w in low for w in ("owe", "debt", "balance")):
        days = (bill.effective_due - f.AS_OF).days
        status = (
            "It's already paid."
            if bill.status == "Paid"
            else (
                f"That's in {days} days."
                if days > 0
                else "It is due today."
                if not days
                else f"It is {-days} days overdue."
            )
        )
        minimum = (
            f" Recorded minimum: {f.money(bill.minimum_payment)}."
            if bill.minimum_payment and bill.minimum_payment < bill.amount
            else ""
        )
        return result(
            f"Your {bill.name} bill from {bill.provider} is {f.money(bill.amount)}, due {f._spoken_date(bill.effective_due)}. {status}{minimum}",
            "bills",
            [source("Bill register", f"{bill.provider}; {bill.status.lower()}.")],
            ["Build my bill payment plan.", f"What if I pay {bill.name} 5 days late?"],
        )
    if "net worth" in low:
        cash = account.balance("Checking") + account.balance("Savings")
        debt = sum(account.debts().values())
        return result(
            f"Cash minus recorded debt is {f.money(cash - debt)}: {f.money(cash)} in checking and savings, less {f.money(debt)} of debt. This is not a full net-worth statement; property, investments, and other assets or liabilities are not recorded.",
            "balance",
            [source("Cash ledgers and debt history", f"Snapshot {f.AS_OF}.")],
        )
    if any(w in low for w in ("debt", "owe", "loan", "credit card balance")):
        debts = account.debts()
        return result(
            f"You owe about ${sum(debts.values()):,.0f} in total:\n\n"
            + "\n".join(f"• {k}: {f.money(v)}" for k, v in debts.items())
            + "\n\nThese are recorded balances. A bill's required payment is not the same as the total loan balance.",
            "debt",
            [source("Debt history", f"Latest modeled balances at {f.AS_OF}.")],
            ["How much is my credit card bill?", "Build my bill payment plan."],
        )
    if any(
        w in low
        for w in (
            "balance",
            "checking",
            "savings",
            "how much money",
            "how much cash",
            "how much do i have",
            "how much in checking",
            "how much in savings",
            "how much is in checking",
            "how much is in savings",
            "available funds",
            "available money",
            "cash on hand",
            "account total",
            "total cash",
            "my accounts",
            "what are my accounts",
            "list my accounts",
            "show my accounts",
            "in the bank",
            "where is my money",
            "where's my money",
            "financial position",
            "financial snapshot",
        )
    ):
        checking, savings = account.balance("Checking"), account.balance("Savings")
        debts = account.debts()
        debt_total = sum(debts.values())
        names = [name for name in ("Checking", "Savings") if name.lower() in low]
        if len(names) == 1 and not any(k in low for k in ("all", "both", "total", "accounts", "bank", "money", "cash")):
            reply = f"Your {names[0].lower()} balance is {f.money(account.balance(names[0]))}."
        else:
            reply = (
                f"You have {f.money(checking)} in checking and {f.money(savings)} in savings, giving you {f.money(checking + savings)} in total liquid cash.\n\n"
                f"• Checking account: {f.money(checking)} (for everyday spending and bill payments)\n"
                f"• Savings account: {f.money(savings)} (emergency reserve cushion)\n"
                f"• Recorded debt: {f.money(debt_total)} across {len(debts)} debt accounts\n"
                f"• Net cash position (cash minus debt): {f.money(checking + savings - debt_total)}"
            )
        return result(
            reply,
            "balance",
            [
                source(
                    "Account ledgers",
                    f"Opening balances plus signed transactions through {f.AS_OF}; debt not included in cash.",
                )
            ],
            [
                "Can I afford a $200 purchase?",
                "What bills are due this week?",
                "What is my total debt?",
            ],
        )
    if any(
        w in low
        for w in (
            "income",
            "paycheck",
            "payday",
            "paid next",
            "when do i get paid",
            "when was i paid",
            "when am i paid",
            "next paycheck",
            "last paycheck",
            "how much do i make",
            "how much did i make",
            "how much do i earn",
            "how much did i earn",
            "what did i earn",
            "what do i earn",
            "what is my salary",
            "what's my salary",
            "my earnings",
            "my salary",
            "take home pay",
            "my income",
            "monthly income",
            "annual income",
            "when do i get my money",
            "paid last",
            "how much i made",
            "who is my employer",
            "my employer",
        )
    ):
        period = (
            period_for(q)
            if any(w in low for w in ("month", "days", "week", "year"))
            else reporting_period("90days")
        )
        amount = totals(account, period)["income"]
        paycheck_val = float(account.preferences.get("paycheck", 2200))
        payday_val = account.preferences.get("payday", f.AS_OF)
        if isinstance(payday_val, str):
            payday_val = dt.date.fromisoformat(payday_val)

        income_tx = account.transactions.loc[account.transactions.category.eq("Income")]
        employer = income_tx.merchant.iloc[-1] if not income_tx.empty else "Primary employer"
        last_month = totals(account, reporting_period("last_month"))["income"]

        reply = (
            f"Your next paycheck of about {f.money(paycheck_val)} is expected around {f._spoken_date(payday_val)}.\n\n"
            f"• Employer / deposit source: {employer}\n"
            f"• Recorded income in {period.label}: {f.money(amount)}\n"
            f"• Last complete month (October 2026): {f.money(last_month)}\n\n"
            "Future paychecks are unconfirmed demo planning estimates and are not counted as available checking cash until confirmed."
        )
        return result(
            reply,
            "income",
            [
                source("Income transactions", f"{period.start} to {period.end}; employer {employer}."),
                source("Expected paycheck", f"{f.money(paycheck_val)} scheduled for {payday_val}."),
            ],
            ["What if my paycheck is 5 days late?", "Can I afford a $200 purchase?", "Where does my money go?"],
        )

    FINANCIAL_KEYWORDS = {
        "money", "cash", "dollar", "dollars", "buck", "bucks", "cent", "cents",
        "pay", "paid", "paying", "paycheck", "payday", "salary", "wage", "wages", "earn", "earned", "earning", "income",
        "checking", "savings", "account", "accounts", "balance", "balances", "bank",
        "debt", "debts", "loan", "loans", "owe", "owed", "owing", "credit", "apr", "interest",
        "bill", "bills", "due", "overdue", "rent", "utility", "utilities", "electric", "electricity", "water", "gas",
        "groceries", "grocery", "food", "dining", "restaurant", "shopping", "transport", "transportation",
        "spend", "spent", "spending", "expense", "expenses", "cost", "costs", "purchase", "purchases", "buy", "buying",
        "afford", "affordable", "headroom", "budget", "budgeting", "financial", "finances", "finance",
        "transaction", "transactions", "receipt", "subscription", "subscriptions", "recurring",
        "net worth", "trouble", "score", "health", "priority", "prioritize", "triage", "plan", "planner",
        "cut back", "save", "saving", "savings", "emergency fund", "advice", "invest", "investing",
        "maya", "jordan", "aisha", "marcus"
    }
    words = set(re.findall(r"[a-z0-9]+", low))
    has_finance = bool(words & FINANCIAL_KEYWORDS) or any(phrase in low for phrase in ("how am i", "where does my", "can i get", "what do i have", "how are my", "what are my", "help me"))

    if not has_finance:
        return result(
            "I'm not sure about that one. I can only help with personal-finance questions using this demo's account data. I can compare spending by category or month, check affordability, explain bills, preview late payments, and record changes after confirmation.\n\nTry a specific question, such as “How much did I spend on groceries last month?”",
            "help",
        )

    checking = account.balance("Checking")
    savings = account.balance("Savings")
    bills = f.current_open_bills(account, 14)
    buffer = planning_buffer(account)
    t = financial_trouble(account)
    return result(
        f"Here is your current financial summary to help with your question:\n\n"
        f"• Checking: {f.money(checking)} | Savings: {f.money(savings)}\n"
        f"• Open bills: {len(bills)} due in the next 14 days totaling {f.money(sum(b.amount for b in bills))}\n"
        f"• 30-day spending room (headroom): {f.money(max(0, buffer['headroom']))}\n"
        f"• Financial status: {t['label']} (priority {t['rank']} of 4, {t['score']}/100 pressure points)\n\n"
        "Try asking about a specific topic, such as:\n"
        "• “How much did I spend on groceries last month?”\n"
        "• “Can I afford a $200 purchase?”\n"
        "• “What bills are due this week?”\n"
        "• “Where does my money go?”\n"
        "• “What should I pay first?”",
        "help",
        [source("Account snapshot", f"Ledger through {f.AS_OF}")],
        [
            "What bills are due this week?",
            "Can I afford a $200 purchase?",
            "Where does my money go?",
        ],
    )


def conversation_turn(
    text: str,
    pending: dict | None,
    last_question: str,
    account: f.AccountStore,
    history: list | None = None,
) -> dict[str, Any]:
    q = normalize(text)
    low = q.lower().strip(" .!?")
    changed = end = False
    if not low:
        res = result(
            "I didn't catch any words. Check the live caption, then try again—or type your question.",
            "help",
            pending=pending,
        )
    elif (
        pending
        and f._short_reply_matches(low, f._YES_WORDS, f._YES_STARTERS)
        and not f._short_reply_matches(low, f._NO_WORDS, f._NO_STARTERS)
    ):
        with account.lock:
            reply = f.confirm_account_update(pending, True, account)
        changed = reply.startswith("Done")
        res = result(
            reply,
            "update",
            [
                source(
                    "Confirmed demo change",
                    "Recorded only in this session; no money moved.",
                )
            ],
        )
    elif pending and f._short_reply_matches(low, f._NO_WORDS, f._NO_STARTERS):
        res = result(f.confirm_account_update(pending, False, account), "update")
    elif low in f._GREETINGS:
        res = result(
            f"Hi! I'm Solvra. I can help make sense of your money. Your checking balance is {f.money(account.balance('Checking'))}. Ask what to pay first, compare spending, or check whether a purchase fits your plan.",
            "greeting",
            pending=pending,
        )
    elif low in f._GOODBYES:
        res = result(
            "Goodbye! Voice is stopped. Your conversation will stay here for this session.",
            "goodbye",
            pending=pending,
        )
        end = True
    elif re.fullmatch(
        r"(?:thanks|thank you|thank you so much|thanks a lot|cool|great|awesome|perfect|got it)(?: solvra)?",
        low,
    ):
        res = result(
            "You're welcome. What else would you like to work through?",
            "greeting",
            pending=pending,
        )
    elif re.search(
        r"\b(what can you do|what can i ask|what do you do|^help$|how does this work|who are you)\b",
        low,
    ):
        res = result(
            "I'm Solvra, an account-grounded money assistant. Ask what to pay first, compare groceries between months, check a purchase against a 30-day buffer, or preview a late payment. I can record income or a bill you've already paid, but only after you confirm.\n\nConnect Grok AI in the assistant panel for broader finance-only guidance. Without that optional connection, the local financial engine still provides account calculations and confirmations. It uses fictional account data and cannot access your bank or make payments.",
            "help",
            pending=pending,
        )
    elif not pending and f._short_reply_matches(
        low, f._YES_WORDS | f._NO_WORDS, f._YES_STARTERS | f._NO_STARTERS
    ):
        res = result(
            "There's no pending change to confirm. What would you like to check?",
            "help",
        )
    else:
        context = [{"role": "user", "content": last_question}] if last_question else history or []
        res = answer_question(q, account, context)
        if pending:
            if res.get("pending") and res["pending"] != pending:
                res["reply"] = (
                    "Please confirm or cancel the existing change before recording a different one. Nothing has changed."
                )
                res["pending"] = pending
            elif not res.get("pending"):
                res["pending"] = pending
    res.update({"speech": f.speech_text(res["reply"]), "changed": changed, "end": end})
    if "context_question" not in res:
        is_followup = bool(
            re.fullmatch(
                r"(?:why|why is that|explain that|how so|tell me more|explain the order)\??",
                low,
            )
        )
        res["context_question"] = (
            last_question
            if is_followup or res["intent"] in {"greeting", "update", "help", "goodbye"}
            else q
        )
    return res
