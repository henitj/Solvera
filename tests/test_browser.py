"""Opt-in real-browser regressions. Start Solvra, then set SOLVRA_E2E_URL.

No real microphone is opened: Chromium uses its fake capture device and recognition
is simulated where deterministic captions are needed. The upload test uses real
server-side decoding and PocketSphinx, not a mocked transcription endpoint.
"""

import os
from pathlib import Path

import pytest

URL = os.environ.get("SOLVRA_E2E_URL", "")
pytestmark = pytest.mark.skipif(
    not URL, reason="Set SOLVRA_E2E_URL to a running workspace for browser tests"
)

RECOGNIZER = """
window.__recognizers = [];
window.SpeechRecognition = class {
  constructor() { window.__recognizers.push(this); }
  start() { this.started = true; window.__recognizer = this; this.onstart?.(); }
  stop() { this.onend?.(); }
  abort() { this.aborted = true; this.onend?.(); }
};
"""


def browser_options(*extra_args):
    options = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            *extra_args,
        ],
    }
    if os.environ.get("CHROMIUM_EXECUTABLE_PATH"):
        options["executable_path"] = os.environ["CHROMIUM_EXECUTABLE_PATH"]
    return options


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        instance = p.chromium.launch(**browser_options())
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield page
    context.close()
    assert not errors, f"Uncaught frontend errors: {errors}"


def open_workspace(page, profile="maya"):
    page.goto(URL)
    page.wait_for_function(
        "document.querySelector('.stats-grid') || document.querySelector('#demo-person:not(:disabled)')",
        timeout=45000,
    )
    if not page.locator(".stats-grid").is_visible():
        page.locator("#demo-person").select_option(profile)
        page.locator("#demo-login-button").click()
    page.wait_for_selector(".stats-grid", timeout=45000)


def ask(page, text):
    count = page.locator(".chat-message.assistant").count()
    page.locator("#chat-input").fill(text)
    page.locator("#chat-send").click()
    page.wait_for_function(
        "count => document.querySelectorAll('.chat-message.assistant').length > count",
        arg=count,
    )
    return page.locator(".chat-message.assistant").last.inner_text()


def emit_transcript(page, text):
    page.evaluate(
        """text => {
        const results = [[{transcript:text, confidence:0.99}]];
        results[0].isFinal = true;
        window.__recognizer.onresult({resultIndex:0, results});
    }""",
        text,
    )


def test_navigation_filters_empty_state_and_csv_download(page, tmp_path):
    open_workspace(page)
    page.locator('.main-nav [data-view="transactions"]').click()
    page.wait_for_selector("[data-tx]")
    assert "897" in page.locator("#tx-filter-summary").inner_text()
    page.locator("#tx-search").fill("Jewel")
    page.wait_for_function(
        "document.querySelector('#tx-filter-summary').textContent.includes('80')"
    )
    assert page.locator("#tx-results [data-tx]").count() == 10
    page.locator("[data-tx]").first.click()
    assert page.locator("#dialog-title").inner_text() == "Jewel-Osco"
    page.locator("#close-dialog").click()
    with page.expect_download() as download:
        page.locator("#export-button").click()
    file = download.value.path()
    csv_text = Path(file).read_text()
    assert "Jewel-Osco" in csv_text and "Target Grocery" not in csv_text
    page.locator("#tx-search").fill("a merchant that is not recorded")
    page.wait_for_selector("#tx-results .table-empty")
    assert "No transactions match" in page.locator("#tx-results").inner_text()
    page.locator('#tx-results [data-action="clear-filters"]').click()
    page.wait_for_selector("[data-tx]")
    assert "897" in page.locator("#tx-filter-summary").inner_text()


def test_bill_planner_and_late_simulation_have_real_results(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="bills"]').click()
    page.locator("#plan-form button").click()
    page.wait_for_selector(".payment-step", timeout=30000)
    assert page.locator(".payment-step").count() == 10
    assert "$2,529.59" in page.locator(".plan-summary").inner_text()
    assert "$0.00" in page.locator(".plan-summary").inner_text()
    page.locator("#sim-days").fill("20")
    page.locator("#simulate-form button").click()
    page.wait_for_selector(".simulation-result")
    result = page.locator("#simulation-output").inner_text()
    assert "$18.00" in result and "Nothing has changed" in result
    page.locator('.main-nav [data-view="insights"]').click()
    assert page.locator(".insight-evidence").count() == 3
    page.locator('[data-action="toggle-factors"]').click()
    assert page.locator("#health-factors").is_visible()
    assert page.locator(".health-factor").count() == 7


def test_chat_context_and_confirmed_changes_survive_refresh_then_reset(page):
    open_workspace(page)
    assert "$752.85" in ask(page, "How much did I spend on groceries last month?")
    assert "groceries" in ask(page, "Compare that with the previous period.")
    ask(page, "I got paid five hundred dollars")
    assert page.locator("#chat-pending").is_visible()
    assert "$19,259.44" in page.locator(".stat-value").first.inner_text()
    page.locator("[data-confirm]").first.click()
    page.wait_for_selector("#chat-pending[hidden]", state="attached")
    assert "$19,759.44" in page.locator(".stat-value").first.inner_text()
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert "$19,759.44" in page.locator(".stat-value").first.inner_text()
    assert "Done." in page.locator(".chat-message.assistant").last.inner_text()
    page.locator("#settings-button").click()
    page.locator('[data-action="confirm-reset"]').click()
    page.locator('[data-action="reset-now"]').click()
    page.wait_for_selector(".chat-welcome")
    assert "$19,259.44" in page.locator(".stat-value").first.inner_text()
    assert not page.locator("#chat-pending").is_visible()


def test_add_transaction_stages_then_confirms_in_shared_ledger(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="transactions"]').click()
    page.locator('[data-action="add-transaction"]').click()
    form = page.locator("#add-transaction-form")
    form.locator('[name="amount"]').fill("12.34")
    form.locator('[name="merchant"]').fill("Browser test cafe")
    form.locator('[name="category"]').select_option("Dining & Entertainment")
    form.locator("button").last.click()
    page.wait_for_selector("#chat-pending:not([hidden])")
    assert "897" in page.locator("#tx-filter-summary").inner_text()
    page.locator("[data-confirm]").first.click()
    page.wait_for_selector("#chat-pending[hidden]", state="attached")
    page.wait_for_function(
        "document.querySelector('#tx-filter-summary').textContent.includes('898')"
    )
    page.locator("#tx-search").fill("Browser test cafe")
    page.wait_for_function("document.querySelectorAll('#tx-results [data-tx]').length === 1")
    assert "−$12.34" in page.locator("#tx-results").inner_text()


def test_inline_voice_sends_one_clean_turn_without_opening_a_dialog(page):
    page.add_init_script(RECOGNIZER)
    open_workspace(page)
    page.locator("#voice-launch").click()
    page.wait_for_function("window.__recognizer?.started")
    assert not page.locator("#voice-dialog").evaluate("dialog => dialog.open")
    assert page.locator("#inline-voice-status").is_visible()

    # An unexpected interim hypothesis must never send a partial question.
    page.evaluate(
        """() => {
        const results = [[{transcript:'How much money', confidence:0.99}]];
        results[0].isFinal = false;
        window.__recognizer.onresult({resultIndex:0, results});
        }""",
    )
    assert page.locator(".chat-message").count() == 0

    # A browser can revise a finalized segment more than once. The composer
    # must replace it—not append it or create two chat turns.
    emit_transcript(page, "How much money do I have?")
    emit_transcript(page, "How much money do I have?")
    page.wait_for_selector(".chat-message.assistant", state="attached")

    assert page.locator(".chat-message.user").count() == 1
    assert page.locator(".chat-message.user .message-text").inner_text() == "How much money do I have?"
    assert "$26,999.44" in page.locator(".chat-message.assistant").inner_text()
    assert not page.locator("#chat-pending").is_visible()
    assert page.locator("#inline-voice-status").is_hidden()


