"""Offline, bounded audio decoding with an optional locally installed Whisper model.

PocketSphinx ships an English model in its wheel: the fallback works without an
API key, a model download, or internet access. Its transcripts must be reviewed.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
MAX_SECONDS = 45
MAX_BYTES = 15 * 1024 * 1024
ALLOWED_SUFFIXES = {".webm", ".ogg", ".wav", ".mp3", ".mp4", ".m4a", ".flac", ".aac"}
_MODEL_LOCK = threading.Lock()
_WHISPER = None
_WHISPER_FAILED = ""
_WHISPER_INITIAL_PROMPT = (
    "This is an English personal-finance question about checking, savings, bills, rent, "
    "utilities, credit cards, loans, budgets, income, and payment plans."
)


def capabilities() -> dict:
    path = os.environ.get("SOLVRA_WHISPER_MODEL", "").strip()
    whisper = bool(
        path
        and path != _WHISPER_FAILED
        and (Path(path) / "model.bin").is_file()
        and (Path(path) / "config.json").is_file()
        and importlib.util.find_spec("faster_whisper")
        and importlib.util.find_spec("av")
    )
    offline = bool(importlib.util.find_spec("pocketsphinx") and importlib.util.find_spec("av"))
    return {
        "offline": offline or whisper,
        "engine": "Local Whisper" if whisper else "Offline English",
        "review_required": True,
        "max_seconds": MAX_SECONDS,
        "note": "Audio is processed on this app's server. Offline transcripts can be inaccurate; review before sending.",
    }


def decode_pcm(path: str) -> np.ndarray:
    import av

    chunks = []
    count = 0
    try:
        with av.open(path) as container:
            if not container.streams.audio:
                raise ValueError("This file has no audio track.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                for pcm in resampler.resample(frame):
                    count += pcm.samples
                    if count > 16000 * MAX_SECONDS:
                        raise ValueError(f"Keep recordings under {MAX_SECONDS} seconds.")
                    chunks.append(pcm.to_ndarray().reshape(-1).copy())
            for pcm in resampler.resample(None):
                count += pcm.samples
                if count > 16000 * MAX_SECONDS:
                    raise ValueError(f"Keep recordings under {MAX_SECONDS} seconds.")
                chunks.append(pcm.to_ndarray().reshape(-1).copy())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "That audio file could not be decoded. Try WAV, MP3, M4A, or a new recording."
        ) from exc
    if not chunks or count < 1600:
        raise ValueError("The recording is too short. Speak for at least a second, then stop.")
    audio = np.concatenate(chunks).astype(np.int16)
    if np.sqrt(np.mean((audio.astype(np.float32) / 32768) ** 2)) < 0.0006:
        raise ValueError(
            "The recording is silent. Check your microphone or select a different input."
        )
    return audio


def trim_silence(audio: np.ndarray | bytes, threshold: float = 0.003, pad_ms: int = 250) -> np.ndarray | bytes:
    """Trim leading and trailing silence to accelerate speech decoding and reduce noise."""
    is_bytes = isinstance(audio, (bytes, bytearray))
    arr = np.frombuffer(audio, dtype=np.int16) if is_bytes else audio
    if len(arr) <= 320:
        return audio
    abs_audio = np.abs(arr.astype(np.float32) / 32768.0)
    window_size = 320
    stride = 160
    energy = np.array([
        np.mean(abs_audio[i : i + window_size])
        for i in range(0, len(abs_audio) - window_size, stride)
    ])
    voiced = np.where(energy > threshold)[0]
    if len(voiced) == 0:
        return audio
    start_frame = max(0, int(voiced[0] * stride - (pad_ms * 16)))
    end_frame = min(len(arr), int((voiced[-1] * stride) + window_size + (pad_ms * 16)))
    trimmed = arr[start_frame:end_frame]
    return trimmed.tobytes() if is_bytes else trimmed


def transcribe(path: str) -> str:
    global _WHISPER, _WHISPER_FAILED
    file = Path(path)
    if not file.is_file() or file.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("Choose an audio recording (WAV, WebM, MP3, M4A, OGG, or FLAC).")
    if not 0 < file.stat().st_size <= MAX_BYTES:
        raise ValueError("Choose a non-empty recording smaller than 15 MB.")
    audio = trim_silence(decode_pcm(str(file)))
    config = capabilities()
    if config["engine"] == "Local Whisper":
        try:
            from faster_whisper import WhisperModel

            with _MODEL_LOCK:
                if _WHISPER is None:
                    _WHISPER = WhisperModel(
                        os.environ["SOLVRA_WHISPER_MODEL"],
                        device="cpu",
                        compute_type="int8",
                        local_files_only=True,
                    )
                # Favor a careful final transcript over low-latency partial text.
                # This path is used only with an explicitly provisioned local model;
                # it never downloads a model or sends the recording to a provider.
                segments, _ = _WHISPER.transcribe(
                    audio.astype(np.float32) / 32768,
                    language="en",
                    beam_size=5,
                    best_of=5,
                    temperature=0,
                    condition_on_previous_text=False,
                    initial_prompt=_WHISPER_INITIAL_PROMPT,
                    vad_filter=True,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            # A missing/corrupt optional model must not disable the bundled engine.
            log.warning("Local Whisper failed; falling back to offline English.", exc_info=True)
            _WHISPER_FAILED = os.environ.get("SOLVRA_WHISPER_MODEL", "").strip()
            _WHISPER = None
            config = capabilities()
    if config["engine"] != "Local Whisper" and config["offline"]:
        from pocketsphinx import Decoder

        # Decoder state is per request; don't mix two users' audio streams.
        with _MODEL_LOCK:
            decoder = Decoder(loglevel="ERROR", samprate=16000)
            decoder.start_utt()
            decoder.process_raw(audio.tobytes(), False, True)
            decoder.end_utt()
            hypothesis = decoder.hyp()
            text = hypothesis.hypstr.strip() if hypothesis else ""
    elif not config["offline"]:
        raise ValueError(
            "Offline transcription is not installed. Install pocketsphinx and av, or use browser recognition."
        )
    if not text:
        raise ValueError(
            "No clear words were detected. Move closer, check the input meter, and try again."
        )
    return text
