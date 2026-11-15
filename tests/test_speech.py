"""Speech fidelity, bounded local inference, model setup, and session authorization."""

import base64
import hashlib
import io
import os
import tarfile
import wave

import numpy as np
import pytest

import solvra_speech as speech
import solvra_workspace as workspace


@pytest.mark.parametrize(
    "amount,words",
    [
        ("$0.00", "zero dollars"),
        ("$0.50", "fifty cents"),
        ("$1.01", "one dollar and one cent"),
        ("-$19.99", "minus nineteen dollars and ninety-nine cents"),
        (
            "$19,259.44",
            "nineteen thousand, two hundred and fifty-nine dollars and forty-four cents",
        ),
    ],
)
def test_money_is_exact_and_pronounceable(amount, words):
    assert speech.speech_text(amount) == words + "."


def test_speech_preparation_dates_percentages_links_and_idempotence():
    text = "**Electricity** is $148.60, due Nov 16.\n• [APR](https://example.test) is 20.5%."
    spoken = speech.speech_text(text)
    assert "one hundred and forty-eight dollars and sixty cents" in spoken
    assert "November sixteenth" in spoken and "twenty point five percent" in spoken
    assert "https" not in spoken and "*" not in spoken and "•" not in spoken
    assert speech.speech_text(spoken) == spoken
    assert "December first, twenty twenty-six" in speech.speech_text("2026-12-01")


def test_chunking_never_loses_words_or_cents():
    text = (
        "Checking is $19,259.44. Savings is $7,740.00. "
        + "We can review your bills together. " * 15
    )
    chunks = speech.speech_chunks(text)
    assert " ".join(chunks) == speech.speech_text(text.strip())
    assert all(0 < len(chunk) <= 300 for chunk in chunks)
    assert "forty-four cents" in chunks[0]
    assert len(chunks[0]) < 120


@pytest.fixture
def session():
    session = workspace.workspace_action({"op": "login", "profile_id": "maya"})
    yield session
    workspace._SESSIONS.pop(session["session"], None)


def test_speech_reads_only_a_server_owned_answer_or_fixed_preview(session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        workspace, "synthesize", lambda text, *args: calls.append(text) or {"audio": "test"}
    )
    reply = workspace.chat_turn(
        {"session": session["session"], "text": "What is my checking balance?"}
    )
    result = workspace.workspace_action(
        {
            "op": "speech",
            "session": session["session"],
            "message_id": reply["message_id"],
            "text": "Client supplied text must not be spoken",
            "index": 0,
        }
    )
    assert result["chunks"] == len(reply["speech_chunks"])
    assert calls == [reply["speech_chunks"][0]]
    unauthorized = workspace.workspace_action(
        {
            "op": "speech",
            "session": session["session"],
            "message_id": "not-an-answer",
            "text": "arbitrary",
        }
    )
    assert "error" in unauthorized and len(calls) == 1
    assert "error" in workspace.workspace_action(
        {"op": "speech", "session": "expired", "preview": True}
    )
    preview = workspace.workspace_action(
        {"op": "speech", "session": session["session"], "preview": True}
    )
    assert preview["chunks"] and calls[-1] == speech.speech_chunks(speech.PREVIEW)[0]
    restored = workspace.workspace_action({"op": "bootstrap", "session": session["session"]})
    assert restored["messages"][-1]["id"] == reply["message_id"]


def test_another_session_cannot_read_private_answer_audio(session, monkeypatch):
    reply = workspace.chat_turn(
        {"session": session["session"], "text": "What is my checking balance?"}
    )
    other = workspace.workspace_action({"op": "login", "profile_id": "maya"})
    try:
        monkeypatch.setattr(
            workspace, "synthesize", lambda *args: pytest.fail("Unauthorized synthesis")
        )
        assert "error" in workspace.workspace_action(
            {
                "op": "speech",
                "session": other["session"],
                "message_id": reply["message_id"],
            }
        )
    finally:
        workspace._SESSIONS.pop(other["session"], None)


def test_pcm_output_and_small_cache(monkeypatch):
    calls = []

    class Model:
        def create(self, text, **options):
            calls.append(options)
            return np.sin(np.arange(24000, dtype=np.float32) / 12) * 0.2, 24000

    monkeypatch.setattr(speech, "_MODEL", Model())
    speech._render.cache_clear()
    try:
        first = speech.synthesize("Your next bill is due soon.", "bf_emma", 0.9)
        assert speech.synthesize("Your next bill is due soon.", "bf_emma", 0.9) == first
        assert len(calls) == 1 and calls[0]["lang"] == "en-gb" and calls[0]["speed"] == 0.9
        with wave.open(io.BytesIO(base64.b64decode(first["audio"]))) as audio:
            assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (
                1,
                2,
                24000,
            )
            assert audio.getnframes() == 24000
        assert first["engine"] == "Kokoro neural" and first["duration"] == 1
        assert speech._render.cache_info().maxsize == 8
    finally:
        speech._render.cache_clear()