def test_inline_voice_can_leave_one_reviewable_draft_when_auto_send_is_off(page):
    page.add_init_script(RECOGNIZER)
    open_workspace(page)
    page.locator("#settings-button").click()
    page.locator('[data-action="voice-settings"]').click()
    page.locator(".voice-settings summary").click()
    page.locator("#voice-auto").uncheck()
    page.locator("#close-voice").click()

    page.locator("#chat-mic").click()
    page.wait_for_function("window.__recognizer?.started")
    emit_transcript(page, "What is my checking balance?")
    page.wait_for_function(
        "document.querySelector('#inline-voice-status').dataset.phase === 'review'",
    )

    assert page.locator("#chat-input").input_value() == "What is my checking balance?"
    assert page.locator(".chat-message").count() == 0
    page.locator("#chat-send").click()
    page.wait_for_selector(".chat-message.assistant", state="attached")
    assert page.locator(".chat-message.user").count() == 1
    assert "$19,259.44" in page.locator(".chat-message.assistant").inner_text()


def test_permission_denial_is_actionable_and_does_not_hang(page):
    page.add_init_script(
        RECOGNIZER
        + "navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Permission denied', 'NotAllowedError'); };"
    )
    open_workspace(page)
    page.locator("#settings-button").click()
    page.locator('[data-action="voice-settings"]').click()
    page.locator("#voice-start").click()
    page.wait_for_selector("#voice-error:not([hidden])")
    assert "permission was denied" in page.locator("#voice-error").inner_text()
    assert "site settings" in page.locator("#voice-error").inner_text()
    assert page.locator("#voice-start").is_enabled()
    page.locator("#close-voice").click()
    assert "$19,259.44" in ask(page, "What is my checking balance?")


def test_late_permission_grant_is_released_after_dialog_closes(page):
    page.add_init_script(
        RECOGNIZER
        + """
const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async (constraints) => {
  const stream = await original(constraints);
  window.__lateStream = stream;
  return new Promise(resolve => { window.__grantLate = () => resolve(stream); });
};
"""
    )
    open_workspace(page)
    page.locator("#settings-button").click()
    page.locator('[data-action="voice-settings"]').click()
    page.locator("#voice-start").click()
    page.wait_for_function("typeof window.__grantLate === 'function'")
    page.locator("#close-voice").click()
    page.evaluate("window.__grantLate()")
    page.wait_for_function("window.__lateStream.getTracks().every(t => t.readyState === 'ended')")
    assert page.locator("#voice-stage").get_attribute("data-phase") == "idle"
    assert page.locator(".chat-message").count() == 0


def test_browser_service_failure_switches_to_inline_local_capture(page):
    page.add_init_script(RECOGNIZER)
    open_workspace(page)
    page.locator("#voice-launch").click()
    page.wait_for_function("window.__recognizer?.started")
    page.evaluate("window.__recognizer.onerror({error:'network'})")
    page.wait_for_function(
        "document.querySelector('#inline-voice-status').textContent.includes('Listening locally')",
    )
    assert not page.locator("#voice-dialog").evaluate("dialog => dialog.open")
    assert "Listening locally" in page.locator("#inline-voice-status").inner_text()
    page.evaluate("voice.stopAll()")
    assert page.locator("#inline-voice-status").is_hidden()


def test_actual_offline_upload_is_reviewed_and_never_auto_sent(page):
    open_workspace(page)
    page.locator("#attach-audio").click()
    page.locator(".voice-settings summary").click()
    page.locator("#voice-auto").check()
    fixture = Path(__file__).parent / "fixtures" / "goforward.flac"
    page.locator("#audio-upload").set_input_files(fixture)
    page.wait_for_function(
        "document.querySelector('#voice-stage').dataset.phase === 'review'",
        timeout=45000,
    )
    assert page.locator("#voice-transcript").input_value() == "go forward ten meters"
    assert page.locator(".chat-message").count() == 0
    assert "inaccurate" in page.locator("#voice-detail").inner_text()
    assert page.locator("#voice-use").is_enabled()


def test_mobile_navigation_chat_and_tables_do_not_overflow_the_page(page):
    page.set_viewport_size({"width": 390, "height": 844})
    open_workspace(page)
    assert page.evaluate("document.body.scrollWidth <= window.innerWidth")
    assert page.locator("#main-navigation").evaluate("e => e.inert")
    page.locator("#mobile-menu").click()
    assert page.locator("#mobile-menu").get_attribute("aria-expanded") == "true"
    page.locator('.main-nav [data-view="transactions"]').click()
    page.wait_for_selector("[data-tx]")
    assert not page.locator("#nav-backdrop").is_visible()
    assert page.locator("#main-navigation").evaluate("e => e.inert")
    assert page.evaluate("document.body.scrollWidth <= window.innerWidth")
    page.locator("#mobile-chat").click()
    assert page.locator("#assistant-panel").is_visible()
    assert "$19,259.44" in ask(page, "How much money do I have?")
    page.locator("#expand-chat").click()
    assert page.locator("#tx-search").is_visible()


def test_device_voice_waits_for_natural_voices_and_preserves_exact_money(page):
    page.add_init_script("""
window.__spoken = []; window.__voices = [];
const events = new EventTarget();
window.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
Object.defineProperty(window, 'speechSynthesis', {value: {
  getVoices: () => window.__voices, cancel: () => {},
  addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events),
  speak: (utterance) => { if (utterance.text.trim()) window.__spoken.push({text:utterance.text, voice:utterance.voice?.name, rate:utterance.rate}); setTimeout(() => utterance.onend?.(), 0); }
}});
window.__publishVoices = () => {
  window.__voices = [{name:'eSpeak English', lang:'en-US', voiceURI:'robot'}, {name:'Microsoft Aria Online Natural', lang:'en-US', voiceURI:'natural'}];
  events.dispatchEvent(new Event('voiceschanged'));
};
""")
    open_workspace(page)
    ask(page, "How much money do I have?")
    page.locator("#attach-audio").click()
    page.locator(".voice-settings summary").click()
    page.locator("#speech-engine").select_option("device")
    assert page.locator("#speech-voice option").count() == 0
    page.evaluate("window.__publishVoices()")
    assert page.locator("#speech-voice").input_value() == "natural"
    page.locator("#speech-rate").select_option("0.9")
    page.locator("#close-voice").click()
    page.locator("[data-read-message]").click()
    page.wait_for_function(
        "document.querySelector('#speech-status').textContent.includes('finished')"
    )
    spoken = page.evaluate("window.__spoken")
    words = " ".join(part["text"] for part in spoken)
    assert "nineteen thousand, two hundred and fifty-nine dollars and forty-four cents" in words
    assert "seven thousand, seven hundred and forty dollars" in words
    assert "twenty-six thousand, nine hundred and ninety-nine dollars and forty-four cents" in words
    assert all(
        part["voice"] == "Microsoft Aria Online Natural" and part["rate"] == 0.9 for part in spoken
    )
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert page.locator("#speech-engine").input_value() == "device"
    assert page.locator("#speech-rate").input_value() == "0.9"


