"""Speech service (task 8.1, RFC C4, file 05 §6). DONE condition (file 11): a team note -> transcript stored; a forced primary
error uses the fallback; a silent control -> "dobara bhejein" with no STT call.

Audio fixtures are generated Ogg Opus (soundfile), so no recording is committed. No test reaches the network: urlopen is
replaced for every test, and the provider tests hand it canned responses. The live check with real keys and a real team
note (6.4 V01) is in DECISIONS.md D-035.
"""
import io
import json
import urllib.error
import urllib.request

import numpy as np
import psycopg
import pytest
import soundfile as sf

from app import gateway, handlers, speech
from tests.test_handlers import ENC_KEY, NUMBER, StubGateway, seed_turn

SR = 16000
rng = np.random.default_rng(0)


def _db(x):
    return 10 ** (x / 20)


def _floor(s, level=-60):  # a phone's noise floor, not digital zeros
    return rng.normal(0, _db(level), int(s * SR))


def _speechlike(s, level=-22):
    """Noise floor + 3 Hz syllable-like bursts of a voiced tone at `level` dBFS."""
    x = _floor(s)
    t = np.arange(len(x)) / SR
    return x + (np.sin(2 * np.pi * 3 * t) > 0.2) * rng.normal(0, _db(level), len(x)) * np.sin(2 * np.pi * 180 * t) * 1.4


def _music(s):
    t = np.arange(int(s * SR)) / SR
    return 0.2 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.sin(2 * np.pi * 660 * t)


def _covered_mic(s):
    """Handling noise around -40 dBFS with a slow wobble, never loud: the live covered-mic note (D-035 row 2, max -23 dBFS)."""
    t = np.arange(int(s * SR)) / SR
    return rng.normal(0, _db(-40), len(t)) * (1 + 0.8 * np.sin(2 * np.pi * 0.7 * t))


def _one_word(s):
    """One 0.4 s word in an otherwise quiet note: the live row 3 shape (5.8% loud frames), which must stay OK."""
    x = _floor(s)
    i, n = int(2 * SR), int(0.4 * SR)
    x[i:i + n] += _speechlike(0.4, level=-16)[:n]
    return x


def ogg(tmp_path, sig, name="note"):
    p = tmp_path / f"{name}.ogg"
    sf.write(p, np.asarray(sig, dtype="float32"), SR, format="OGG", subtype="OPUS")
    return str(p)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


class Providers:
    """Replaces speech.scribe / speech.gemini; each is a str (transcript) or an exception to raise. Records calls."""
    def __init__(self, monkeypatch, scribe="aloo ka rate okara", gemini="pyaz ka rate lahore"):
        self.calls, self.out = [], {"scribe": scribe, "gemini": gemini}
        monkeypatch.setenv("ELEVENLABS_API_KEY", "k-el")
        monkeypatch.setenv("GEMINI_API_KEY", "k-gm")
        monkeypatch.setattr(speech, "scribe", lambda path, key: self._call("scribe", path, key))
        monkeypatch.setattr(speech, "gemini", lambda path, key, model: self._call("gemini", path, key))

    def _call(self, name, path, key):
        self.calls.append((name, sf.info(path).duration))
        out = self.out[name]
        if isinstance(out, BaseException):
            raise out
        return out, {"language": "ur"} if name == "scribe" else {}


# --- pre-checks: silent / short notes never reach an STT --------------------------------------------------------------

@pytest.mark.parametrize("sig,verdict", [
    (_floor(5), "SILENT"), (_floor(20), "SILENT"), (np.zeros(3 * SR), "SILENT"),  # the 6.4 silent controls (5 s, 20 s)
    (_covered_mic(6), "SILENT"),  # C-SIL "cover the mic": hums but never gets loud
    (_speechlike(0.6), "TOO_SHORT"),
    (_speechlike(4), "OK"), (_one_word(6), "OK"),  # one short word in a long note is still speech
    # trade-off (D-035): speech that never peaks above -25 dBFS counts as silence; live WhatsApp speech peaked at -6..-11
    (_speechlike(4, level=-30), "SILENT"),
    (_music(5), "OK"),  # music goes to STT; the parser then finds no question (file 05 §6 step 5)
])
def test_precheck_verdicts(tmp_path, sig, verdict):
    assert speech.precheck(ogg(tmp_path, sig))[0] == verdict


def test_silent_control_gets_dobara_bhejein_with_no_stt_call(tmp_path, monkeypatch):  # DONE (c)
    p = Providers(monkeypatch)
    text, meta = speech.transcribe(ogg(tmp_path, _floor(3)))
    assert text is None and p.calls == [] and meta["attempts"] == []
    assert meta["precheck"] == "SILENT" and meta["active_ratio"] < speech.MIN_ACTIVE
    assert speech.reply(text, meta) == "Awaaz nahi aayi, dobara bhejein."  # file 10 scenario 5 wording


