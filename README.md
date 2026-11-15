# Solvra

**Solvra is a voice money assistant.** Tap **Speak live**, ask a question out loud, and Solvra answers out loud, then keeps listening, like a live voice chat. It works with a fictional household account: balances, upcoming bills, spending, debt, and a payment optimizer that suggests what to pay first when cash is tight.

> **This project is a prototype and is not financial advice.** Answers are estimates from demo data. Solvra never makes payments or contacts providers.

## What's on the page

There is one page and no tabs:

- **Live voice chat**: tap the big button once and talk. Solvra shows live captions while you speak, answers out loud when you pause, and then listens again. Tap the button while it's talking to interrupt. Tap **End live chat** to stop. You can also type a question or tap a suggestion.
- **Your money**: checking, savings, debt, the total due in the next 14 days, and the list of bills to pay. It updates when you make a change by voice.
- **Reset demo account**: puts the demo data back the way it started.

Things you can say:

- "How much money do I have?"
- "What bills are due this week?"
- "What should I pay first?" (then "Why?")
- "When is rent due?" / "How much is my phone bill?"
- "How much did I spend last month?" / "How much debt do I have?"
- "Am I okay financially?"
- "What if I pay electricity 5 days late?"
- "I got paid 500 dollars" or "I paid my internet bill". Solvra asks first; say **yes** to record it or **no** to cancel.

## Run it in Google Colab

1. Open [`Solvra_Financial_Triage.ipynb`](Solvra_Financial_Triage.ipynb) in Google Colab.
2. Run the cells from top to bottom. No paid API key is needed.
3. The last cell prints a public **https** link. Open it in Chrome, Edge, or Safari, allow the microphone, and tap **Speak live**.

Keep the Colab runtime running while you use the app.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python solvra_app.py
```

Open http://localhost:7860. The microphone works on `localhost` or on an `https` link. Browsers block it on plain `http://` addresses.

## How voice works

- **Chrome, Edge, and Safari** use the browser's built-in speech recognition, which gives fast, live captions. Answers are read aloud with the browser's built-in voice, so no audio files are made and no API key is needed.
- **Other browsers (like Firefox)** record what you say until you pause, then transcribe it on the server with Faster-Whisper. It downloads a small English model the first time.
- If the microphone is blocked, the app tells you how to allow it. Typing always works.

## How the optimizer works

"What should I pay first?" runs a SciPy `milp` model, not an LLM. It only spends cash that's available on each date, pays required minimums by their due dates, and pays bills that don't allow partial payments in full or not at all. It ranks bills by estimated late fees, interest, and serious consequences (such as losing a utility). These are modeled estimates, not quotes from providers.

The demo account is generated the same way every time. It has 897 transactions from November 2024 to November 2026.

## Tests

```bash
pytest -q
```

The tests cover the demo data, the optimizer's cash, minimum-payment and all-or-nothing rules, the what-if answers, the health score, confirmation before any account change, account reset, the voice conversation (yes/no confirmations, small talk, common questions), read-aloud text cleanup, and the one-page interface.

## Project files

- `solvra_app.py`: the app (demo data, optimizer, assistant, voice, and interface). Every function is used by the app.
- `Solvra_Financial_Triage.ipynb`: the same code split into Colab cells.
- `test_solvra_app.py`: automated tests.
- `requirements.txt`: Python dependencies.