@pytest.mark.parametrize(
    "error_name,expected",
    [
        ("NotFoundError", "No microphone was found"),
        ("NotReadableError", "Another app may be using it"),
    ],
)
def test_missing_or_unavailable_microphone_is_reported(page, error_name, expected):
    page.add_init_script(
        RECOGNIZER
        + f"navigator.mediaDevices.getUserMedia = async () => {{ throw new DOMException('Capture failed', '{error_name}'); }};"
    )
    open_workspace(page)
    page.locator("#settings-button").click()
    page.locator('[data-action="voice-settings"]').click()
    page.locator("#voice-start").click()
    page.wait_for_selector("#voice-error:not([hidden])")
    assert expected in page.locator("#voice-error").inner_text()
    assert page.locator("#voice-start").is_enabled()
    assert page.locator(".chat-message").count() == 0


def test_recorded_microphone_fallback_uploads_decodes_and_requires_review(browser, tmp_path):
    # Supply prerecorded speech to Chromium's fake microphone, not the runner's mic.
    import numpy as np
    from scipy.io.wavfile import write

    from solvra_voice import decode_pcm

    fixture = Path(__file__).parent / "fixtures" / "goforward.flac"
    clip = tmp_path / "fake-microphone.wav"
    audio = np.concatenate(
        [
            np.zeros(16000, dtype=np.int16),
            decode_pcm(str(fixture)),
            np.zeros(32000, dtype=np.int16),
        ]
    )
    write(clip, 16000, audio)
    recorded_browser = browser.browser_type.launch(
        **browser_options(f"--use-file-for-fake-audio-capture={clip}")
    )
    try:
        context = recorded_browser.new_context()
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(
            RECOGNIZER
            + """
const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async (constraints) => {
  window.__capturedStream = await capture(constraints);
  return window.__capturedStream;
};
"""
        )
        open_workspace(page)
        page.locator("#voice-launch").click()
        page.wait_for_function("window.__recognizer?.started")
        page.evaluate("window.__recognizer.onerror({error:'network'})")
        page.wait_for_function(
            "document.querySelector('#inline-voice-status').dataset.phase === 'review'",
            timeout=45000,
        )
        # Lossy browser encoding can change a word. The recovery transcript stays
        # in the composer for review and must not auto-send a chat turn.
        transcript = page.locator("#chat-input").input_value().lower()
        assert "go forward" in transcript and len(transcript.split()) >= 3
        assert not page.locator("#voice-dialog").evaluate("dialog => dialog.open")
        assert page.locator(".chat-message").count() == 0
        assert page.locator("#chat-send").is_enabled()
        assert page.evaluate(
            "window.__capturedStream.getTracks().every(t => t.readyState === 'ended')"
        )
        assert not errors
        context.close()
    finally:
        recorded_browser.close()


TRACK_AUDIO = """
window.__decodedAudio = 0; window.__playedAudio = [];
const AudioContextOriginal = window.AudioContext;
window.AudioContext = class extends AudioContextOriginal {
  decodeAudioData(...args) { ++window.__decodedAudio; return super.decodeAudioData(...args); }
  createBufferSource() {
    const source = super.createBufferSource(), start = source.start.bind(source);
    source.start = (...args) => { window.__playedAudio.push({frames:source.buffer.length, rate:source.buffer.sampleRate}); return start(...args); };
    return source;
  }
};
"""


def open_speech_settings(page):
    open_workspace(page)
    page.locator("#settings-button").click()
    page.locator('[data-action="voice-settings"]').click()
    assert page.locator("#speech-engine").input_value() == "neural"


def test_voice_settings_preview_needs_no_microphone_and_toggles_are_visible(page):
    page.add_init_script(
        "window.__micRequests = 0; navigator.mediaDevices.getUserMedia = async () => { ++window.__micRequests; throw new Error('Microphone must not be requested'); };"
    )
    open_speech_settings(page)
    assert page.locator(".voice-settings").get_attribute("open") is not None
    assert page.locator("#speech-preview").is_enabled()
    assert page.locator("#voice-read").is_checked()
    assert page.locator("#voice-read").evaluate("e => getComputedStyle(e).appearance") == "auto"
    page.locator("#voice-read").uncheck()
    page.locator("#speech-engine").select_option("device")
    assert (
        "Device" in page.locator("#speech-status").inner_text()
        or "device" in page.locator("#speech-status").inner_text()
    )
    page.locator("#speech-engine").select_option("neural")
    assert "Natural" in page.locator("#speech-status").inner_text()
    assert page.evaluate("window.__micRequests") == 0
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert not page.locator("#voice-read").is_checked()
    assert page.evaluate("window.__micRequests") == 0


@pytest.mark.parametrize("after", ["close", "logout"])
def test_canceled_neural_request_never_decodes_or_plays_late_audio(page, after):
    import base64
    import io
    import wave

    page.add_init_script(TRACK_AUDIO)
    pending = []

    def hold_speech(route):
        if route.request.post_data_json.get("data", {}).get("op") == "speech":
            pending.append(route)
        else:
            route.continue_()

    page.route("**/component_server**", hold_speech)
    open_speech_settings(page)
    with page.expect_request(
        lambda request: (
            request.post_data_json.get("data", {}).get("op") == "speech"
            if request.method == "POST"
            else False
        )
    ):
        page.locator("#speech-preview").click()
    assert pending
    page.locator("#close-voice").click()
    if after == "logout":
        log_out(page)
        choose_person(page, "marcus")
        assert page.locator("#voice-transcript").input_value() == ""
    file = io.BytesIO()
    with wave.open(file, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(4800))
    with page.expect_response(lambda response: "/component_server" in response.url):
        pending[0].fulfill(
            json={
                "audio": base64.b64encode(file.getvalue()).decode(),
                "engine": "Kokoro neural",
                "chunks": 2,
                "index": 0,
            }
        )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    assert page.evaluate("window.__decodedAudio") == 0
    assert page.evaluate("window.__playedAudio") == []
    assert page.locator("#speech-stop").is_disabled()
    assert page.locator("#voice-stage").get_attribute("data-phase") == "idle"


def test_neural_failure_is_visible_and_never_silently_uses_a_robotic_voice(page):
    page.add_init_script(
        "window.__deviceSpeech = 0; const originalSpeak = speechSynthesis.speak.bind(speechSynthesis); speechSynthesis.speak = u => {++window.__deviceSpeech; originalSpeak(u);};"
    )

    def fail_speech(route):
        if route.request.post_data_json.get("data", {}).get("op") == "speech":
            route.fulfill(json={"error": "Natural voice model unavailable."})
        else:
            route.continue_()

    page.route("**/component_server**", fail_speech)
    open_speech_settings(page)
    page.locator("#speech-preview").click()
    page.wait_for_function(
        "document.querySelector('#speech-status').textContent.includes('unavailable')"
    )
    assert page.locator("#speech-engine").input_value() == "neural"
    assert page.evaluate("window.__deviceSpeech") == 0
    assert page.locator("#speech-stop").is_disabled()
    page.locator("#close-voice").click()
    assert "$19,259.44" in ask(page, "What is my checking balance?")