def test_too_short_and_unreadable_never_reach_stt(tmp_path, monkeypatch):
    p = Providers(monkeypatch)
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(0.5)))
    assert (text, meta["precheck"], speech.reply(text, meta)) == (None, "TOO_SHORT", speech.TOO_SHORT_TEXT)
    junk = tmp_path / "junk.ogg"
    junk.write_bytes(b"not audio" * 10)
    text, meta = speech.transcribe(str(junk))
    assert (text, meta["precheck"], speech.reply(text, meta)) == (None, "UNREADABLE", speech.FAILED_TEXT)
    assert p.calls == []


def test_over_120_s_sends_only_the_first_120_s_and_says_so(tmp_path, monkeypatch):
    p = Providers(monkeypatch)
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(125)))
    assert p.calls == [("scribe", pytest.approx(120, abs=0.1))]
    assert meta["truncated"] and meta["duration_s"] == 125.0
    assert speech.reply(text, meta) == "aloo ka rate okara " + speech.TRUNCATED_NOTE
    assert not list(tmp_path.glob("wa-stt-*"))  # the 120 s temp copy is removed


# --- the chain: primary -> fallback -> "likh kar" -------------------------------------------------------------------------

def test_primary_ok_uses_scribe_only(tmp_path, monkeypatch):
    p = Providers(monkeypatch)
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text == "aloo ka rate okara" and [c[0] for c in p.calls] == ["scribe"]
    assert meta["provider"] == "scribe" and meta["language"] == "ur"
    assert [(a["provider"], a["outcome"]) for a in meta["attempts"]] == [("scribe", "ok")]


def test_forced_primary_error_uses_the_fallback(tmp_path, monkeypatch):  # DONE (b)
    p = Providers(monkeypatch, scribe=speech.STTError("HTTP 500"))
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text == "pyaz ka rate lahore" and [c[0] for c in p.calls] == ["scribe", "gemini"]
    assert meta["provider"] == "gemini"
    assert [(a["provider"], a["outcome"], a.get("error")) for a in meta["attempts"]] == [
        ("scribe", "error", "HTTP 500"), ("gemini", "ok", None)]


@pytest.mark.parametrize("bad,reason", [("", "empty"), ("   ", "empty"), ("rate rate rate rate", "repeat_loop"),
                                        ("这是 中文", "script"), (" ".join(["pyaz"] + ["ka"] * 30), "words_per_second")])
def test_garbage_from_primary_falls_back(tmp_path, monkeypatch, bad, reason):
    p = Providers(monkeypatch, scribe=bad)
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text == "pyaz ka rate lahore" and len(p.calls) == 2
    assert meta["attempts"][0] == {"provider": "scribe", "model": "scribe_v2", "outcome": "rejected", "reason": reason,
                                   "ms": meta["attempts"][0]["ms"]}


def test_unexpected_provider_exception_falls_back_and_never_raises(tmp_path, monkeypatch):
    p = Providers(monkeypatch, scribe=KeyError("text"), gemini=TypeError("not a dict"))
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))  # must not raise: the worker would re-run the turn
    assert text is None and len(p.calls) == 2
    assert [(a["outcome"], a["error"]) for a in meta["attempts"]] == [("error", "KeyError"), ("error", "TypeError")]


def test_scribe_non_dict_body_is_an_error_not_a_crash(tmp_path, monkeypatch):
    FakeHTTP(monkeypatch, ["unexpected"])
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text is None and meta["attempts"][0]["outcome"] == "error"


def test_truncation_write_failure_gives_up_without_stt(tmp_path, monkeypatch):
    p = Providers(monkeypatch)
    path = ogg(tmp_path, _speechlike(125))
    def fail(*a, **k):
        raise RuntimeError("bad sample rate")
    monkeypatch.setattr(sf, "write", fail)
    text, meta = speech.transcribe(path)
    assert text is None and p.calls == [] and meta["precheck"] == "UNREADABLE" and speech.reply(text, meta) == speech.FAILED_TEXT


@pytest.mark.parametrize("label", ["[background noise]", "(music)", " [noise]  (silence) "])
def test_a_sound_label_alone_is_empty_and_falls_back(tmp_path, monkeypatch, label):  # live check 2026-11-27, row 2
    p = Providers(monkeypatch, scribe=label)
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text == "pyaz ka rate lahore" and len(p.calls) == 2
    assert (meta["attempts"][0]["outcome"], meta["attempts"][0]["reason"]) == ("rejected", "empty")


