# Solvra

**Track:** AI + Finance

**Team:** Henit Jain

## The problem

Households juggling tight cash flow, irregular paychecks, or unexpected expenses often struggle to tell which bills are most urgent and how much safe spending room they actually have before fees or service disruptions hit. Standard banking apps list past transactions without modeling future cash constraints, while generic AI chatbots lack grounded ledger math and can hallucinate balances or unsafe financial advice. Understanding true financial urgency and building a realistic bill-payment plan matters because a single mistimed payment can trigger avoidable late fees, high-interest debt, or housing and utility instability.

## What we built

Solvra is an interactive, voice-enabled financial triage workspace and account-grounded assistant backed by deterministic household ledgers (`solvra_app.py` locally or via `Solvra_Financial_Triage.ipynb` in Google Colab).

- **What goes in:** A user selects one of four fictional demo households (ranging from stable cash cushion to critical overdue rent and utilities), sets cash-reserve or expected-paycheck preferences, and asks typed or spoken financial questions, tests "what-if" late-payment scenarios, or stages new deposits/payments.
- **What comes out:**
  - An explainable **0–100 financial-trouble ranking** (**Priority 1 Critical** to **Priority 4 Stable**) with transparent factor rules, evidence, and safety floors, alongside a 7-factor financial-health score.
  - A constrained **bill-payment schedule** minimizing late fees, interest accrual, and consequence risk while respecting cash-by-date availability, minimum payments, and full-payment-only rules.
  - A **scikit-learn savings-category classifier** that ranks an expense category to review, trained and evaluated on generated synthetic monthly budgets. Its score measures agreement with synthetic heuristic labels, not real-world savings.
  - **Sourced text and neural read-aloud answers**, plus an interactive **AI Guardrails** monitor that blocks off-topic, cross-account, or prompt-injection requests before any data is shared.
- **How someone uses it:** Run `python solvra_app.py` (or open the self-contained Colab notebook), log into a fictional profile from the demo picker, explore cash flow and triage factors in **Overview** and **Insights**, generate a dated payment plan in **Bills & payments**, or click **Ask by voice** in **Assistant** to talk through decisions using either the local deterministic engine or optional consented Grok AI.

## How it works

**Data:**
We built a deterministic, seeded synthetic ledger generator (`RNG_SEED = 271828`, snapshot date November 14, 2026) spanning **4 fictional household scenarios** and **1,643 total reconciled transactions** across Checking, Savings, and Credit Card accounts:
- **Maya Chen** (897 transactions, 24-month history · *Stable, 4/100*), **Jordan Reyes** (249 transactions, irregular freelance income · *Watch, 22/100*), **Aisha Patel** (255 transactions, tight budget & overdue utility · *High, 64/100*), and **Marcus Bennett** (242 transactions, reduced shifts, car repair & overdue rent · *Critical, 98/100*).
- **Cleaning & normalization:** Every profile reconciles opening balances plus signed transactions to exact monthly snapshots without unrecorded overdrafts. Internal account transfers are excluded from spending totals, partial-month views (November 1–14) compare against equal prior-month day windows rather than full completed months, duplicate bill-payment audit rows are deduplicated to latest settlement state, and spoken/uploaded audio is resampled to 16 kHz mono with leading/trailing silence trimmed and bounded to 45 seconds / 15 MB.
- **Savings-classifier training data:** A separate, reproducible dataset of 4,000 synthetic monthly-budget profiles is generated in `solvra_savings_model.py`. Target categories are assigned by a documented hypothetical-headroom heuristic; these are not observed household decisions or records from an external public dataset. Rows with missing selected features/labels are dropped before model fitting.

**Model:**
Solvra uses a hybrid neuro-symbolic architecture so arithmetic and account mutations remain exact while open-ended guidance stays conversational:
- **Triage & Optimization (Deterministic Core):** A 6-factor rules-based triage engine (`Triage v1`) with explicit safety floors for overdue essentials/housing, paired with a **SciPy Mixed-Integer Linear Programming (`scipy.optimize.milp`)** two-pass optimizer that minimizes late fees, daily APR interest, and consequence risk under strict cash-by-date constraints.
- **Conversational AI (`x-ai/grok-4-1-fast-non-reasoning` via Puter.js):** Chosen for low-latency, structured JSON financial guidance without requiring backend API keys. A two-stage topic gate checks scope before sharing bounded account summaries, and the LLM has zero action/mutation tools—every ledger update requires server-enforced confirmation.
- **Savings-category classifier:** A `RandomForestClassifier` uses monthly income and expense-category amounts to choose a category to review. The synthetic target is the category with the largest heuristic potential; for the displayed account, the classifier ranks the selected fictional profile's last-90-day category spending.
- **Speech Pipeline:** Browser Web Speech API with finance phrase biasing and automatic fallback to bundled offline **PocketSphinx** (plus optional local **Faster-Whisper**), paired with local **Kokoro-82M ONNX** (`kokoro-onnx`) neural text-to-speech so financial replies are read aloud naturally on CPU without sending text to external speech APIs.

## Results

Solvra combines decision-support, optimization, a supervised savings-category experiment, and a guarded assistant. We evaluated the ML experiment on held-out synthetic profiles and the other components against baseline heuristics and held-out test scenarios across our automated regression suite (`test_solvra_app.py` and `tests/`):