@pytest.mark.skipif(
    os.environ.get("SOLVRA_TEST_NEURAL") != "1",
    reason="Set SOLVRA_TEST_NEURAL=1 with prepared model assets",
)
def test_real_neural_preview_plays_in_browser_and_can_be_stopped(page):
    page.add_init_script(TRACK_AUDIO)
    open_speech_settings(page)
    assert page.locator("#speech-voice option").count() == 4
    page.locator("#speech-voice").select_option("bf_emma")
    page.locator("#speech-rate").select_option("1.1")
    page.locator("#speech-preview").click()
    page.wait_for_function("window.__playedAudio.length > 0", timeout=90000)
    played = page.evaluate("window.__playedAudio")
    assert played[0]["rate"] in {24000, 44100, 48000}
    assert played[0]["frames"] / played[0]["rate"] > 1
    assert "Kokoro neural" in page.locator("#speech-status").inner_text()
    page.locator("#speech-stop").click()
    assert page.locator("#speech-stop").is_disabled()
    assert "stopped" in page.locator("#speech-status").inner_text()
    assert page.locator(".chat-message").count() == 0
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert page.locator("#speech-voice").input_value() == "bf_emma"
    assert page.locator("#speech-rate").input_value() == "1.1"
    ask(page, "What is my checking balance?")
    read = page.locator("[data-read-message]")
    read.click()
    page.wait_for_function("window.__playedAudio.length > 0", timeout=90000)
    assert read.get_attribute("aria-pressed") == "true"
    read.click()
    assert read.get_attribute("aria-pressed") == "false"
    assert page.locator("#speech-stop").is_disabled()


@pytest.mark.skipif(
    os.environ.get("SOLVRA_TEST_NEURAL") != "1",
    reason="Set SOLVRA_TEST_NEURAL=1 with prepared model assets",
)
def test_spoken_reply_uses_neural_audio_and_interrupt_restarts_only_capture(page):
    page.add_init_script(RECOGNIZER + TRACK_AUDIO)
    open_workspace(page)
    page.locator("#voice-launch").click()
    page.wait_for_function("window.__recognizer?.started")
    page.locator(".voice-settings summary").click()
    assert page.locator("#speech-preview").is_disabled()
    emit_transcript(page, "What is my checking balance?")
    page.locator("#voice-start").click()
    page.wait_for_function("document.querySelector('#voice-stage').dataset.phase === 'review'")
    assert page.locator("#speech-preview").is_enabled()
    page.locator("#voice-use").click()
    page.wait_for_function("window.__playedAudio.length > 0", timeout=90000)
    assert page.locator("#voice-stage").get_attribute("data-phase") == "speaking"
    assert "Kokoro neural" in page.locator("#speech-status").inner_text()
    assert "$19,259.44" in page.locator("#voice-answer").inner_text()
    page.locator("#voice-start").click()
    page.wait_for_function("window.__recognizers.length === 2 && window.__recognizer.started")
    assert page.locator("#voice-stage").get_attribute("data-phase") == "listening"
    assert page.locator("#speech-stop").is_disabled()
    assert page.locator("#speech-preview").is_disabled()
    page.locator("#close-voice").click()
    assert page.locator("#voice-stage").get_attribute("data-phase") == "idle"


def hold_workspace_response(page, operation, *, error=None):
    """Delay transport after real server work, to exercise UI navigation races."""
    pending = []

    def hold(route):
        body = route.request.post_data_json
        matches = (
            body.get("fn_name") == "live_turn"
            if operation == "chat"
            else body.get("data", {}).get("op") == operation
        )
        if matches:
            pending.append((route, route.fetch() if not error else None))
            page.evaluate("window.__heldResponse = true")
        else:
            route.continue_()

    page.route("**/component_server**", hold)

    def release():
        assert pending, "The expected workspace request was not intercepted"
        route, response = pending.pop(0)
        with page.expect_response(lambda response: "/component_server" in response.url):
            route.fulfill(json={"error": error}) if error else route.fulfill(response=response)
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )

    return pending, release


def test_global_search_and_spending_links_clear_unrelated_income_filters(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="transactions"]').click()
    page.wait_for_selector("[data-tx]")
    page.locator("#tx-direction").select_option("in")
    page.locator("#global-search").fill("Aldi")
    page.locator("#global-search").press("Enter")
    page.wait_for_function("document.querySelector('#tx-results').textContent.includes('Aldi')")
    assert page.locator("#tx-direction").input_value() == ""
    assert "−$" in page.locator("#tx-results").inner_text()
    page.locator("#tx-direction").select_option("in")
    page.locator('.main-nav [data-view="overview"]').click()
    page.locator('.legend-row[data-category="Groceries"]').click()
    page.wait_for_selector("#tx-results [data-tx]")
    assert page.locator("#tx-category").input_value() == "Groceries"
    assert page.locator("#tx-direction").input_value() == "out"
    assert "−$" in page.locator("#tx-results").inner_text()


def test_bill_tabs_preserve_unsaved_reserve_income_and_simulation_inputs(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="bills"]').click()
    page.locator("#plan-reserve").fill("2500")
    page.locator("#plan-income").check()
    page.locator("#sim-days").fill("20")
    page.locator('[data-bill-tab="plan"]').click()
    page.locator('[data-bill-tab="bills"]').click()
    assert page.locator("#plan-reserve").input_value() == "2500"
    assert page.locator("#plan-income").is_checked()
    assert page.locator("#sim-days").input_value() == "20"


def test_late_simulation_cannot_update_an_unrelated_view(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="bills"]').click()
    pending, release = hold_workspace_response(page, "simulate")
    page.locator("#simulate-form button").click()
    page.wait_for_function("window.__heldResponse === true")
    assert pending
    page.locator('.main-nav [data-view="insights"]').click()
    release()
    assert page.locator(".insight-evidence").count() == 3
    assert "null" not in page.locator("#toast-region").inner_text()
    assert not page.locator("#simulation-output").count()


def test_late_form_error_preserves_the_new_dialog_and_releases_the_chat(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="transactions"]').click()
    page.locator('[data-action="add-transaction"]').click()
    form = page.locator("#add-transaction-form")
    form.locator('[name="amount"]').fill("12.34")
    form.locator('[name="merchant"]').fill("Late form response")
    pending, release = hold_workspace_response(
        page, "stage_transaction", error="Please try this change again."
    )
    form.locator("button").last.click()
    page.wait_for_function("window.__heldResponse === true")
    assert pending
    page.locator("#close-dialog").click()
    page.locator("#profile-button").click()
    release()
    assert page.locator("#dialog-title").inner_text() == "Maya Chen’s demo space."
    assert page.locator("#app-dialog").is_visible()
    assert "Please try this change again" in page.locator("#toast-region").inner_text()
    page.locator("#close-dialog").click()
    assert page.locator("#chat-send").is_enabled()
    assert "$19,259.44" in ask(page, "What is my checking balance?")