def test_sound_labels_are_stripped_from_a_real_transcript(tmp_path, monkeypatch):
    Providers(monkeypatch, scribe="[background noise] Okara mein pyaz ka rate (laughs)")
    assert speech.transcribe(ogg(tmp_path, _speechlike(4)))[0] == "Okara mein pyaz ka rate"


def test_both_fail_says_likh_kar_and_logs_an_error(tmp_path, monkeypatch, caplog):
    Providers(monkeypatch, scribe=speech.STTError("timeout"), gemini=speech.STTError("HTTP 429"))
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text is None and speech.reply(text, meta) == "Awaaz samajh nahi aayi, likh kar bhej dein."
    assert any(r.levelname == "ERROR" and "every provider failed" in r.getMessage() for r in caplog.records)


def test_missing_keys_skip_providers(tmp_path, monkeypatch):
    p = Providers(monkeypatch)
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    text, meta = speech.transcribe(ogg(tmp_path, _speechlike(4)))
    assert text == "pyaz ka rate lahore" and [c[0] for c in p.calls] == ["gemini"]
    assert meta["attempts"][0] == {"provider": "scribe", "model": "scribe_v2", "outcome": "no_key"}
    monkeypatch.delenv("GEMINI_API_KEY")
    assert speech.transcribe(ogg(tmp_path, _speechlike(4)))[0] is None


@pytest.mark.parametrize("text", ["Okara mandi mein pyaz ka rate kya hai", "اوکاڑہ میں پیاز کا ریٹ", "प्याज का रेट", "50 mann aloo"])
def test_sanity_accepts_real_transcripts(text):
    assert speech.sanity(text, 4.0) is None


# --- providers: request shape and error mapping (canned HTTP, no network) -------------------------------------------------

class FakeHTTP:
    def __init__(self, monkeypatch, body=None, error=None):
        self.reqs, self.body, self.error = [], body, error
        monkeypatch.setattr(urllib.request, "urlopen", self)

    def __call__(self, req, timeout=None):
        self.reqs.append((req, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.body).encode())


def test_scribe_request_shape(tmp_path, monkeypatch):
    http = FakeHTTP(monkeypatch, {"text": "aloo", "language_code": "urd", "language_probability": 0.9})
    text, extra = speech.scribe(ogg(tmp_path, _speechlike(2)), "k-el")
    (req, timeout), = http.reqs
    assert (text, extra) == ("aloo", {"language": "urd", "language_probability": 0.9})
    assert req.full_url == speech.SCRIBE_URL and req.get_header("Xi-api-key") == "k-el" and timeout == 6.0
    body = req.data
    assert b'name="model_id"\r\n\r\nscribe_v2' in body and b'name="file"; filename="note.ogg"' in body
    assert b'name="tag_audio_events"\r\n\r\nfalse' in body
    assert b'name="keyterms"\r\n\r\nOkara' in body and 'پیاز'.encode() in body


def test_keyterms_fit_scribe_limits():
    kt = speech.keyterms()
    assert 0 < len(kt) <= 1000 and all(0 < len(t) <= 50 for t in kt) and len(set(kt)) == len(kt)
    assert {"Onion", "pyaz", "Okara", "Lahore", "Hyderabad"} <= set(kt) and "piaz" not in kt  # misspellings left out


def test_gemini_request_shape_key_in_header_not_url(tmp_path, monkeypatch):
    http = FakeHTTP(monkeypatch, {"candidates": [{"content": {"parts": [{"text": "pyaz "}, {"text": "ka rate"}]},
                                                  "finishReason": "STOP"}]})
    text, extra = speech.gemini(ogg(tmp_path, _speechlike(2)), "k-gm", "gemini-x")
    (req, timeout), = http.reqs
    assert (text, extra) == ("pyaz ka rate", {"finish_reason": "STOP"})
    assert req.full_url.endswith("/models/gemini-x:generateContent") and "k-gm" not in req.full_url
    assert req.get_header("X-goog-api-key") == "k-gm" and timeout == 6.0
    sent = json.loads(req.data)
    assert sent["generationConfig"] == {"temperature": 0}
    assert sent["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "audio/ogg"


@pytest.mark.parametrize("error,msg", [
    (urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b"secret echo")), "HTTP 401"),
    (TimeoutError(), "timeout"), (urllib.error.URLError(TimeoutError()), "timeout"),
    (urllib.error.URLError(OSError("dns")), "network"),
])
def test_provider_errors_become_stterror(tmp_path, monkeypatch, error, msg):
    FakeHTTP(monkeypatch, error=error)
    with pytest.raises(speech.STTError, match=f"^{msg}$"):
        speech.scribe(ogg(tmp_path, _speechlike(2)), "k")