- **Savings-category classifier:** With a fixed seed, the model achieved **91.5% top-category accuracy** on 1,000 held-out synthetic profiles, versus a **12.5% expected hit rate** for an equal-allocation baseline across eight categories (3,000 training profiles). This measures agreement with the generated heuristic labels only. It does not establish real-user accuracy, genuine savings, or financial benefit; the suggested dollar headroom is also a rule-based estimate, not a forecast.

- **Financial Triage Ranking:** A naive raw weighted-sum baseline can mask urgent crises when a household still holds savings or steady past income (scoring below the 40-point High or 70-point Critical threshold despite an overdue essential or post-grace-period rent shortfall). Our **Triage v1 model with explicit safety floors** achieved **4/4 (100%) exact priority-band alignment** across all four household scenarios (`Stable 4/100`, `Watch 22/100`, `High 64/100`, `Critical 98/100`) and passed **100% of held-out edge-case stress tests** (such as overdue rent beyond grace period with insufficient checking cash).
- **Bill Payment Optimizer:** Compared to a single-pass harm-minimization baseline (which leaves affordable $0-late-fee subscriptions unpaid because their objective weight is zero) or chronological due-date paying (which exhausts cash before high-consequence housing/utility bills), our **two-pass lexicographic MILP** achieved **0 cash-overdraft violations** across tight-cash, minimum-payment, and all-or-nothing bill constraints while maximizing secondary bill coverage at optimal minimum harm.
- **Guardrail & Scope Gate:** Against our adversarial and scope test set (prompt overrides, SQL-like injection, cross-account queries, role spoofing, unapproved transfers, off-topic prompts, and valid finance typos), the local fail-closed guardrail monitor and two-stage AI gate blocked **100% of unsafe/off-topic test prompts** before sharing account context while preserving read-only finance guidance.

**Where it fails, and why we think so:**
- **Offline speech recognition on noisy or accented audio:** When browser speech recognition is unavailable, the bundled PocketSphinx fallback has a noticeably higher word-error rate on open-ended financial phrasing because it uses a lightweight phoneme/statistical acoustic model rather than a large neural transformer (unless Faster-Whisper is locally configured).
- **Nuanced local-only phrasing and strict keyword gating:** Without Grok AI connected, the local regex/intent engine handles core balance, spending, affordability, and what-if queries reliably, but fails on multi-goal life-planning trade-offs (e.g., Roth vs. traditional retirement allocation). Conversely, the offline guardrail monitor fails closed when a financial question uses unfamiliar phrasing outside its explicit finance vocabulary.
- **Simplified financial dynamics:** Synthetic ledgers and linear APR / consequence-weight models do not capture real-world compounding statements, variable minimum-payment formulas, tax withholding, or unrecorded cash obligations.

## What we'd do next

1. **Privacy-preserving real transaction ingestion & categorization:** Support user-uploaded bank/card CSV and OFX statements with local merchant normalization, recurring-bill detection, and uncertainty flags so people can run Solvra's triage and MILP bill planner on their own exported data without linking bank credentials.
2. **Multi-month stochastic cash-flow simulation & benchmarked voice/NLU:** Extend the 35–40 day deterministic MILP planner into a 3–6 month Monte Carlo cash-flow simulator for irregular earners (like Jordan), and bundle a quantized local Whisper + small local language model benchmarked on a larger held-out corpus of messy spoken financial queries.

## Sources

- **Datasets:** Deterministic synthetic household ledgers generated in-repo (`solvra_app.py`, `solvra_profiles.py` — 4 fictional profiles, 1,643 reconciled transactions) and 4,000 generated synthetic monthly-budget profiles for the savings classifier (`solvra_savings_model.py`). No external personal-finance dataset or consumer PII is used; the ML labels are generated by the documented heuristic.
- **Pretrained models:**
  - [Grok (`x-ai/grok-4-1-fast-non-reasoning`)](https://x.ai/) accessed client-side via [Puter.js (`@heyputer/puter.js@2.6.5`)](https://github.com/HeyPuter/puter/tree/main/src/puter-js)
  - [Kokoro-82M ONNX (`kokoro-onnx`, `kokoro-q8-shards@1.0.0`, `kokoro-js@1.2.1`)](https://github.com/thewh1teagle/kokoro-onnx) (Apache-2.0, local neural TTS)
  - [PocketSphinx (`pocketsphinx`)](https://github.com/cmusphinx/pocketsphinx) (bundled offline English ASR fallback)
  - [Faster-Whisper (`faster-whisper`)](https://github.com/SYSTRAN/faster-whisper) (optional local CTranslate2 Whisper ASR)
- **Libraries & frameworks:**
  - [SciPy (`scipy.optimize.milp`)](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html), [scikit-learn](https://scikit-learn.org/), [Pandas](https://pandas.pydata.org/), and [NumPy](https://numpy.org/) for ledger math, the synthetic savings classifier, and mixed-integer optimization
  - [Gradio](https://www.gradio.app/) for the web/Colab server transport, [PyAV](https://pyav.basswood-io.com/) for bounded audio decoding, and [num2words](https://github.com/savoirfairelinux/num2words) for exact spoken currency/dates
  - [DM Sans](https://fonts.google.com/specimen/DM+Sans) (bundled UI typography) and [Pytest](https://docs.pytest.org/) / [Playwright](https://playwright.dev/python/) for automated testing
- **Tutorials & AI tools:**
  - [Puter Grok API Tutorial](https://developer.puter.com/tutorials/free-unlimited-grok-api/) and [Puter User-Pays Usage Model Docs](https://docs.puter.com/user-pays-model/)
  - Built and iterated with AI-assisted coding on [Arena.ai](https://arena.ai/)