def test_clear_and_reset_wait_for_an_inflight_reply(page):
    open_workspace(page)
    pending, release = hold_workspace_response(page, "chat")
    page.locator("#chat-input").fill("What is my checking balance?")
    page.locator("#chat-send").click()
    page.wait_for_function("window.__heldResponse === true")
    assert pending
    page.locator("#settings-button").click()
    assert page.locator('[data-action="confirm-reset"]').is_disabled()
    page.locator("#close-dialog").click()
    page.locator("#chat-options").click()
    assert page.locator('[data-action="clear-chat"]').is_disabled()
    release()
    page.wait_for_selector(".chat-message.assistant")
    assert "$19,259.44" in page.locator(".chat-message.assistant").inner_text()
    assert page.locator('[data-action="clear-chat"]').is_enabled()
    page.locator('[data-action="clear-chat"]').click()
    page.wait_for_selector(".chat-welcome")


def test_old_plan_cannot_overwrite_a_newly_confirmed_balance(page):
    open_workspace(page)
    page.locator('.main-nav [data-view="bills"]').click()
    pending, release = hold_workspace_response(page, "plan")
    page.locator("#plan-form button").click()
    page.wait_for_function("window.__heldResponse === true")
    assert pending
    ask(page, "I got paid five hundred dollars")
    page.locator("[data-confirm]").first.click()
    page.wait_for_selector("#chat-pending[hidden]", state="attached")
    release()
    page.locator('.main-nav [data-view="overview"]').click()
    assert "$19,759.44" in page.locator(".stat-value").first.inner_text()
    page.locator('.main-nav [data-view="bills"]').click()
    page.locator('[data-bill-tab="plan"]').click()
    assert not page.locator(".payment-step").count()


def test_mobile_keyboard_navigation_and_search_remain_accessible(page):
    page.set_viewport_size({"width": 390, "height": 844})
    open_workspace(page)
    menu = page.locator("#mobile-menu")
    menu.click()
    page.locator('.main-nav [data-view="transactions"]').click()
    assert menu.get_attribute("aria-expanded") == "false"
    assert menu.get_attribute("aria-label") == "Open navigation"
    assert menu.evaluate("el => el === document.activeElement")
    search = page.locator("#global-search-toggle")
    search.focus()
    search.press("Enter")
    assert page.locator("#global-search").evaluate("el => el === document.activeElement")
    page.locator("#global-search").fill("Aldi")
    page.locator("#global-search").press("Enter")
    page.wait_for_function("document.querySelector('#tx-results').textContent.includes('Aldi')")
    page.locator("#profile-button").focus()
    assert "expanded" not in page.locator("#global-search-form").get_attribute("class")
    assert page.locator("#global-search").is_hidden()


def test_voice_engine_details_do_not_mislabel_the_device_fallback(page):
    open_workspace(page)
    page.locator("#settings-button").click()
    page.locator('[data-action="voice-settings"]').click()
    page.locator("#speech-engine").select_option("device")
    assert "browser/OS" in page.locator("#speech-engine-detail").inner_text()
    assert "server" not in page.locator("#speech-engine-detail").inner_text()
    page.locator("#speech-engine").select_option("neural")
    assert "app’s server" in page.locator("#speech-engine-detail").inner_text()


def test_rolling_period_labels_show_both_comparison_months(page):
    open_workspace(page)
    page.locator("#reporting-period").select_option("90days")
    page.wait_for_function(
        "document.querySelector('.stat-meta').closest('.stats-grid').textContent.includes('vs May')"
    )
    assert "vs May 19–Aug 16" in page.locator(".stats-grid").inner_text()


def test_late_period_response_cannot_restore_a_preconfirmation_balance(page):
    open_workspace(page)
    pending, release = hold_workspace_response(page, "dashboard")
    page.locator("#reporting-period").select_option("last_month")
    page.wait_for_function("window.__heldResponse === true")
    assert pending
    ask(page, "I got paid five hundred dollars")
    page.locator("[data-confirm]").first.click()
    page.wait_for_selector("#chat-pending[hidden]", state="attached")
    assert "$19,759.44" in page.locator(".stat-value").first.inner_text()
    release()
    assert "$19,759.44" in page.locator(".stat-value").first.inner_text()
    assert page.locator("#nav-tx-count").inner_text() == "898"
    assert page.locator("#reporting-period").input_value() == "last_month"
    assert page.locator("#reporting-period").is_enabled()


# Deterministic provider-contract stub; production uses the unmodified bundled SDK.
# These tests exercise real server context/finalization, not real Grok inference/billing.
PUTER_STUB = """
window.__puterCalls = [];
window.__puterSignIns = 0;
window.__puterSignedIn = false;
window.__puterMode = 'answer';
window.puter = {
  auth: {
    isSignedIn: () => window.__puterSignedIn,
    signIn: async () => { ++window.__puterSignIns; window.__puterSignedIn = true; return {success:true}; }
  },
  ai: { chat: async (messages, options) => {
    window.__puterCalls.push({messages, model:options.model, schema:options.outputFormat, max_tokens:options.max_tokens});
    const guard = options.outputFormat.name === 'solvra_finance_scope';
    if (guard) {
      if (window.__puterMode === 'bad_guard') return {message:{content:'not JSON'}};
      const question = JSON.parse(messages[1].content).question;
      return {message:{content:JSON.stringify({scope:/weather|dragon|football|poem/i.test(question) ? 'off_topic' : 'finance'})}};
    }
    if (window.__puterMode === 'quota') throw {code:'insufficient_credit'};
    const value = JSON.stringify({scope:'finance', reply:window.__puterReply || 'Compare the debt avalanche and snowball methods. Your checking is $19,259.44; keep a reserve and verify each debt APR before committing extra cash.', source_ids:['balances','buffer'], suggestions:['How should I choose a debt payoff method?']});
    if (window.__puterMode === 'hold') return new Promise(resolve => {window.__releasePuter = () => resolve({message:{content:value}});});
    return {message:{content:value}};
  }}
};
"""


def connect_grok(page):
    page.locator("#ai-status-button").click()
    assert page.locator("#ai-connect").is_disabled()
    page.locator("#ai-consent").check()
    page.locator("#ai-connect").click()
    page.wait_for_function(
        "document.querySelector('#ai-status-button').dataset.connected === 'true'"
    )
    page.locator("#close-dialog").click()


def test_grok_is_opt_in_and_offline_chat_never_initializes_the_provider(page):
    open_workspace(page)
    assert page.evaluate("typeof window.puter") == "undefined"
    assert "$19,259.44" in ask(page, "What is my checking balance?")
    assert page.evaluate("typeof window.puter") == "undefined"
    assert page.locator(".engine-badge").inner_text() == "Local finance engine"
    page.locator("#ai-status-button").click()
    assert page.locator("#ai-connect").is_disabled()
    assert "allowance" in page.locator("#dialog-content").inner_text()
    assert "Puter and its model provider" in page.locator("#dialog-content").inner_text()
    assert page.evaluate("typeof window.puter") == "undefined"