def test_gemini_blocked_or_empty_is_an_error(tmp_path, monkeypatch):
    FakeHTTP(monkeypatch, {"promptFeedback": {"blockReason": "OTHER"}})
    with pytest.raises(speech.STTError, match="no candidate"):
        speech.gemini(ogg(tmp_path, _speechlike(2)), "k", "m")


# --- in the turn: transcript stored in message_log, re-claim reuses it, STOP deletes it (needs Postgres) ------------------

@pytest.fixture
def url(db, monkeypatch):
    from app.migrate import migrate
    migrate(db)
    monkeypatch.setenv("WA_NUMBER_ENC_KEY", ENC_KEY)
    return db


@pytest.fixture
def conn(url):
    with psycopg.connect(url, autocommit=True) as c:
        yield c


@pytest.fixture
def note(tmp_path, monkeypatch):
    """download_media hands the turn a fresh copy of a generated note each call; `calls` counts downloads."""
    src = ogg(tmp_path, _speechlike(4), "src")
    calls = []

    def download(mid):
        calls.append(mid)
        dst = tmp_path / f"dl{len(calls)}.ogg"
        dst.write_bytes(open(src, "rb").read())
        return str(dst)
    monkeypatch.setattr(gateway, "download_media", download)
    return calls


def log_rows(conn):
    return conn.execute("SELECT user_key, direction, modality, text_or_transcript, stt_meta FROM message_log").fetchall()


def test_voice_turn_stores_the_transcript_and_deletes_the_audio(conn, monkeypatch, note, tmp_path):  # DONE (a), mocked
    gw = StubGateway(monkeypatch)
    Providers(monkeypatch)
    handlers.handle_turn(conn, seed_turn(conn, mtype="audio"))
    assert gw.sends == [(NUMBER, "Echo: aloo ka rate okara")]
    (user, direction, modality, text, meta), = log_rows(conn)
    assert (user, direction, modality, text) == ("US.F", "in", "voice", "aloo ka rate okara")
    assert meta["precheck"] == "OK" and meta["provider"] == "scribe" and meta["attempts"][0]["outcome"] == "ok"
    assert not (tmp_path / "dl1.ogg").exists()  # audio is never kept (OPS §3)


def test_silent_voice_turn_logs_no_stt_call(conn, monkeypatch, tmp_path):  # file 10 scenario 5: message_log shows no STT call
    gw, p = StubGateway(monkeypatch), Providers(monkeypatch)
    silent = ogg(tmp_path, _floor(3), "silent")
    monkeypatch.setattr(gateway, "download_media", lambda mid: silent)
    handlers.handle_turn(conn, seed_turn(conn, mtype="audio"))
    assert gw.sends == [(NUMBER, speech.SILENT_TEXT)] and p.calls == []
    (_, _, _, text, meta), = log_rows(conn)
    assert text is None and meta["precheck"] == "SILENT" and meta["attempts"] == []


def test_reclaimed_voice_turn_does_not_download_or_transcribe_again(conn, monkeypatch, note):
    gw, p = StubGateway(monkeypatch), Providers(monkeypatch)
    job = seed_turn(conn, mtype="audio")
    gw.result = gateway.SendRetryable("HTTP 503")  # the reply fails after STT: the worker will re-run the turn
    with pytest.raises(gateway.SendRetryable):
        handlers.handle_turn(conn, job)
    gw.result = "wamid.OUT"
    handlers.handle_turn(conn, job)
    assert len(note) == 1 and len(p.calls) == 1  # one download, one STT call
    assert gw.sends[-1] == (NUMBER, "Echo: aloo ka rate okara") and len(log_rows(conn)) == 1


def test_download_failure_says_likh_kar_and_is_logged(conn, monkeypatch):
    gw = StubGateway(monkeypatch)

    def gone(mid):
        raise gateway.SendPermanent("media download failed after re-query")
    monkeypatch.setattr(gateway, "download_media", gone)
    handlers.handle_turn(conn, seed_turn(conn, mtype="audio"))
    assert gw.sends == [(NUMBER, speech.FAILED_TEXT)]
    assert log_rows(conn)[0][4] == {"precheck": "DOWNLOAD_FAILED", "attempts": []}


def test_stop_deletes_message_log(conn, monkeypatch, note):
    StubGateway(monkeypatch)
    Providers(monkeypatch)
    handlers.handle_turn(conn, seed_turn(conn, mtype="audio", user="US.GONE"))
    assert conn.execute("SELECT count(*) FROM message_log WHERE user_key = 'US.GONE'").fetchone() == (1,)
    handlers.handle_turn(conn, seed_turn(conn, "STOP", user="US.GONE"))
    assert conn.execute("SELECT count(*) FROM message_log").fetchone() == (0,)
