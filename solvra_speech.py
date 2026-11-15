"""Local neural read-aloud. Only pinned model assets are downloaded, never account text.

Run ``python -m solvra_speech`` to prepare the voice before starting the app.
The same lazy setup runs on first read-aloud unless SOLVRA_TTS_AUTO_DOWNLOAD=0.
"""

from __future__ import annotations

import base64
import calendar
import datetime as dt
import hashlib
import importlib.util
import io
import math
import os
import re
import tarfile
import tempfile
import textwrap
import threading
import time
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from num2words import num2words

VOICES = {
    "af_heart": "Heart · warm, US",
    "af_bella": "Bella · soft, US",
    "am_michael": "Michael · calm, US",
    "bf_emma": "Emma · warm, UK",
}
PREVIEW = "Let's take this one step at a time. Your next bill is $148.60, due November 16. We can look at your spending, or work through a plan together."
MODEL_SHA = "fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478"
PACKAGES = {
    "model": (
        "kokoro-q8-shards/-/kokoro-q8-shards-1.0.0.tgz",
        "94b79d3f877a5f6d1f0b8b081fd2b7d2f4f33cefb1210400d2cf67431f8d57b8",
    ),
    "voices": (
        "kokoro-js/-/kokoro-js-1.2.1.tgz",
        "1f0d0383ef0349af0bd9440d81dc12abbea3a5392eb645283eda876f537f5860",
    ),
}
_LOCK = threading.RLock()
_MODEL = None
_MONTHS = {
    name.lower(): i
    for i in range(1, 13)
    for name in (calendar.month_name[i], calendar.month_abbr[i])
}


def model_dir() -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return Path(os.environ.get("SOLVRA_TTS_DIR", str(cache / "solvra" / "tts")))


def capabilities() -> dict:
    directory = model_dir()
    return {
        "available": importlib.util.find_spec("kokoro_onnx") is not None,
        "ready": all((directory / name).is_file() for name in ("kokoro.onnx", "voices.npz")),
        "engine": "Kokoro · local neural voice",
        "voices": [{"id": key, "label": label} for key, label in VOICES.items()],
        "preview": {"preview": True, "speech_chunks": speech_chunks(PREVIEW)},
    }


