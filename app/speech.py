"""Speech service (task 8.1, RFC C4 + §4 steps 2-3, file 05 §6 + D10). Choices: DECISIONS.md D-035.

One voice note in, one transcript (or a fixed reason it has none) out, plus stt_meta for message_log:
  1. pre-checks before any STT call: < 1 s -> TOO_SHORT; energy/silence check -> SILENT (no STT request, file 09 R-24);
     > 120 s -> only the first 120 s are sent and the reply says so;
  2. chain: Scribe v2 with gazetteer keyterms -> (error / timeout 6 s / empty / garbage) -> Gemini audio -> still failing ->
     "likh kar bhej dein" + an error log line (the alert);
  3. sanity checks on each transcript: empty, implausible words per second, repeated-token loops, script outside
     {Latin, Urdu-Arabic, Devanagari}.
A missing API key or any HTTP error counts as that provider failing; nothing here raises to the worker, so a failed STT never
re-runs the turn (each re-run would spend free-tier quota). Transcripts and vendor error bodies are never logged.
Free-tier vendors only ever see team/synthetic audio in FYP-I (file 07 §3, file 09 R-23).
"""
import base64
import functools
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import uuid

import numpy as np
import soundfile as sf

from mandi import gazetteer

log = logging.getLogger(__name__)

MIN_S, MAX_S = 1.0, 120.0  # file 05 §6
TIMEOUT_S = 6.0            # per STT call (file 05 §6)
FRAME_S = 0.02
# A note is SILENT when < 2% of its 20 ms frames are louder than -25 dBFS: a covered mic hums but never gets loud, speech
# always peaks. Calibrated on 4 live WhatsApp notes (2026-11-27, D-035): covered-mic silence 0.3% (max -23 dBFS), the
# weakest speech note (one short word in 6 s) 5.8%, the others 47-54% (speech max -6..-11 dBFS).
# shortcut: one silent note and one phone so far; re-check on the 6.4 silent (5 s, 20 s) + music controls before G2
ACTIVE_DBFS, MIN_ACTIVE = -25.0, 0.02
MAX_WPS = 6.0              # Urdu/Punjabi speech runs ~2-4 words per second; more means invented text
SCRIBE_URL, SCRIBE_MODEL = "https://api.elevenlabs.io/v1/speech-to-text", "scribe_v2"  # D10; a model change is a decision
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DEFAULT = "gemini-flash-latest"  # file 05 P1 alias; GEMINI_MODEL overrides
GEMINI_PROMPT = ("Transcribe this voice note exactly as spoken, in the script the speaker would write it (Urdu script or Roman "
                 "Urdu, English words as English). Output only the transcript. If there is no speech, output nothing.")

# Reply text (plain strings until the 9.1 renderer owns all reply text). SILENT_TEXT is file 10 scenario 5's wording.
TOO_SHORT_TEXT = "Paigham bohat chhota tha, dobara bhejein."
SILENT_TEXT = "Awaaz nahi aayi, dobara bhejein."
FAILED_TEXT = "Awaaz samajh nahi aayi, likh kar bhej dein."
TRUNCATED_NOTE = "(Sirf pehle 2 minute sune gaye.)"


class STTError(Exception):
    """One provider failed (HTTP status, timeout, bad body). The message never holds audio or transcript text."""


