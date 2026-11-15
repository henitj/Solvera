# Solvra

### Your money, in focus.

A financial workspace with a shared, ledger-backed view of checking, savings, spending, debt, and bills. Explore the numbers, build a payment plan, or talk a question through with the account-grounded assistant.

**Four fictional demo households · snapshot November 14, 2026 · not financial advice.** There is no bank connection. Solvra never sends, schedules, or transfers money and never contacts providers.

## Run locally

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python solvra_app.py
```

Open the printed URL, choose a person from the demo-login dropdown, then select **Log in to demo**. The server binds to `0.0.0.0` for remote previews; browser-to-server requests use Gradio's same-origin transport, not a hard-coded localhost URL. Port 7860 is preferred and an available port is selected automatically if it is occupied. To require a port:

```bash
GRADIO_SERVER_PORT=7861 python solvra_app.py
```

Microphone access requires **HTTPS or localhost**. If using an embedded preview, open the preview in its own browser tab when the parent page blocks microphone access.

## Demo login and distinct people

The landing page is an explicitly labeled **simulated login**. It takes no password or real identity. Pick a fictional person, inspect their story, then click **Log in to demo**. Selecting a name alone does not reveal the ledger. Logged-out financial endpoints also reject access; the login is not just a visual overlay.

| Fictional person | Scenario | Checking | Savings | Recorded debt | Starting financial pressure |
| --- | --- | ---: | ---: | ---: | --- |
| **Maya Chen** · operations analyst | Steady income, growing cash cushion; the original 897-entry account | $19,259.44 | $7,740.00 | $18,898.77 | **Stable · 4/100 · priority 4** |
| **Jordan Reyes** · freelance designer | Irregular client invoices, savings drawdowns and substantial student/card debt; 249 entries | $2,750.00 | $900.00 | $32,800.00 | **Watch · 22/100 · priority 3** |
| **Aisha Patel** · medical assistant and parent | Tight cash flow, a medical expense and overdue electricity; 255 entries | $980.00 | $2,100.00 | $16,700.00 | **High · 64/100 · priority 2** |
| **Marcus Bennett** · warehouse associate | Reduced shifts, a $920 car repair, overdue rent and utilities; 242 entries | $215.00 | $75.00 | $34,650.00 | **Critical · 98/100 · priority 1** |

These are independently seeded ledgers, not renamed copies: amounts, merchants, providers, pay dates, debt mix, bill terms, savings histories and planning preferences differ. Maya retains the original two-year fixture; the other profiles cover May–November 2026. Cash snapshots reconcile to opening balances plus signed transactions. Recurring rent due next month is included even when this month's rent is overdue.

Use **Settings → Log out** to return to the people dropdown. Logout revokes the active server token, cancels unconfirmed changes, stops capture/read-aloud, clears the visible account/draft/transcript, and disconnects consented AI sharing. Confirmed changes and chat remain **separate per person in this tab's in-memory demo workspace**. Logging back in restores that person's changes, not another person's conversation or pending confirmation. Refresh keeps the active login. **Reset demo account** restores only the selected person's own starting data.

This is **not production authentication or durable storage**. Anyone can choose a fictional profile; never put real finances into it. Fresh tabs receive separate demo workspaces; some browser duplicate-tab actions may copy session storage. Server restarts, inactivity expiry, or capacity eviction can discard all profiles in that workspace.

## What you can do

| Workspace | Useful actions |
| --- | --- |
| **Overview** | See the selected person and financial-trouble urgency; check balances, compare income/spending, switch cash-flow and balance charts, inspect categories, upcoming bills, and recent activity. |
| **Transactions** | Search merchants/descriptions, filter date/category/account/direction, paginate, inspect records, export filtered CSV, and record a confirmed checking expense or deposit. |
| **Bills & payments** | Inspect bill terms, choose a cash reserve, explicitly include/exclude an expected paycheck, calculate a payment preview, record an already-made payment after confirmation, and model a late payment. |
| **Insights** | Explain the trouble ranking with all factors, thresholds and safety floors. See account-derived spending patterns and savings coverage, inspect the evidence, explore the seven-factor health model, and ask relevant follow-ups. |
| **Assistant** | Ask typed or spoken questions. Answers include account sources, follow-up suggestions, reporting-window context, and separate confirmation controls for ledger changes. Download or clear the conversation. |

November is a **partial month**. Month-to-date comparisons use the same days of the previous month, not an entire completed month; rolling and multi-month windows use the full preceding equal-length window. Transfers are excluded from reported spending. Income-related health factors use completed months, and upcoming/partial bills are not counted as on-time payment history. Expected income is not presented as available checking cash.

## Voice: one tap, one clean turn

1. Tap **Ask by voice** in the assistant composer (or the microphone icon). Capture stays in that composer—there is no separate speaking popup.
2. In supported Chrome, Edge, and Safari versions, browser recognition waits for final words instead of placing partial captions in the text box. Indexed recognition segments replace revised results rather than append them, and adjacent repeated phrases are removed before the question is sent. Where the browser supports speech phrase bias, Solvra also supplies product, account, bill, and selected-person terms to improve recognition of finance-specific words; other browsers use their normal recognizer unchanged.
3. Pause or tap the microphone to finish. Solvra waits for a completed result, processes it once, sends **one** cleaned question, and returns the answer in the same conversation—no manual Send step.
4. If browser recognition fails, the app records a local fallback, processes its finished transcript, and sends it in the same flow—never in a new popup. You can also select offline mode directly or upload a recording.
5. Use **Test microphone only** and the device selector in Voice settings to distinguish a blocked input, a silent microphone, and a speech-service failure. The mic test does not upload audio.

The bundled offline English model uses **PocketSphinx**: no API key, internet connection, or first-use model download is needed. It is a recovery path and less accurate than modern browser or Whisper recognition, but a spoken fallback question is still processed and sent automatically as one turn. Uploaded recordings remain reviewable before sending. Supported uploads include WAV, WebM/Opus, MP3, M4A, OGG, and FLAC, limited to **45 seconds / 15 MB**. Audio is decoded and resampled on the server; the server does not need its own microphone.

Microphone tracks and audio contexts are released on stop, close, page hide, navigation away, permission failure, and canceled/in-flight capture. Read-aloud uses local Kokoro neural speech by default and can be disabled. Interrupting an answer cancels playback before starting capture.

### Natural speaking voices

The default voice is **Heart**, a warm US neural voice—not the browser's robotic system default. Open **Settings → Voice & read-aloud** (no microphone permission needed), or expand **Microphone & voice settings** while talking. Choose Heart, Bella, Michael, or Emma (UK), select a relaxed/conversational/brisk pace, and tap **Preview voice**. Settings survive refresh in the current tab. The read-aloud button also acts as Stop while its answer is playing.

- Kokoro runs on the app server using CPU ONNX inference. No speech API key is needed, and reply text is not sent to a speech provider.
- The first read-aloud downloads about **90 MB** of pinned model/voice packages from the npm registry. SHA-256 checks protect both packages and the assembled model; package JavaScript is never executed. The resulting model and four voice styles occupy about 94 MB in the user cache, not Git or the notebook.
- Preload it to avoid a first-use wait: `python -m solvra_speech`. Use `SOLVRA_TTS_DIR=/path/to/cache` to choose storage. Set `SOLVRA_TTS_AUTO_DOWNLOAD=0` to require preinstalled assets instead of downloading at runtime.
- Exact dollar amounts, cents, dates, percentages, and abbreviations are prepared for speech. Sentence/phrase playback prefetches just one passage ahead; closing, Stop, or a new question invalidates late audio so it cannot start afterward.
- **Device voice** remains an explicit fallback. It waits for delayed voice lists and prefers enhanced/natural voices where available. It cannot upgrade a basic OS voice into a neural one. Device voices may use the browser/OS provider's speech service.
- Speech audio is returned in memory for this session's assistant answers and a fixed preview only. It is not saved as a public audio file. A small in-memory cache holds up to eight passages.

Kokoro model/voice data is Apache-2.0 licensed; see `licenses/KOKORO.txt`. The verified packages are `kokoro-q8-shards@1.0.0` (the ONNX Community quantized Kokoro-82M v1.0 model) and the upstream `kokoro-js@1.2.1` voice styles.

### Optional: a higher-accuracy local model

For better offline transcription, install Faster-Whisper and point the server at an **already-downloaded CTranslate2 Whisper model directory**:

```bash
pip install faster-whisper
SOLVRA_WHISPER_MODEL=/absolute/path/to/whisper-base.en python solvra_app.py
```

The app uses `local_files_only=True` and never attempts a hidden model download. Its careful final-pass settings include a finance-specific prompt for account and bill vocabulary. If no valid local model is configured, PocketSphinx remains available. The base install is fully functional without Whisper.

### Voice privacy and troubleshooting

- Browser recognition may send audio to the browser vendor's speech service. This is controlled by the browser, not a Solvra language-model integration.
- Offline mode uploads audio to the app server for transcription. Gradio uses temporary upload storage; cache cleanup is configured every five minutes for files older than five minutes. Do not upload sensitive recordings to a shared demo server.
- A parent iframe must explicitly allow microphone use. The app cannot override that browser policy; use **Open in a new tab** when blocked.
- If bars move but captions do not, try offline mode. If bars do not move, check the selected input, system mute, and site permissions.
- Browser/device behavior varies. Automated tests exercise capture state, simulated recognition, permission denial, late permission grants, actual offline audio decoding, and uploads; they do not replace testing a physical microphone on every browser.

## The assistant and suggestions

Solvra combines **Grok AI via Puter** for broad, conversational financial guidance with an **explainable local finance engine** for account calculations and every confirmed change. Answers identify which engine produced them. The account is still a fictional demo, not a connected bank account.

### Connect Grok AI

1. In the assistant panel, select **Connect Grok AI** (also available in Settings or Conversation options).
2. Review the sharing/usage notice, check the consent box, and select **Connect with Puter**.
3. Complete the Puter sign-in popup. If an embedded preview blocks popups, open the app in its own HTTPS tab.
4. Ask a finance question normally, by text or voice. Use **Disconnect AI** in the same settings to stop new sharing.

The [Puter tutorial](https://developer.puter.com/tutorials/free-unlimited-grok-api/) is an integration guide, **not an API key**. No pasted key or backend credential is needed: the SDK manages Puter authentication in the user's browser. **Your own Puter account pays for usage** through its allowance/plan; limits and charges can apply. This is not guaranteed unlimited free access, and Solvra never upgrades the plan. See [Puter's usage model](https://docs.puter.com/user-pays-model/).

The pinned SDK is bundled locally and initialized only after consent (including restoring an earlier consent in this tab). Model requests go directly from the browser to Puter using `puter.ai.chat`, with `x-ai/grok-4-1-fast-non-reasoning` for responsive chat. Each advice turn has a small topic-check call and, only when allowed, a bounded answer call; there are no automatic paid retries or tool-execution loops. A provider outage, expired sign-in, quota error, malformed answer, or timeout returns a **clearly labeled local fallback**, never a fake AI answer. Local tools remain usable without connecting AI.

### Scope, grounding, and privacy

- **Finance-only:** budgeting, saving, bills, debt strategies, credit, mortgages, insurance, investing principles, retirement, tax education, and related follow-ups. The topic check receives the current prompt and previous finance question for follow-up context, and rejects unrelated/mixed requests before account summaries are sent. Invalid checks fail closed. The answering prompt also enforces scope; obvious prompt overrides, known mixed-topic requests, financial-crime instructions, sensitive-identifier patterns, and requests for another profile's finances are rejected locally even when AI is off. These pattern checks are not a complete semantic classifier.
- **Bounded account context:** after consent and an allowed topic check, Puter / its model provider receives the current prompt, up to four recent financial exchanges, the selected fictional person's profile and balances/debts/bills/cash-flow summaries, the financial-trouble assessment with evidence and policy, the headroom model, and relevant verified local calculations. A calculation can include matching transactions; the complete ledger and audio recordings are not sent to Grok. Do not type real banking credentials or sensitive identifiers.
- **Read-only AI:** the model receives no execution tools. Its structured reply cannot stage or confirm a change. Recording and confirming deposits/payments always use the local engine, even in AI mode. Server-owned request tickets, account fingerprints, expiry and session checks reject late or cross-session results.
- **Honest limits:** AI can make factual or arithmetic mistakes. Verify its guidance against the displayed account sources and local calculations. It has no live market/rate/news feed, does not guarantee returns, and is not a licensed financial/tax/legal adviser. Consequential decisions should be checked with an appropriate professional.
- **Not an authorization boundary:** topic classification is probabilistic and the browser controls the Puter transport. Scope/output checks are defense in depth, not a cryptographic guarantee of model origin or a security sandbox. Actual ledger permissions and confirmations remain server-enforced; browser/model-supplied actions are never executed. Production use needs independently authenticated, audited infrastructure.

### AI guardrails monitor

The **AI guardrails** workspace tab is a local, visible prompt-security demo. Test a custom prompt or use built-in prompt injection, cross-account, SQL-like injection, role-spoofing, confirmation-bypass, malware, clearly off-topic, and safe-finance examples. Every test is evaluated locally before any AI call or ledger action; the tab shows its **allow/block** decision, reason, counters, and selected-demo-session prompt history. The monitor cannot retrieve another profile, call a model, execute code, or change a ledger. A normal finance prompt may be allowed only as read-only guidance—actual demo ledger changes still use the existing separate review and confirmation controls.

Try these with Grok connected:

- “Compare the avalanche and snowball methods for my debts. What facts would you need to recommend one?”
- “I received a $500 gift. Should I save it or reduce debt?” (advice, not an instruction to record a deposit)
- “Help me plan for a house deposit in five years without compromising my emergency fund.”
- “Explain Roth versus traditional retirement contributions, then help me list the questions I should ask.”
- “How do insurance deductibles affect the cash reserve I should keep?”
- “Explain that more simply.” / “What are the trade-offs for my situation?”

These local account workflows also remain available without AI:

- “How much is in checking and what bills are due this week?”
- “How much did I spend on groceries last month?” → “Compare that with the previous period.” → “What about dining?”
- “Show my last 3 transactions.”
- “Can I afford a $200 purchase?”
- “Build my bill payment plan.” → “Why?”
- “What if I pay electricity 20 days late?”
- “What if my paycheck is 5 days late?”
- “How can I build a stronger emergency fund?”
- “I got paid five hundred dollars.” → review the pending change → “Yes, confirm” or “No, cancel.”

Suggestions show actual amounts, comparison windows, and underlying evidence. Hypothetical savings targets are labeled as targets, not predicted savings. The 30-day affordability estimate deducts recorded bills, a 90-day-based everyday-spending allowance, and the selected reserve; savings and unconfirmed future income are excluded. Unknown or unrecorded obligations can change the answer.

## Explainable financial-trouble ranking

**Triage v1** produces 0–100 *pressure points*: higher means more urgent, unlike the separate seven-factor financial-health score. This is an intentionally simple, disclosed planning heuristic, **not** a credit score, probability of default, lender DTI or prediction of eviction/disconnection. It evaluates one household, not a comparison of other people's accounts.

| Signal | Maximum points | Calculation |
| --- | ---: | --- |
| Overdue essentials | 30 | If any housing/utility/insurance bill is overdue: `min(30, 10 + 5 × count + min(oldest overdue days, 10))`; otherwise 0. |
| 14-day bill shortfall | 25 | `25 × uncovered share of recorded bills due within 14 days`, including arrears; checking only. |
| 30-day headroom pressure | 15 | `15 × negative headroom / recent average monthly income`, capped at 15. Headroom deducts bills, everyday allowance and the selected reserve; savings and expected income are excluded. |
| Recent cash-flow deficit | 15 | `15 × average monthly deficit / 20% of average income`, capped at 15, using the last three completed months. Transfers excluded. |
| Emergency savings gap | 10 | `10 × shortfall from three months of recent essential spending`. Savings are not automatically spent. |
| Required debt-service load | 5 | `5 × required monthly debt payments / 40% of recent monthly recorded income`, capped at 5. This is a recorded-income proxy, not lender DTI. |

Factors are rounded to one decimal; their sum is rounded to an integer. **Stable 0–19 = priority 4; Watch 20–39 = priority 3; High 40–69 = priority 2; Critical 70–100 = priority 1.** An overdue essential sets a minimum of High (40). Housing overdue beyond its recorded grace period plus insufficient checking to cover overdue essentials sets a minimum of Critical (70). The final score is the greater of the weighted total and the applicable floor; both are shown, so the floor is not hidden.

Overview shows the urgency. **Insights → See every factor, point and rule** exposes the evidence, thresholds and safety floors. The fixed triage windows do not change with the reporting dropdown. Ask **“Explain my financial trouble ranking and what I should do first.”** in local mode or with Grok. After consent and the finance-topic gate, Grok receives the **selected person's exact server-calculated ranking, metrics, factors, policy and limitations**, with a server-owned source citation; it does not receive other people's accounts. Confirmed ledger changes recalculate the assessment and invalidate stale AI context.

## Payment planner

SciPy mixed-integer optimization enforces dated cash availability, the selected reserve, applicable minimums, and full-payment-only bill rules. The primary objective minimizes modeled late fees, interest, and consequence weights. A second pass covers additional bills at the same modeled harm, so an affordable zero-fee subscription is not arbitrarily left unpaid. Tie-breaking favors earlier payment dates.

**Consequence weights are prioritization points, not dollar costs.** Estimated fees and interest are reported separately. Provider terms in this fictional account are not lender quotes. A plan is only a preview: recording a payment still requires explicit confirmation and does not pay a provider.

## Sessions and safety

- Each demo workspace has separate person/account/history slots and at most one active, unguessable login token. Each login rotates the token; logout and switching revoke the old token. Bootstrap without an active token exposes only the public people catalog. Tokenless legacy chat cannot create an account.
- Account and conversation state are kept **in memory**, not a permanent database. Refresh restores the active person while the server runs. Workspaces expire after eight hours of inactivity; the server retains at most 64 workspaces, with up to four fictional profiles each. Capacity eviction removes the oldest workspace.
- Session locks and client generations reject stale/cross-profile chat, AI, export, planner, filter, payment and read-aloud responses. Speech is authorized before synthesis and again before delivery; logout does not interrupt already-running neural computation, but its audio is discarded.
- Pending executable changes are kept on the server. Client-supplied pending actions are ignored.
- Chat request IDs make retries idempotent, including a repeated payment/deposit confirmation. New questions do not silently approve or discard an existing pending change.
- **Reset demo account** clears only the selected person's account changes, pending change, conversation, and planning preference; all other people in that workspace retain their state.
- Inputs and amounts are validated; uploaded paths are confined to the upload directory, audio work is bounded, and exported CSV text is protected against spreadsheet formula injection.

This is a single-process prototype, not an authenticated financial service. It is not intended to hold real financial information or survive server restarts. Production use would require authenticated persistent storage, durable idempotency, deployment-specific upload retention, rate limiting, and broader browser/device testing.

## Live-demo preflight

1. Start the server and keep it running. Preload natural speech before presenting: `python -m solvra_speech` (use the same `SOLVRA_TTS_DIR` for setup and the server if you override it).
2. Open the preview/public **HTTPS link in its own tab**. Choose Maya, log in, and use **Settings → Voice & read-aloud → Preview voice** to verify the actual presentation speakers. No microphone permission is needed for read-aloud.
3. Test the **physical microphone on the presentation device**. Allow permission, ask a balance question from the composer, and verify it becomes one clean chat turn. If the browser speech service fails, review the local fallback draft or type; do not rely on a live remote service as the only path.
4. Demonstrate Maya's healthy buffer, then **Settings → Log out → Marcus → Log in to demo** to show a genuinely different ledger, arrears, repair expense and Critical triage. Inspect the factor rules and calculate a bill plan. Jordan and Aisha provide intermediate stress scenarios.
5. For live Grok, explicitly consent and sign in to **your own Puter account** on that device, confirm its allowance, ask about the ranking, and inspect **Grok AI** plus account sources. Logout disconnects AI, so reconnect/consent for another person. Also ask a weather/mixed-topic question to demonstrate the guardrail. No authenticated live provider call is claimed by the automated tests.
6. Try a recorded deposit and cancel it, then confirm a small example and watch the same dashboard update. Reset that person before the main presentation if desired. Demonstrate logout/re-entry without mixing chats or carrying a pending confirmation.
7. If the external provider, popup, network, microphone or speakers are unavailable, keep the **clearly labeled local finance engine**, typed questions, planner, and automatic offline speech fallback available. This is a live-demo prototype, not a guarantee about external services or every browser/device.

## Google Colab

Open [`Solvra_Financial_Triage.ipynb`](Solvra_Financial_Triage.ipynb), run the four code cells, and open the printed public **HTTPS** link in its own tab. The notebook embeds the complete app, web assets, and local font; it does not clone an older version of `main`. Keep the runtime running.

After source or asset changes, regenerate and verify the notebook:

```bash
python scripts/build_notebook.py
python scripts/build_notebook.py --check
```

## Tests

```bash
pytest -q
```

The suite covers explicit login, logged-out API rejection, token rotation/revocation, four reproducible profile scenarios, per-person reset/re-entry, profile/tab isolation, explainable triage math/floors, AI ranking context, offline guardrails, reproducible demo data, ledger consistency, constrained optimization and zero-penalty bills, reporting periods, contextual chat, grounded suggestions, affordability, confirmed mutations, session isolation, idempotency, forged pending actions, transaction filtering/export, upload confinement, real offline transcription, silent audio, and recording limits.

Optional browser regression tests (start the app first):

```bash
pip install -r requirements-dev.txt
playwright install chromium
SOLVRA_E2E_URL=http://127.0.0.1:7860 pytest -q tests/test_browser.py
```

For an existing Chromium binary, set `CHROMIUM_EXECUTABLE_PATH`. Browser tests cover navigation, filtering/export, record/confirm flows, reset and refresh, mobile keyboard access and overflow, final-only recognition with a simulated recognizer, unavailable/denied microphones, cancellation, and actual offline audio upload. They also test the people dropdown, all four account/ranking views, settings logout, separate re-entry, new consent per profile, copy/download/clear/help/reminder controls, expired/failed login recovery, old-profile responses arriving after logout, fresh drill-down filters, retained planner inputs, complete comparison labels, and delayed responses arriving after navigation or a confirmed account change. A prerecorded-speech fake microphone exercises browser recording → service-failure fallback → automatic offline speech turn. Read-aloud tests check exact spoken money, delayed device voices, and cancellation. No microphone recording is taken from the test runner. To include actual neural inference and browser audio playback, prepare the voice model first and set `SOLVRA_TEST_NEURAL=1` when running the suite.

AI regressions use a deterministic Puter response stub with the real session/context/finalization endpoints, plus a real bundled-SDK initialization/blocked-popup test. They verify consent, scope rejection before context sharing, broad finance prompts, read-only confirmations, exact source context, canceled/late responses, quota/malformed-output fallbacks, persistence, escaped text and session isolation. **They do not authenticate a live Puter account or prove real Grok answer quality.** To verify live inference, connect your own Puter account through the app, ask a financial question, inspect the **Grok AI** label and account sources, test an off-topic question, and check your Puter usage dashboard.

## Project layout

- `solvra_app.py` — deterministic account data, ledger, optimizer, compatibility entry points, Gradio launch.
- `solvra_profiles.py` — public fictional people, reproducible scenario recipes, profile-aware seed/reset.
- `solvra_insights.py` — explainable six-factor financial-trouble triage, shared reporting windows, dashboard calculations, affordability, evidence-backed insights, plan serialization.
- `solvra_assistant.py` — local financial intent handling, multi-turn context, spoken amounts, staged changes, sourced answers.
- `solvra_ai.py` — Grok finance-only prompts, bounded account context, structured output and read-only validation.
- `solvra_workspace.py` — demo login/logout, isolated per-person workspaces and revoked-token checks, server-owned confirmations, AI turn tickets, retry deduplication, transaction queries and CSV export.
- `solvra_voice.py` — bounded offline decoding/transcription and local-model capabilities.
- `solvra_speech.py` — verified neural model setup, financial speech preparation, bounded synthesis and caching.
- `web/` — responsive interface, SVG visualizations, consented Puter AI controller, microphone state machine, shared neural/device playback controller, bundled DM Sans font and license. No frontend build or CDN dependency. `web/vendor/` contains the pinned Puter.js SDK and provenance; see `licenses/PUTER.txt`.
- `scripts/build_notebook.py` — reproducible self-contained Colab bundle.
- `test_solvra_app.py`, `tests/` — core, workspace, audio, and opt-in browser tests.