def test_grok_guidance_uses_account_context_and_persists_a_labeled_answer(page):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    assert page.evaluate("window.__puterSignIns") == 1
    assert page.evaluate("window.__puterCalls.length") == 0
    reply = ask(page, "Which debt payoff method fits my finances and why?")
    assert "avalanche" in reply and "$19,259.44" in reply
    assert page.locator(".engine-badge").inner_text() == "Grok AI"
    assert "verify" in page.locator(".answer-notice").inner_text()
    calls = page.evaluate("window.__puterCalls")
    assert len(calls) == 2 and all(c["model"] == "x-ai/grok-4-1-fast-non-reasoning" for c in calls)
    assert "19259.44" not in str(calls[0]) and "19259.44" in str(calls[1])
    assert calls[0]["max_tokens"] == 80 and calls[1]["max_tokens"] == 1100
    page.locator(".message-sources summary").click()
    assert "Cash and debt ledgers" in page.locator(".message-sources").inner_text()
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert page.locator(".engine-badge").inner_text() == "Grok AI"
    assert "avalanche" in page.locator(".chat-message.assistant").inner_text()
    assert (
        page.locator("#ai-status-button").get_attribute("data-connected") == "false"
    )  # stub is signed out again


def test_grok_refuses_unrelated_and_mixed_prompts_before_sharing_account_data(page):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    reply = ask(page, "What is my checking balance and tomorrow's weather?")
    assert "finances only" in reply and "weather is" not in reply
    assert page.locator(".engine-badge").inner_text() == "Finance-only"
    calls = page.evaluate("window.__puterCalls")
    assert len(calls) == 0  # Obvious mixed topics are rejected locally, even without AI.
    assert page.locator("#chat-send").is_enabled()
    assert "avalanche" in ask(page, "Help me compare debt payoff strategies.")
    assert page.evaluate("window.__puterCalls.length") == 2


@pytest.mark.parametrize("mode", ["quota", "bad_guard"])
def test_grok_provider_or_scope_failure_keeps_a_clearly_labeled_local_fallback(page, mode):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    page.evaluate("mode => window.__puterMode = mode", mode)
    reply = ask(page, "What is my checking balance?")
    assert "$19,259.44" in reply and "not an AI answer" in reply
    assert page.locator(".engine-badge").inner_text() == "Local finance engine"
    assert page.locator("#chat-send").is_enabled()
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert "not an AI answer" in page.locator(".answer-notice").inner_text()


def test_grok_never_bypasses_local_confirmations_or_renders_executable_html(page):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    ask(page, "I got paid five hundred dollars")
    assert page.locator("#chat-pending").is_visible()
    assert page.evaluate("window.__puterCalls.length") == 0
    page.locator("[data-confirm]").first.click()
    page.wait_for_selector("#chat-pending[hidden]", state="attached")
    assert "$19,759.44" in page.locator(".stat-value").first.inner_text()
    assert page.evaluate("window.__puterCalls.length") == 0
    page.evaluate(
        "window.__puterReply = '<img src=x onerror=window.__injected=1> Diversify rather than concentrate your investments.'"
    )
    assert "<img" in ask(page, "Explain diversification.")
    assert not page.locator(".chat-message.assistant img").count()
    assert page.evaluate("window.__injected") is None


def test_disconnecting_grok_cancels_late_output_and_keeps_chat_usable(page):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    page.evaluate("window.__puterMode = 'hold'")
    page.locator("#chat-input").fill("What is my checking balance?")
    page.locator("#chat-send").click()
    page.wait_for_function("typeof window.__releasePuter === 'function'")
    page.locator("#ai-status-button").click()
    page.locator('[data-action="ai-disconnect"]').click()
    page.wait_for_selector(".chat-message.assistant")
    page.evaluate("window.__releasePuter()")
    page.locator("#close-dialog").click()
    assert page.locator(".engine-badge").inner_text() == "Local finance engine"
    assert "not an AI answer" in page.locator(".answer-notice").inner_text()
    assert page.locator("#chat-send").is_enabled()
    assert "$19,259.44" in ask(page, "What is my checking balance?")
    assert page.evaluate("window.__puterCalls.length") == 2


def test_official_bundled_sdk_loads_only_after_consent_and_handles_blocked_popups(page):
    page.add_init_script("window.open = () => null;")
    open_workspace(page)
    assert page.evaluate("typeof window.puter") == "undefined"
    page.locator("#ai-status-button").click()
    page.locator("#ai-consent").check()
    page.locator("#ai-connect").click()
    page.wait_for_function(
        "document.querySelector('#ai-connection-status').textContent.includes('blocked')"
    )
    assert page.evaluate("typeof window.puter.ai.chat") == "function"
    assert page.locator("#ai-status-button").get_attribute("data-connected") == "false"
    assert page.locator("#ai-connect").is_enabled()
    assert "HTTPS tab" in page.locator("#ai-connection-status").inner_text()
    page.locator("#close-dialog").click()
    assert "$19,259.44" in ask(page, "What is my checking balance?")


def test_grok_settings_and_guidance_work_in_mobile_chat_without_overflow(page):
    page.add_init_script(PUTER_STUB)
    page.set_viewport_size({"width": 390, "height": 844})
    open_workspace(page)
    page.locator("#mobile-chat").click()
    connect_grok(page)
    assert "avalanche" in ask(page, "Help me plan a realistic debt repayment strategy.")
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    page.locator("#ai-status-button").click()
    assert page.locator('[data-action="ai-disconnect"]').is_visible()
    assert page.evaluate("document.body.scrollWidth <= innerWidth")


def test_disconnecting_before_context_arrives_never_sends_it_to_grok(page):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    pending, release = hold_workspace_response(page, "ai_context")
    page.locator("#chat-input").fill("What is my checking balance?")
    page.locator("#chat-send").click()
    page.wait_for_function("window.__heldResponse === true")
    assert pending and page.evaluate("window.__puterCalls.length") == 1
    page.locator("#ai-status-button").click()
    page.locator('[data-action="ai-disconnect"]').click()
    release()
    page.wait_for_selector(".chat-message.assistant")
    assert page.evaluate("window.__puterCalls.length") == 1
    assert page.locator(".engine-badge").inner_text() == "Local finance engine"
    assert "not an AI answer" in page.locator(".answer-notice").inner_text()


def test_grok_advice_and_followups_do_not_stage_a_described_gift_as_income(page):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    assert "avalanche" in ask(page, "I received $500 as a gift; should I save it or reduce debt?")
    assert not page.locator("#chat-pending").is_visible()
    assert "$19,259.44" in page.locator(".stat-value").first.inner_text()
    ask(page, "Explain that more simply.")
    calls = page.evaluate("window.__puterCalls")
    assert len(calls) == 4
    assert "gift" in calls[2]["messages"][1]["content"]
    assert any(
        m["role"] == "assistant" and "avalanche" in m["content"] for m in calls[3]["messages"]
    )
    assert page.locator(".engine-badge").all_inner_texts() == ["Grok AI", "Grok AI"]


def choose_person(page, who):
    page.wait_for_selector("#demo-person:not(:disabled)", timeout=45000)
    page.locator("#demo-person").select_option(who)
    page.locator("#demo-login-button").click()
    page.wait_for_selector(".stats-grid", timeout=45000)


def log_out(page):
    page.locator("#settings-button").click()
    page.locator('[data-action="logout"]').click()
    page.wait_for_selector("#demo-person:not(:disabled)", timeout=45000)
    assert page.locator("#demo-login").is_visible()
    assert not page.locator("#workspace-shell").is_visible()


