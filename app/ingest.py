"""Idempotent ingest (task 3.1): webhook payload -> inbound_event + job in one transaction (RFC §3 step 1, §13)."""
import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from app import crypto

log = logging.getLogger(__name__)

PHONE_KEYS = {"from", "wa_id", "new_wa_id", "recipient_id", "phone"}  # values are phone numbers in Meta payloads

# A duplicate WAMID / status key inserts no event, so the chained job insert gets no row either.
STORE_SQL = """
WITH ev AS (
    INSERT INTO inbound_event (dedup_key, kind, user_key, wa_ts, payload) VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (dedup_key) DO NOTHING
    RETURNING id, user_key
)
INSERT INTO job (kind, user_key, payload) SELECT %s::text, user_key, jsonb_build_object('event_id', id) FROM ev
"""


def phash(key: str, value: str) -> str:
    """Keyed hash of the digits only, so '+92 300-1234567' and '923001234567' give the same key."""
    return hmac.new(key.encode(), re.sub(r"\D", "", value).encode(), hashlib.sha256).hexdigest()


def redact(obj, key: str):
    """Copy of obj with every phone-number value (any depth) replaced by its hash."""
    if isinstance(obj, dict):
        return {k: phash(key, str(v)) if k in PHONE_KEYS and isinstance(v, str | int) else redact(v, key) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, key) for v in obj]
    return obj


def _ts(item: dict) -> datetime:
    return datetime.fromtimestamp(int(item["timestamp"]), UTC)


def events(data: dict, key: str, enc_key: str) -> list[tuple]:
    """(dedup_key, kind, user_key, wa_ts, payload, job_kind) per message/status. Raises KeyError etc. on a malformed payload.

    `key` hashes numbers for analysis (task 3.1); `enc_key` encrypts the sender's number so the gateway (task 5.1) can
    recover it to reply. The stored payload keeps the number only two ways: hashed inside `message.from` and, for
    messages, encrypted as top-level `from_enc` (file 07 §3). A plain number never lands in the row.
    """
    out = []
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                log.warning("webhook: ignored field %s", change.get("field"))
                continue
            value = change["value"]
            if value.get("errors"):
                log.warning("webhook: ignored value.errors (%d)", len(value["errors"]))
            base = {"metadata": value.get("metadata"), "contacts": value.get("contacts") or []}
            for m in value.get("messages") or []:
                user = m.get("from_user_id") or (phash(key, m["from"]) if m.get("from") else None)
                payload = redact({**base, "message": m}, key)
                if m.get("from"):  # reversible copy for the send path; no "from" (BSUID-only) can't be replied to yet (D-013)
                    payload["from_enc"] = crypto.encrypt(enc_key, m["from"])
                out.append((m["id"], "message", user, _ts(m), payload, "turn"))
            for s in value.get("statuses") or []:
                user = s.get("recipient_user_id") or (phash(key, s["recipient_id"]) if s.get("recipient_id") else None)
                out.append((f'{s["id"]}:{s["status"]}', "status", user, _ts(s), redact({**base, "status": s}, key), "status"))
    return out


# shortcut: one job per event, no per-farmer coalescing; coalescing in 6.2, debounce in 14.1
# shortcut: new connection per request, no pool; fine at <=1 msg/s (RFC §14)
def store(conninfo: str, evs: list[tuple]) -> int:
    """Insert all events and their jobs in ONE transaction; return how many were new. Any error rolls back everything."""
    new = 0
    with psycopg.connect(conninfo, connect_timeout=2) as conn:  # commits on clean exit, rolls back on exception
        for dedup_key, kind, user_key, wa_ts, payload, job_kind in evs:
            new += conn.execute(STORE_SQL, (dedup_key, kind, user_key, wa_ts, Jsonb(payload), job_kind)).rowcount
    return new
