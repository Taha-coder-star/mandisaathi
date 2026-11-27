"""Task 6.4: benchmark voice notes (30) + controls (5), SPEC §2.2/§2.3/§3.2/§3.3 (D-030).

Gold is checked now; recordings are checked as they arrive (audio is git-ignored, so CI sees only manifest.csv and
duration_s). DONE (file 11): >= 10 recorded items, each with a manifest row and a consenting, named speaker."""
import csv
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path

import pytest

from scripts import voice_pull
from tests.test_benchmark_texts import ARABIC, check_gazetteer, check_numbers, check_schema, check_tags

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "data/benchmark"
VOICE = voice_pull.load(BENCH / "voice.jsonl")
CONTROLS = voice_pull.load(BENCH / "controls.jsonl")
TEXT = {i["id"]: i for i in voice_pull.load(BENCH / "text.jsonl")}
SPEAKERS = {r["speaker_id"]: r for r in csv.DictReader((BENCH / "speakers.csv").open(encoding="utf-8"))}
MANIFEST = {r["file"]: r for r in csv.DictReader((BENCH / "manifest.csv").open(encoding="utf-8"))} if (
    BENCH / "manifest.csv").exists() else {}

# SPEC §3.2 table: speaker -> (phone, note ids, categories in id order)
MATRIX = {"S1": ("P1", [1, 2, 3, 4, 23], "RU RU RU RU MIX"), "S2": ("P2", [5, 6, 7, 8, 24], "RU RU RU RU MIX"),
          "S3": ("P3", [9, 10, 11, 12, 25], "RU RU RU RU MIX"), "S4": ("P1", [13, 14, 26, 27, 28], "RU RU MIX MIX AMB"),
          "S5": ("P2", [15, 16, 17, 18, 29], "PA PA PA PA AMB"), "S6": ("P3", [19, 20, 21, 22, 30], "PA PA PA PA AMB")}
CONDITIONS = {s: {"QUIET": 2, "INDOOR": 2, "OUTDOOR": 1} for s in ("S1", "S2", "S3", "S4")} | {
    s: {"QUIET": 2, "INDOOR": 1, "OUTDOOR": 2} for s in ("S5", "S6")}
PAIRED = {"V01", "V02", "V05", "V06", "V09", "V10", "V13", "V15", "V19", "V23", "V24", "V28"}
VOICE_KEYS = {"id", "set", "category", "lang", "audio", "speaker", "phone", "condition", "duration_s", "gold_transcript",
              "paired_text_id", "input", "gold", "tags", "notes"}


def as_text(it):
    """The voice item as a text item whose input is the gold transcript, so the text gold rules apply unchanged."""
    return {k: it[k] for k in ("id", "set", "category", "lang", "gold", "tags", "notes")} | {
        "input": it["gold_transcript"]["roman"]}


def test_ids_and_matrix():
    assert [i["id"] for i in VOICE] == [f"V{n:02d}" for n in range(1, 31)]
    for spk, (phone, ids, cats) in MATRIX.items():
        mine = [i for i in VOICE if i["speaker"] == spk]
        assert [i["id"] for i in mine] == [f"V{n:02d}" for n in ids], spk
        assert [i["category"] for i in mine] == cats.split(), spk
        assert {i["phone"] for i in mine} == {phone} and SPEAKERS[spk]["phone"] == phone, spk
        assert Counter(i["condition"] for i in mine) == CONDITIONS[spk], spk
        accent = SPEAKERS[spk]["accent"]
        for i in mine:
            assert i["lang"] == ("PA" if accent == "punjabi" else {"MIX": "MIX"}.get(i["category"], "RU")), i["id"]
    assert Counter(i["category"] for i in VOICE) == {"RU": 14, "PA": 8, "MIX": 5, "AMB": 3}
    assert Counter(i["condition"] for i in VOICE) == {"QUIET": 12, "INDOOR": 10, "OUTDOOR": 8}
    assert Counter(i["phone"] for i in VOICE) == {"P1": 10, "P2": 10, "P3": 10}


def test_gold():
    for it in VOICE:
        i = it["id"]
        assert set(it) == VOICE_KEYS and it["set"] == "voice" and it["input"] is None, i
        assert it["audio"] == f"audio/{i}.ogg", i
        t = it["gold_transcript"]
        assert set(t) == {"roman", "urdu"} and not ARABIC.search(t["roman"]) and ARABIC.search(t["urdu"]), i
        view = as_text(it)
        for check in (check_schema, check_gazetteer, check_tags, check_numbers):
            check(view)
        assert (it["paired_text_id"] is not None) == (i in PAIRED), i
        if src := it["paired_text_id"]:
            assert it["gold"] == TEXT[src]["gold"] and it["tags"] == TEXT[src]["tags"], i
            assert t["roman"] == TEXT[src]["input"], i
    assert next(i for i in VOICE if i["id"] == "V05")["paired_text_id"] == "T-RU-05"  # SPEC §2.2 example
    assert len({re.sub(r"\W", "", i["gold_transcript"]["roman"].casefold()) for i in VOICE}) == 30
    amb = [i["gold"] for i in VOICE if i["category"] == "AMB"]
    assert all(g["outcome"] == "CLARIFY" for g in amb)


