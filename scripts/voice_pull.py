"""Task 6.4: store a benchmark voice note that came in through the real webhook + media path (SPEC §3.2).

    python scripts/voice_pull.py sheet [S1 ...]   recording sheet: who says what, on which phone, in which condition
    python scripts/voice_pull.py V01 <media_id>    download the note and store it as data/benchmark/audio/V01.ogg

Steps per note:
1. On the item's phone, record the line INSIDE WhatsApp (hold the mic) and send it to the test number.
   The bot answers "Echo: voice note received (N bytes)": the webhook, queue and media download all worked.
2. On the VM (browser terminal, ~/mandisaathi), list the media IDs of the voice notes, newest last:
     sudo docker compose exec postgres psql -U mandi -d mandi -c "SELECT id, wa_ts,
       payload->'message'->'audio'->>'id' AS media_id FROM inbound_event
       WHERE payload->'message'->>'type' = 'audio' AND payload->'message'->'audio'->>'voice' = 'true'
       ORDER BY wa_ts DESC LIMIT 10"
   (voice = 'true' keeps out forwarded audio files; only notes recorded in WhatsApp count.)
3. On the laptop, from the repo root (needs WA_TOKEN in .env): python scripts/voice_pull.py V01 <media_id>
   Downloads with app.gateway.download_media (fresh URL per media ID), checks it is an Ogg/Opus note, saves it,
   writes duration_s into voice.jsonl / controls.jsonl and the file's sha256 into manifest.csv (re-pull replaces).
Do NOT send STOP from a recording phone before pulling: STOP deletes that phone's inbound_event rows (and media IDs).
Media IDs of incoming messages are kept by Meta for 30 days.
"""
import csv
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "data" / "benchmark"
FILES = (BENCH / "voice.jsonl", BENCH / "controls.jsonl")
MANIFEST = BENCH / "manifest.csv"
MIN_S, MAX_S = 3, 45  # SPEC §3.2 note length; controls are exempt (silence 5 s, long > 120 s)


def ogg_duration(data: bytes) -> float:
    """Seconds of an Ogg Opus file: last page's granule position minus pre-skip, at Opus's fixed 48 kHz."""
    if not data.startswith(b"OggS") or data.find(b"OpusHead") < 0:
        raise ValueError("not an Ogg Opus file (WhatsApp voice notes are audio/ogg; codecs=opus)")
    head = data.find(b"OpusHead")
    pre_skip = struct.unpack_from("<H", data, head + 10)[0]
    last = data.rfind(b"OggS")
    granule = struct.unpack_from("<q", data, last + 6)[0]
    return round((granule - pre_skip) / 48000, 2)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def save(path: Path, items: list[dict]) -> None:
    path.write_bytes("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items).encode("utf-8"))


def store(item_id: str, data: bytes) -> float:
    """Write audio + duration_s + manifest row for one benchmark item; returns the duration."""
    for path in FILES:
        items = load(path)
        item = next((i for i in items if i["id"] == item_id), None)
        if item:
            break
    else:
        raise SystemExit(f"{item_id}: not in voice.jsonl or controls.jsonl")
    dur = ogg_duration(data)
    if item["set"] == "voice" and not MIN_S <= dur <= MAX_S:
        raise SystemExit(f"{item_id}: {dur} s is outside {MIN_S}-{MAX_S} s (SPEC §3.2); record it again")
    out = BENCH / item["audio"]
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(data)
    item["duration_s"] = dur
    save(path, items)
    rows = [r for r in (csv.DictReader(MANIFEST.open(encoding="utf-8")) if MANIFEST.exists() else []) if r["file"] != item["audio"]]
    rows.append({"file": item["audio"], "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "duration_s": dur})
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["file", "sha256", "bytes", "duration_s"], lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["file"]))
    return dur


def pull(item_id: str, media_id: str) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_token import load_env  # .env reader shared with the other Meta scripts

    os.environ.update({k: v for k, v in load_env().items() if k not in os.environ})
    from app import gateway

    tmp = gateway.download_media(media_id)
    try:
        data = Path(tmp).read_bytes()
    finally:
        os.remove(tmp)
    print(f"{item_id}: stored {len(data)} bytes, {store(item_id, data)} s")


def sheet(speakers: list[str]) -> None:
    for item in load(FILES[0]) + load(FILES[1]):
        if speakers and item["speaker"] not in speakers:
            continue
        done = "done" if item["duration_s"] else "todo"
        if item["set"] == "voice":
            t = item["gold_transcript"]
            print(f"{item['id']:9} {item['speaker']} {item['phone']} {item['condition']:7} [{done}]  {t['roman']}\n{'':32}{t['urdu']}")
        else:
            print(f"{item['id']:9} {item['speaker']} {item['phone']} {'':7} [{done}]  control: {item['kind']}: {item['notes']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["sheet"]:
        sheet(args[1:])
    elif len(args) == 2:
        pull(*args)
    else:
        raise SystemExit(__doc__)