def test_fake_login_is_explicit_and_logout_after_refresh_returns_people_dropdown(page):
    page.goto(URL)
    page.wait_for_selector("#demo-person:not(:disabled)", timeout=45000)
    assert page.locator("#demo-person option").count() == 5
    assert page.locator("#demo-login-button").is_disabled()
    assert not page.locator("#workspace-shell").is_visible()
    assert "simulated login" in page.locator("#demo-login-note").inner_text()
    assert not page.locator('input[type="password"]').count()
    page.locator("#demo-person").select_option("aisha")
    assert "Aisha Patel" in page.locator("#login-person-preview").inner_text()
    assert not page.locator(".stats-grid").count()  # Selecting is not yet a login.
    page.locator("#demo-login-button").click()
    page.wait_for_selector(".stats-grid")
    assert "$980.00" in page.locator(".stat-value").first.inner_text()
    assert "Aisha Patel" in page.locator(".sidebar-profile").inner_text()
    page.reload()
    page.wait_for_selector(".stats-grid")
    assert "$980.00" in page.locator(".stat-value").first.inner_text()
    log_out(page)
    assert page.locator("#demo-person option").count() == 5
    assert page.locator("#view-content").inner_text() == ""
    assert page.locator("#dialog-content").inner_text() == ""
    assert not page.locator(".chat-message").count()
    page.reload()
    page.wait_for_selector("#demo-person:not(:disabled)")
    assert not page.locator("#workspace-shell").is_visible()
    choose_person(page, "jordan")
    assert "$2,750.00" in page.locator(".stat-value").first.inner_text()


@pytest.mark.parametrize(
    "who,balance,level,rank",
    [
        ("maya", "$19,259.44", "Stable", 4),
        ("jordan", "$2,750.00", "Watch", 3),
        ("aisha", "$980.00", "High", 2),
        ("marcus", "$215.00", "Critical", 1),
    ],
)
def test_all_people_open_distinct_finances_and_explain_their_ranking(
    page, who, balance, level, rank
):
    open_workspace(page, who)
    assert balance in page.locator(".stat-value").first.inner_text()
    assert f"{level} · Priority {rank} of 4" in page.locator(".trouble-card h2").inner_text()
    page.locator('.trouble-card [data-view="insights"]').click()
    assert page.locator(".trouble-scale .selected").inner_text().startswith(f"{rank}. {level}")
    page.locator(".trouble-details summary").click()
    assert page.locator(".trouble-factor").count() == 6
    assert (
        "Safety" in page.locator(".trouble-method").inner_text()
        if who in {"aisha", "marcus"}
        else True
    )
    page.locator(".trouble-method [data-prompt]").click()
    page.wait_for_selector(".chat-message.assistant")
    reply = page.locator(".chat-message.assistant").last.inner_text()
    assert f"priority {rank} of 4" in reply and level in reply
    assert "Local finance engine" in reply
    assert not page.locator("#chat-pending").is_visible()
    page.locator('.trouble-method [data-action="open-plan"]').click()
    page.wait_for_selector(".plan-summary", timeout=30000)
    assert (
        "No money" in page.locator("#view-content").inner_text()
        or "preview" in page.locator("#view-content").inner_text().lower()
    )


def test_switching_profiles_keeps_confirmed_changes_but_cancels_pending_drafts(page):
    open_workspace(page)
    ask(page, "I got paid $123")
    page.locator('[data-confirm="Yes, confirm"]').click()
    page.wait_for_function(
        "document.querySelector('.stat-value').textContent.includes('19,382.44')"
    )
    ask(page, "I got paid $900")
    assert page.locator("#chat-pending").is_visible()
    page.locator("#chat-input").fill("A draft only for Maya")
    log_out(page)
    choose_person(page, "jordan")
    assert "$2,750.00" in page.locator(".stat-value").first.inner_text()
    assert page.locator("#chat-input").input_value() == ""
    assert not page.locator(".chat-message").count()
    assert not page.locator("#chat-pending").is_visible()
    assert "no pending" in ask(page, "Yes, confirm")
    log_out(page)
    choose_person(page, "maya")
    assert "$19,382.44" in page.locator(".stat-value").first.inner_text()
    assert page.locator(".chat-message").count() == 6
    assert not page.locator("#chat-pending").is_visible()
    page.locator("#settings-button").click()
    page.locator('[data-action="confirm-reset"]').click()
    page.locator('[data-action="reset-now"]').click()
    page.wait_for_selector(".chat-welcome")
    assert "$19,259.44" in page.locator(".stat-value").first.inner_text()


@pytest.mark.parametrize(
    "operation",
    ["chat", "transactions", "plan", "dashboard", "export", "stage_transaction", "simulate"],
)
def test_logout_discards_old_persons_delayed_transport_responses(page, operation):
    open_workspace(page)
    downloads = []
    page.on("download", lambda d: downloads.append(d.suggested_filename))
    if operation in {"plan", "simulate"}:
        page.locator('.main-nav [data-view="bills"]').click()
    if operation == "stage_transaction":
        page.locator('.main-nav [data-view="transactions"]').click()
        page.locator('[data-action="add-transaction"]').click()
        page.locator('#add-transaction-form [name="amount"]').fill("25")
        page.locator('#add-transaction-form [name="merchant"]').fill("Old profile only")
    pending, release = hold_workspace_response(page, operation)
    if operation == "chat":
        page.locator("#chat-input").fill("What is my checking balance?")
        page.locator("#chat-send").click()
    elif operation == "transactions":
        page.locator('.main-nav [data-view="transactions"]').click()
    elif operation == "plan":
        page.locator("#plan-form button").click()
    elif operation == "simulate":
        page.locator("#simulate-form button").click()
    elif operation == "dashboard":
        page.locator("#reporting-period").select_option("last_month")
    elif operation == "export":
        page.locator("#export-button").click()
    else:
        page.locator("#add-transaction-form button").last.click()
    page.wait_for_function("window.__heldResponse === true")
    assert pending
    if page.locator("#app-dialog").is_visible():
        page.locator("#close-dialog").click()
    log_out(page)
    choose_person(page, "marcus")
    release()
    page.unroute("**/component_server**")
    assert "$215.00" in page.locator(".stat-value").first.inner_text()
    assert page.locator("#reporting-period").input_value() == "month"
    assert not page.locator(".chat-message").count()
    assert not page.locator("#chat-pending").is_visible()
    assert page.locator("#chat-input").input_value() == ""
    assert page.locator("#chat-send").is_enabled()
    assert not page.locator("#toast-region .error").count()
    assert downloads == []
    assert "$215.00" in ask(page, "What is my checking balance?")


@pytest.mark.parametrize("phase", ["context", "inference"])
def test_logout_revokes_ai_sharing_cancels_output_and_requires_new_profile_consent(page, phase):
    page.add_init_script(PUTER_STUB)
    open_workspace(page)
    connect_grok(page)
    release = None
    if phase == "context":
        _, release = hold_workspace_response(page, "ai_context")
    else:
        page.evaluate("window.__puterMode='hold'")
    page.locator("#chat-input").fill("Explain my financial trouble ranking.")
    page.locator("#chat-send").click()
    page.wait_for_function(
        "window.__heldResponse === true"
        if release
        else "typeof window.__releasePuter === 'function'"
    )
    log_out(page)
    choose_person(page, "marcus")
    if release:
        release()
    else:
        page.evaluate("window.__releasePuter()")
    assert page.locator("#ai-status-button").get_attribute("data-connected") == "false"
    assert page.evaluate("sessionStorage.getItem('solvra.ai-consent.v1')") == "no"
    assert page.locator("#chat-send").is_enabled()
    assert not page.locator(".chat-message").count()
    assert "$215.00" in ask(page, "What is my checking balance?")
    assert page.evaluate("window.__puterCalls.length") == (1 if phase == "context" else 2)
    assert all("Marcus Bennett" not in str(call) for call in page.evaluate("window.__puterCalls"))