def test_controls():
    assert [c["id"] for c in CONTROLS] == ["C-SIL-01", "C-SIL-02", "C-MUS-01", "C-LANG-01", "C-LONG-01"]
    kinds = {"SILENCE", "MUSIC", "OTHER_LANGUAGE", "TOO_LONG"}
    for c in CONTROLS:
        assert set(c) == {"id", "set", "kind", "audio", "speaker", "phone", "duration_s", "gold", "notes"}, c["id"]
        assert c["set"] == "control" and c["kind"] in kinds and c["audio"] == f"audio/{c['id']}.ogg", c["id"]
        g = c["gold"]
        assert g["max_tool_calls"] == 0, c["id"]
        assert g["outcome"] == ("CLARIFY" if c["kind"] == "OTHER_LANGUAGE" else "GRACEFUL_FAIL"), c["id"]
        assert (g.get("clarify_slot") == "language") == (c["kind"] == "OTHER_LANGUAGE"), c["id"]
        assert g["stt_called"] is (False if c["kind"] == "SILENCE" else None), c["id"]


def test_recordings_match_manifest_and_consent():
    """Every recorded item (duration_s set) has its manifest row and a named speaker who gave consent; local audio,
    where present, matches the manifest's sha256."""
    items = {i["audio"]: i for i in VOICE + CONTROLS}
    assert set(MANIFEST) <= set(items)
    for audio, it in items.items():
        row = MANIFEST.get(audio)
        assert (row is None) == (it["duration_s"] is None), it["id"]
        if row is None:
            continue
        assert float(row["duration_s"]) == it["duration_s"], it["id"]
        if it["set"] == "voice":
            assert voice_pull.MIN_S <= it["duration_s"] <= voice_pull.MAX_S, it["id"]
        spk = SPEAKERS[it["speaker"]]
        assert "TBD" not in spk["first_name"] and spk["consent_date"], (it["id"], "speaker not named or no consent")
        if (f := BENCH / audio).exists():
            data = f.read_bytes()
            assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == int(row["bytes"]), it["id"]


def fake_opus(seconds: float, pre_skip: int = 312) -> bytes:
    """Smallest bytes ogg_duration reads: OggS + OpusHead (pre-skip at +10) ... last OggS page (granule at +6)."""
    head = b"OggS" + bytes(24) + b"OpusHead" + bytes([1, 1]) + struct.pack("<H", pre_skip) + bytes(10)
    return head + b"OggS" + bytes(2) + struct.pack("<q", round(seconds * 48000) + pre_skip) + bytes(20)


def test_ogg_duration():
    assert voice_pull.ogg_duration(fake_opus(6.4)) == 6.4
    with pytest.raises(ValueError):
        voice_pull.ogg_duration(b"ID3" + bytes(40))  # an mp3 forwarded as a file, not a voice note


def test_store_writes_audio_duration_and_manifest(tmp_path, monkeypatch):
    for name in ("voice.jsonl", "controls.jsonl"):
        (tmp_path / name).write_bytes((BENCH / name).read_bytes())
    monkeypatch.setattr(voice_pull, "BENCH", tmp_path)
    monkeypatch.setattr(voice_pull, "FILES", (tmp_path / "voice.jsonl", tmp_path / "controls.jsonl"))
    monkeypatch.setattr(voice_pull, "MANIFEST", tmp_path / "manifest.csv")

    data = fake_opus(5.5)
    assert voice_pull.store("V01", data) == 5.5
    assert voice_pull.store("V01", data) == 5.5  # re-pull replaces, never duplicates
    assert voice_pull.store("C-LONG-01", fake_opus(130)) == 130  # controls skip the 3-45 s rule
    assert (tmp_path / "audio/V01.ogg").read_bytes() == data
    rows = list(csv.DictReader((tmp_path / "manifest.csv").open(encoding="utf-8")))
    assert [r["file"] for r in rows] == ["audio/C-LONG-01.ogg", "audio/V01.ogg"]
    assert rows[1]["sha256"] == hashlib.sha256(data).hexdigest() and rows[1]["duration_s"] == "5.5"
    items = voice_pull.load(tmp_path / "voice.jsonl")
    assert items[0]["duration_s"] == 5.5 and all(i["duration_s"] is None for i in items[1:])
    assert json.dumps(items[1], ensure_ascii=False) == (BENCH / "voice.jsonl").read_text("utf-8").splitlines()[1]
    with pytest.raises(SystemExit):
        voice_pull.store("V02", fake_opus(50))  # too long for a benchmark note
    with pytest.raises(SystemExit):
        voice_pull.store("V99", data)