def precheck(path: str) -> tuple[str, dict, np.ndarray | None, int]:
    """(verdict OK|TOO_SHORT|SILENT|UNREADABLE, meta, first <= 120 s of mono audio, sample rate). Decodes at most 120 s."""
    try:
        info = sf.info(path)
        dur = float(info.duration)
        meta = {"duration_s": round(dur, 2)}
        if dur < MIN_S:
            return "TOO_SHORT", meta, None, 0
        data, sr = sf.read(path, frames=int(min(dur, MAX_S) * info.samplerate), dtype="float32", always_2d=True)
    except Exception as e:  # any decode failure: no STT call, and never raise to the worker (a retry would re-download)
        return "UNREADABLE", {"error": type(e).__name__}, None, 0
    mono = data.mean(axis=1)
    n = max(1, int(sr * FRAME_S))
    k = len(mono) // n
    if k == 0:
        return "TOO_SHORT", meta, None, 0
    rms = np.sqrt(np.mean(mono[: k * n].reshape(k, n) ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-10)
    active = float(np.mean(db > ACTIVE_DBFS))
    p10, p50, p95 = np.percentile(db, [10, 50, 95])
    # the levels go into stt_meta so the next calibration (6.4 controls) needs no re-download: audio is deleted after the turn
    meta.update(active_ratio=round(active, 3), p10_dbfs=round(float(p10), 1), p50_dbfs=round(float(p50), 1),
                p95_dbfs=round(float(p95), 1), max_dbfs=round(float(db.max()), 1))
    return ("SILENT" if active < MIN_ACTIVE else "OK"), meta, mono, sr


@functools.cache
def keyterms() -> tuple[str, ...]:
    """Crop and place names + common/Punjabi/Urdu-script aliases from the gazetteer (D10). Misspellings are left out:
    keyterms bias the transcript toward a spelling. Scribe limits: 1000 terms, 50 characters each."""
    gaz = gazetteer.read()
    kinds = ("COMMON", "PUNJABI", "URDU_SCRIPT")
    out: dict[str, None] = {}
    for item in [*gaz["crops"].values(), *gaz["mandis"], *gaz.get("other_places", [])]:
        for t in (item["name_en"], item["name_ur"], *(a for k in kinds for a in item.get("aliases", {}).get(k, []))):
            if 0 < len(t) <= 50:
                out.setdefault(str(t), None)
    return tuple(out)[:1000]


def _open(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise STTError(f"HTTP {e.code}") from None  # the body may echo our input: never kept
    except TimeoutError as e:  # socket.timeout is TimeoutError since 3.10
        raise STTError("timeout") from e
    except urllib.error.URLError as e:
        raise STTError("timeout" if isinstance(e.reason, TimeoutError) else "network") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise STTError("bad json") from e


def scribe(path: str, key: str) -> tuple[str, dict]:
    """ElevenLabs Scribe v2 (POST multipart). Returns (text, {language, language_probability})."""
    boundary = uuid.uuid4().hex
    # tag_audio_events off: Scribe otherwise answers a noise-only note with "[background noise]" (live check, D-035)
    parts = [("model_id", SCRIBE_MODEL), ("tag_audio_events", "false"), *(("keyterms", t) for t in keyterms())]
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode() for n, v in parts)
    with open(path, "rb") as f:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="note.ogg"\r\n'
                 "Content-Type: audio/ogg\r\n\r\n").encode() + f.read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(SCRIBE_URL, data=body, method="POST", headers={
        "xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    r = _open(req)
    return r.get("text") or "", {"language": r.get("language_code"), "language_probability": r.get("language_probability")}


def gemini(path: str, key: str, model: str) -> tuple[str, dict]:
    """Gemini audio via generateContent, inline base64 audio, temperature 0. The key goes in a header, never the URL."""
    with open(path, "rb") as f:
        audio = base64.b64encode(f.read()).decode()
    payload = {"contents": [{"parts": [{"inline_data": {"mime_type": "audio/ogg", "data": audio}}, {"text": GEMINI_PROMPT}]}],
               "generationConfig": {"temperature": 0}}
    req = urllib.request.Request(GEMINI_URL.format(model=model), data=json.dumps(payload).encode(), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    r = _open(req)
    try:
        cand = r["candidates"][0]
        text = "".join(p.get("text", "") for p in cand["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise STTError("no candidate (blocked or empty)") from None
    return text, {"finish_reason": cand.get("finishReason")}


_TAG = re.compile(r"\[[^\]]*\]|\([^)]*\)")  # "[background noise]", "(music)": sound labels, not words


def strip_tags(text: str) -> str:
    """Drop bracketed sound labels so a note that is only a label counts as empty (and goes to the next provider)."""
    return " ".join(_TAG.sub(" ", text).split())


def sanity(text: str, duration_s: float) -> str | None:
    """None if the transcript is plausible, else the reason (file 05 §6 step 3)."""
    words = text.split()
    if not words:
        return "empty"
    if len(words) / max(duration_s, MIN_S) > MAX_WPS:
        return "words_per_second"
    run = best = 1
    for a, b in zip(words, words[1:], strict=False):
        run = run + 1 if a.casefold() == b.casefold() else 1
        best = max(best, run)
    # only machine-length loops: a person testing the bot says "hello hello hello hello hello hello" (live 2026-11-28, D-035)
    if best >= 8 or (len(words) >= 16 and len({w.casefold() for w in words}) / len(words) < 0.25):
        return "repeat_loop"
    for ch in text:
        if ch.isalpha() and not unicodedata.name(ch, "").startswith(("LATIN", "ARABIC", "DEVANAGARI")):
            return "script"
    return None


def transcribe(path: str) -> tuple[str | None, dict]:
    """(transcript or None, stt_meta). stt_meta.attempts is empty when the pre-check stopped the note (no STT call)."""
    verdict, meta, mono, sr = precheck(path)
    meta = {"precheck": verdict, **meta, "truncated": False, "attempts": [], "provider": None}
    if verdict != "OK":
        return None, meta
    send, tmp = path, None
    if meta["duration_s"] > MAX_S:  # send only the decoded first 120 s; the reply says so
        fd, tmp = tempfile.mkstemp(prefix="wa-stt-", suffix=".ogg")
        os.close(fd)
        try:
            sf.write(tmp, mono, sr, format="OGG", subtype="OPUS")
        except Exception as e:  # e.g. a sample rate Opus does not take: give up without STT rather than raise
            os.remove(tmp)
            meta.update(precheck="UNREADABLE", error=f"truncate: {type(e).__name__}")
            return None, meta
        send, meta["truncated"] = tmp, True
    heard_s = min(meta["duration_s"], MAX_S)
    model = os.environ.get("GEMINI_MODEL") or GEMINI_DEFAULT
    chain = [("scribe", SCRIBE_MODEL, "ELEVENLABS_API_KEY", lambda k: scribe(send, k)),
             ("gemini", model, "GEMINI_API_KEY", lambda k: gemini(send, k, model))]
    try:
        for provider, model_id, env, call in chain:
            attempt = {"provider": provider, "model": model_id}
            meta["attempts"].append(attempt)
            if not (key := os.environ.get(env)):
                attempt["outcome"] = "no_key"
                continue
            t0 = time.monotonic()
            try:
                text, extra = call(key)
            except Exception as e:  # STTError, or an unexpected body shape: never raise (a re-run turn spends quota again)
                err = str(e) if isinstance(e, STTError) else type(e).__name__
                attempt.update(outcome="error", error=err, ms=round((time.monotonic() - t0) * 1000))
                continue
            attempt["ms"] = round((time.monotonic() - t0) * 1000)
            text = strip_tags(text)
            if reason := sanity(text, heard_s):
                # the rejected text stays in stt_meta (same row, retention and STOP as the transcript), never in logs
                attempt.update(outcome="rejected", reason=reason, text=text[:200] or None)
                continue
            attempt["outcome"] = "ok"
            meta.update(provider=provider, **extra)
            return text.strip(), meta
    finally:
        if tmp:
            os.remove(tmp)
    log.error("stt: every provider failed for a %.1f s note: %s", heard_s,
              [(a["provider"], a["outcome"], a.get("error") or a.get("reason")) for a in meta["attempts"]])
    return None, meta


def reply(text: str | None, meta: dict) -> str:
    """What the farmer is told about this note; derived from the stored row, so a re-claimed turn says the same thing."""
    if text:
        return text + (" " + TRUNCATED_NOTE if meta.get("truncated") else "")
    return {"TOO_SHORT": TOO_SHORT_TEXT, "SILENT": SILENT_TEXT}.get(meta.get("precheck"), FAILED_TEXT)