def speech_text(text: str) -> str:
    """Turn visual finance answers into exact, pronounceable sentences, not table narration."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text or ""))
    text = re.sub(r"(?m)^\s*(?:[•*\-]|\d+[.)])\s+", "", text)
    text = re.sub(r"[*_`#>|]", "", text).replace("&", " and ")

    def currency(match):
        digits = match[2].replace(",", "").split(".")
        dollars, cents = (
            int(digits[0]),
            int((digits[1] if len(digits) > 1 else "").ljust(2, "0")),
        )
        parts = (
            [f"{num2words(dollars)} dollar{'s' if dollars != 1 else ''}"]
            if dollars or not cents
            else []
        )
        if cents:
            parts.append(f"{num2words(cents)} cent{'s' if cents != 1 else ''}")
        return ("minus " if match[1] else "") + " and ".join(parts)

    def iso_date(match):
        try:
            date = dt.date.fromisoformat(match[0])
            return (
                f"{date:%B} {num2words(date.day, to='ordinal')}, {num2words(date.year, to='year')}"
            )
        except ValueError:
            return match[0]

    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", iso_date, text)
    text = re.sub(r"(-?)\$\s*(\d[\d,]*(?:\.\d{1,2})?)", currency, text)
    text = re.sub(
        rf"\b({'|'.join(_MONTHS)})\.?\s+(\d{{1,2}})\b",
        lambda m: (
            f"{calendar.month_name[_MONTHS[m[1].lower()]]} {num2words(int(m[2]), to='ordinal')}"
        ),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(\d+(?:\.\d+)?)%", lambda m: f"{num2words(m[1])} percent", text)
    for pattern, replacement in {
        r"\bAPR\b": "A P R",
        r"\bCSV\b": "C S V",
        r"\bvs\.?\s": "compared with ",
        r"[—–]": ", ",
        r"\s/\s": " or ",
    }.items():
        text = re.sub(pattern, replacement, text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    return " ".join(line if line[-1:] in ".!?:;" else line + "." for line in lines)


def speech_chunks(text: str) -> list[str]:
    """Keep sentences and money intact; a short first sentence reduces initial latency."""
    sentences = re.split(r"(?<=[.!?])\s+", speech_text(text))
    chunks = []
    for sentence in sentences:
        for part in textwrap.wrap(sentence, 300, break_long_words=False, break_on_hyphens=False):
            if len(chunks) > 1 and len(chunks[-1]) + len(part) < 280:
                chunks[-1] += " " + part
            else:
                chunks.append(part)
    return chunks


def _sha(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _download(kind: str, destination: Path) -> None:
    suffix, expected = PACKAGES[kind]
    request = urllib.request.Request(
        "https://registry.npmjs.org/" + suffix,
        headers={"User-Agent": "Solvra-local-voice/1"},
    )
    deadline, size = time.monotonic() + 150, 0
    with (
        urllib.request.urlopen(request, timeout=25) as response,
        destination.open("wb") as file,
    ):
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 110 * 1024 * 1024 or time.monotonic() > deadline:
                raise ValueError("The voice download exceeded its size or time limit.")
            file.write(chunk)
    if _sha(destination) != expected:
        raise ValueError("The downloaded voice failed its integrity check. Please try again.")


def prepare_voice() -> Path:
    """Install verified data atomically. Never execute JavaScript from model packages."""
    directory = model_dir()
    with _LOCK:
        model, voices = directory / "kokoro.onnx", directory / "voices.npz"
        if model.is_file() and voices.is_file() and _sha(model) == MODEL_SHA:
            return directory
        if os.environ.get("SOLVRA_TTS_AUTO_DOWNLOAD", "1") == "0":
            raise ValueError(
                "Natural voice files are missing. Run python -m solvra_speech, or choose Device voice in settings."
            )
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="voice-", dir=directory) as staging:
            staging = Path(staging)
            for kind in PACKAGES:
                package = staging / (kind + ".tgz")
                _download(kind, package)
                with tarfile.open(package) as archive:
                    if kind == "model":
                        with (staging / "kokoro.onnx").open("wb") as file:
                            for i in range(6):
                                member = archive.getmember(f"package/kokoro-q8.part{i}.bin")
                                if not member.isfile() or member.size > 20 * 1024 * 1024:
                                    raise ValueError("Unexpected voice model data.")
                                file.write(archive.extractfile(member).read())
                    else:
                        arrays = {}
                        for name in VOICES:
                            member = archive.getmember(f"package/voices/{name}.bin")
                            if not member.isfile() or member.size != 522240:
                                raise ValueError("Unexpected voice style data.")
                            arrays[name] = np.frombuffer(
                                archive.extractfile(member).read(), dtype="<f4"
                            ).reshape(510, 1, 256)
                        np.savez(staging / "voices.npz", **arrays)
                        (staging / "LICENSE").write_bytes(
                            archive.extractfile("package/LICENSE").read()
                        )
            if _sha(staging / "kokoro.onnx") != MODEL_SHA:
                raise ValueError("The neural model failed its integrity check.")
            for name in ("kokoro.onnx", "voices.npz", "LICENSE"):
                (staging / name).replace(directory / name)
        return directory


@lru_cache(maxsize=8)
def _render(text: str, voice: str, speed: float) -> dict:
    global _MODEL
    import onnxruntime as rt
    from kokoro_onnx import Kokoro

    with _LOCK:
        if _MODEL is None:
            directory = prepare_voice()
            options = rt.SessionOptions()
            options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
            session = rt.InferenceSession(
                str(directory / "kokoro.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            _MODEL = Kokoro.from_session(session, str(directory / "voices.npz"))
        samples, rate = _MODEL.create(
            text,
            voice=voice,
            speed=speed,
            lang="en-gb" if voice.startswith("b") else "en-us",
            sentence_pause=0.22,
            clause_pause=0.08,
        )
    if not len(samples) or len(samples) > rate * 60 or not np.isfinite(samples).all():
        raise ValueError("The natural voice could not generate this passage.")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return {
        "audio": base64.b64encode(output.getvalue()).decode(),
        "mime": "audio/wav",
        "duration": round(len(samples) / rate, 2),
        "engine": "Kokoro neural",
    }


def synthesize(text: str, voice: str = "af_heart", speed: float = 1.0) -> dict:
    if voice not in VOICES or not math.isfinite(float(speed)) or not 0.85 <= float(speed) <= 1.15:
        raise ValueError("Choose an available voice and a pace between 0.85 and 1.15.")
    if not isinstance(text, str) or not text.strip() or len(text) > 600:
        raise ValueError("Choose a short assistant passage to read aloud.")
    return _render(text, voice, round(float(speed), 2)).copy()


if __name__ == "__main__":
    print(f"Natural voice is ready in {prepare_voice()}")
