# Solvra

**Solvra is a financial decision-support prototype for people choosing among bills when cash is limited.** It combines a transparent consequence-based payment optimizer with a fictional, two-year household account, interactive financial analytics, what-if scenarios, document extraction, and optional voice interaction.

> **This project is a prototype and is not financial advice.** Recommendations are modeled estimates, not guarantees. Solvra does not make payments or contact providers.

## Run it in Google Colab

1. Open [`Solvra_Financial_Triage.ipynb`](Solvra_Financial_Triage.ipynb) in Google Colab.
2. Run the cells from top to bottom. The notebook installs the open-source dependencies; no paid API key is required.
3. Optionally run the Tesseract setup cell to enable OCR for image bills. Pasted text and text-based PDFs do not need Tesseract.
4. Review the synthetic account and held-out evaluation in the validation cell, then run **Launch Solvra**.
5. Open the Gradio share link. Keep the Colab runtime running while you use the app.

Faster-Whisper downloads its English model the first time you transcribe audio. gTTS requires internet access to create spoken responses. Voice is optional; the text interface, dashboard, optimizer, and reports work without it.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python solvra_app.py
```

Open the local Gradio URL shown in the terminal. Image OCR also requires the Tesseract system executable.

## What is included

- **Overview:** balance and cash-flow cards, six interactive charts, upcoming obligations, calculated insights, and a documented health index.
- **Transactions and bills:** historical ledger, payment history, add/edit/delete actions, partial payments, confirmed extensions, and document extraction with review before saving.
- **Financial situation:** planning inputs for available cash, a protected reserve, expected income and dates, and household context.
- **Smart prioritization:** SciPy mixed-integer allocation with dated cash constraints, minimum-payment deadlines, all-or-nothing bills, late-fee estimates, interest estimates, consequence weights, and explanations.
- **Simulations:** compare earliest due date, smallest bill first, largest bill first, and the optimizer using a shared scenario.
- **Assistant and voice:** structured answers grounded in the account, Faster-Whisper transcription, confirmation before financial updates, and gTTS playback.
- **Reports and evaluation:** separate personal reports and synthetic algorithm evaluation, with CSV and PDF exports where available.

The fictional account is generated deterministically once per process. It contains 897 ledger transactions from November 2024 through November 2026, with income, recurring bills, day-to-day spending, savings and debt history, and documented irregular events. Navigate between sections without regenerating the account. Use **Settings → Reset demo account** to restore the starting dataset.

## How the optimizer is modeled

The optimizer is a SciPy `milp` model—not an LLM. It limits cumulative payments to cash available on each date, adds expected income only on its entered arrival date, honors applicable minimum payments by their due dates, and uses one full payment for bills that do not allow partial payments. Only confirmed extensions change a bill's effective due date.

The objective estimates three kinds of harm: prorated late fees on unpaid balances, simple daily interest over the scenario horizon, and explicit dollar-equivalent weights for critical consequences. These values are assumptions for comparing plans; they are not quotes, legal conclusions, or real-world loss estimates. The interface exposes the weights and identifies uncertainty. If available funds cannot cover every obligation, the app returns an allocation and shows what remains unpaid rather than claiming a fully feasible outcome.

The benchmark generator creates 350 development scenarios and 150 held-out scenarios. Results are computed on the held-out set and labeled synthetic. They should not be interpreted as a prediction of performance for real households.

## Tests

```bash
pytest -q
```

The tests cover deterministic account generation and ledger balances, dated cash constraints, minimum payments, non-partial bills, baseline consistency, confirmed extensions, ambiguous document extraction, confirmation-before-update, dashboard date ranges and totals, report exports, the held-out evaluation split, and Gradio interface construction.

## Project files

- `Solvra_Financial_Triage.ipynb` — executable, cell-organized Colab application.
- `solvra_app.py` — same modular implementation for local use and testing.
- `test_solvra_app.py` — automated regression tests.
- `requirements.txt` — Python dependencies.