def test_profile_help_reminders_account_links_copy_chat_download_and_clear_controls(page):
    page.add_init_script(
        "window.__copied=''; Object.defineProperty(navigator,'clipboard',{value:{writeText: async text => {window.__copied=text;}}});"
    )
    open_workspace(page, "aisha")
    page.locator("#profile-button").click()
    assert "Aisha Patel" in page.locator("#dialog-title").inner_text()
    page.locator('[data-action="profile-settings"]').click()
    assert "Log out" in page.locator("#dialog-content").inner_text()
    page.locator('[data-action="settings-plan"]').click()
    assert page.locator("#plan-reserve").input_value() == "500"
    page.locator("#workspace-switch").click()
    assert "Four separate ledgers" in page.locator("#dialog-content").inner_text()
    page.locator("#close-dialog").click()
    page.locator("#notifications-button").click()
    page.locator("#dialog-content [data-bill]").first.click()
    assert page.locator("#dialog-title").inner_text() == "Electricity"
    page.locator("[data-record-payment]").last.click()
    page.locator('#record-payment-form [name="amount"]').fill("10")
    page.locator("#record-payment-form button").last.click()
    page.wait_for_selector("#chat-pending:not([hidden])")
    page.locator('[data-confirm="No, cancel"]').click()
    page.wait_for_selector("#chat-pending[hidden]", state="attached")
    page.locator('[data-account="Savings"]').click()
    page.wait_for_selector("#tx-results [data-tx]")
    assert page.locator("#tx-account").input_value() == "Savings"
    page.locator("#tx-results [data-tx]").first.press("Enter")
    assert "Savings" in page.locator("#dialog-content").inner_text()
    page.locator("#close-dialog").click()
    reply = ask(page, "What is my checking balance?")
    page.locator("[data-copy-message]").last.click()
    assert "$980.00" in page.evaluate("window.__copied")
    page.locator("#chat-options").click()
    with page.expect_download() as download:
        page.locator('[data-action="download-chat"]').click()
    assert "$980.00" in Path(download.value.path()).read_text()
    assert "checking" in reply.lower()
    page.locator('[data-action="clear-chat"]').click()
    page.wait_for_selector(".chat-welcome")
    assert not page.locator(".chat-message").count()


def test_mobile_login_profile_switch_and_full_triage_do_not_overflow(page):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(URL)
    page.wait_for_selector("#demo-person:not(:disabled)", timeout=45000)
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    choose_person(page, "marcus")
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    page.locator('.trouble-card [data-view="insights"]').click()
    page.locator(".trouble-details summary").click()
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    page.locator("#mobile-menu").click()
    log_out(page)
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    choose_person(page, "maya")
    assert "$19,259.44" in page.locator(".stat-value").first.inner_text()


@pytest.mark.parametrize("who,label,rank", [("jordan", "Watch", 3), ("marcus", "Critical", 1)])
def test_grok_context_from_ranking_button_is_selected_person_only(page, who, label, rank):
    import json

    page.add_init_script(PUTER_STUB)
    open_workspace(page, who)
    connect_grok(page)
    page.evaluate(
        "text => window.__puterReply=text",
        f"Your urgency is {label}, priority {rank} of 4. Protect essentials and verify the recorded provider terms.",
    )
    page.locator('.trouble-card [data-view="insights"]').click()
    page.locator(".trouble-method [data-prompt]").click()
    page.wait_for_selector(".chat-message.assistant")
    assert label in page.locator(".chat-message.assistant").inner_text()
    assert page.locator(".engine-badge").inner_text() == "Grok AI"
    calls = page.evaluate("window.__puterCalls")
    assert len(calls) == 2
    facts = json.loads(
        next(
            m["content"].split("\n", 1)[1]
            for m in calls[1]["messages"]
            if m["content"].startswith("SERVER FINANCIAL CONTEXT")
        )
    )
    assert facts["selected_person"]["id"] == who
    assert facts["financial_trouble"]["rank"] == rank
    assert facts["financial_trouble"]["label"] == label
    assert len(facts["financial_trouble"]["factors"]) == 6
    assert "Maya Chen" not in str(calls)
    assert "19259.44" not in str(calls)


def test_login_error_and_expired_session_return_to_safe_recoverable_login(page):
    page.goto(URL)
    page.wait_for_selector("#demo-person:not(:disabled)", timeout=45000)
    failed = []

    def fail_once(route):
        op = route.request.post_data_json.get("data", {}).get("op")
        if op == "login" and not failed:
            failed.append(op)
            route.fulfill(json={"error": "Demo could not open. Try again."})
        else:
            route.continue_()

    page.route("**/component_server**", fail_once)
    page.locator("#demo-person").select_option("aisha")
    page.locator("#demo-login-button").click()
    page.wait_for_function(
        "document.querySelector('#demo-login-status').textContent.includes('could not open')"
    )
    assert page.locator("#demo-login-button").is_enabled()
    assert not page.locator("#workspace-shell").is_visible()
    page.locator("#demo-login-button").click()
    page.wait_for_selector(".stats-grid")
    assert "$980.00" in page.locator(".stat-value").first.inner_text()
    page.unroute("**/component_server**")

    def expire(route):
        if route.request.post_data_json.get("data", {}).get("op") == "dashboard":
            route.fulfill(
                json={
                    "error": "Your demo session expired. Choose a person again.",
                    "code": "login_required",
                }
            )
        else:
            route.continue_()

    page.route("**/component_server**", expire)
    page.locator("#reporting-period").select_option("last_month")
    page.wait_for_selector("#demo-person:not(:disabled)")
    assert not page.locator("#workspace-shell").is_visible()
    assert page.locator("#view-content").inner_text() == ""
    assert "expired" in page.locator("#demo-login-status").inner_text()
    page.unroute("**/component_server**")
    choose_person(page, "marcus")
    assert "$215.00" in page.locator(".stat-value").first.inner_text()
    assert page.locator("#reporting-period").is_enabled()


@pytest.mark.parametrize("clear", ["reset", "clear-chat"])
def test_reset_and_clear_remove_old_inline_voice_turns_and_drafts(page, clear):
    page.add_init_script(RECOGNIZER)
    open_workspace(page, "aisha")
    page.locator("#voice-launch").click()
    page.wait_for_function("window.__recognizer?.started")
    emit_transcript(page, "What is my checking balance?")
    page.wait_for_selector(".chat-message.assistant")
    assert "$980.00" in page.locator(".chat-message.assistant").inner_text()
    if clear == "reset":
        page.locator("#settings-button").click()
        page.locator('[data-action="confirm-reset"]').click()
        page.locator('[data-action="reset-now"]').click()
    else:
        page.locator("#chat-options").click()
        page.locator('[data-action="clear-chat"]').click()
    page.wait_for_selector(".chat-welcome")
    assert page.locator("#chat-input").input_value() == ""
    assert page.locator("#inline-voice-status").is_hidden()
    assert page.locator(".chat-message").count() == 0