@pytest.mark.parametrize(
    "text,voice,speed",
    [
        ("", "af_heart", 1),
        ("x" * 601, "af_heart", 1),
        ("Hello", "unknown", 1),
        ("Hello", "af_heart", float("nan")),
        ("Hello", "af_heart", 9),
    ],
)
def test_invalid_synthesis_never_reaches_model(monkeypatch, text, voice, speed):
    monkeypatch.setattr(speech, "_render", lambda *args: pytest.fail("Invalid inference"))
    with pytest.raises(ValueError):
        speech.synthesize(text, voice, speed)


def test_missing_models_do_not_download_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLVRA_TTS_DIR", str(tmp_path))
    monkeypatch.setenv("SOLVRA_TTS_AUTO_DOWNLOAD", "0")
    monkeypatch.setattr(speech, "_download", lambda *args: pytest.fail("Unexpected download"))
    with pytest.raises(ValueError, match="files are missing"):
        speech.prepare_voice()


def test_model_package_download_is_pinned(monkeypatch, tmp_path):
    monkeypatch.setattr(
        speech.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"not model data")
    )
    with pytest.raises(ValueError, match="integrity check"):
        speech._download("model", tmp_path / "model.tgz")


def test_setup_reassembles_only_expected_files_and_reuses_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLVRA_TTS_DIR", str(tmp_path))
    monkeypatch.setenv("SOLVRA_TTS_AUTO_DOWNLOAD", "1")
    pieces = [b"model data " + bytes([i]) for i in range(6)]
    monkeypatch.setattr(speech, "MODEL_SHA", hashlib.sha256(b"".join(pieces)).hexdigest())
    downloads = []

    def download(kind, destination):
        downloads.append(kind)
        with tarfile.open(destination, "w:gz") as archive:
            files = (
                {f"package/kokoro-q8.part{i}.bin": part for i, part in enumerate(pieces)}
                if kind == "model"
                else {
                    **{f"package/voices/{name}.bin": bytes(522240) for name in speech.VOICES},
                    "package/LICENSE": b"Apache-2.0",
                }
            )
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    monkeypatch.setattr(speech, "_download", download)
    assert speech.prepare_voice() == tmp_path
    assert speech.prepare_voice() == tmp_path
    assert downloads == ["model", "voices"]
    assert (tmp_path / "kokoro.onnx").read_bytes() == b"".join(pieces)
    with np.load(tmp_path / "voices.npz", allow_pickle=False) as voices:
        assert set(voices.files) == set(speech.VOICES)
        assert voices["af_heart"].shape == (510, 1, 256)
    assert not list(tmp_path.glob("voice-*"))


@pytest.mark.skipif(
    os.environ.get("SOLVRA_TEST_NEURAL") != "1",
    reason="Set SOLVRA_TEST_NEURAL=1 after preparing model assets",
)
def test_real_neural_model_produces_playable_audio():
    result = speech.synthesize("Let's work through this together.", "af_heart", 1)
    with wave.open(io.BytesIO(base64.b64decode(result["audio"]))) as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        assert audio.getframerate() == 24000
        assert len(samples) > 24000
        assert float(np.sqrt(np.mean(samples.astype(float) ** 2))) > 100


def test_speech_inference_never_holds_the_account_lock(session, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    started, release = threading.Event(), threading.Event()

    def slow_render(*args):
        started.set()
        assert release.wait(5)
        return {"audio": "test"}

    monkeypatch.setattr(workspace, "synthesize", slow_render)
    with ThreadPoolExecutor(max_workers=2) as pool:
        speech_request = pool.submit(
            workspace.workspace_action,
            {"op": "speech", "session": session["session"], "preview": True},
        )
        assert started.wait(2)
        try:
            chat = pool.submit(
                workspace.chat_turn,
                {"session": session["session"], "text": "What is my checking balance?"},
            )
            assert "$19,259.44" in chat.result(timeout=1.5)["reply"]
        finally:
            release.set()
        assert speech_request.result(timeout=2)["audio"] == "test"
