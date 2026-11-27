"""Worker job handlers. Registered in app.worker.HANDLERS.

`handle_turn` is the conversation orchestrator skeleton (task 6.2, RFC C3; choices: DECISIONS.md D-028):
  1. coalesce: take every not-yet-taken message of the farmer (stamped with this job's id), in WhatsApp-timestamp order;
     the other turn jobs of the same burst then find nothing and finish silently;
  2. STOP / "band karo" anywhere in the turn: confirm, then delete the farmer's rows, keeping only an anonymous count;
  3. consent gate: first contact gets the consent + AI disclosure text, then the turn is answered (file 10 scenario 1);
  4. load query_state, build the reply, save query_state (version + 1).
The reply is still an echo of the turn's messages: the parser (7.1), state patches (7.2) and renderer (9.1) replace it.

`handle_status` advances the matching outbound_message as Meta reports sent → delivered → read (forward-only; never
regresses, never moves past a terminal 'failed').

Send idempotency follows the transactional outbox (RFC §13): one outbound row per (job_id, seq); a row that already
carries a WAMID is a no-op on re-claim; a retryable failure clears the intent so the worker's backoff can try again; an
ambiguous outcome leaves the row 'pending' and is never resent. Choices: DECISIONS.md D-021.
"""
import logging
import os
import re

from psycopg.types.json import Jsonb

from app import crypto, gateway
from mandi.parse import STOP_WORDS  # single source of truth for the stop keywords (task 7.1, handoff §3.2)

log = logging.getLogger(__name__)

CONSENT_SEQ, REPLY_SEQ = 0, 1  # fixed per turn, so a re-claimed job finds what it already sent

# Plain strings until the 9.1 renderer owns all reply text. Contents per file 07 §3; no "pakka" (9.1 validator word).
CONSENT_TEXT = (
    "MandiSaathi: FAST-NUCES ka student project. Yeh AI assistant hai; rates sirf andaza hain. "
    "Hum aap ka number (encrypted) aur paighamaat 90 din tak rakhte hain. Band karne ke liye \"STOP\" likhein. "
    "Demo data (synthetic).\n"
    "MandiSaathi is an AI assistant from a FAST-NUCES student project. Prices are estimates. "
    "We keep your number (encrypted) and messages for 90 days. Send STOP to opt out. Demo data (synthetic)."
)
STOP_TEXT = (
    "Aap ka data mita diya gaya hai; ab koi paigham nahi aaye ga. Dobara shuru karne ke liye koi bhi paigham bhejein.\n"
    "Your data has been deleted and you will get no more messages. Send any message to start again."
)
# Meta delivery states, in order; 'pending' (not yet sent) ranks 0 so the first 'sent' advances it. 'failed' is terminal.
STATUS_RANK = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}


def _load_payload(conn, event_id: int) -> dict | None:
    row = conn.execute("SELECT payload FROM inbound_event WHERE id = %s", (event_id,)).fetchone()
    return row[0] if row else None


def _audio_echo(msg: dict) -> str:
    """Download the voice note (task 5.2), report it, delete it: no STT until 8.1 and audio is never kept (OPS §3).

    SendRetryable propagates so the worker retries the turn; a later attempt re-queries the media ID for a fresh URL.
    """
    try:
        path = gateway.download_media(msg["audio"]["id"])
    except gateway.SendPermanent as e:
        return f"Echo: voice note could not be downloaded ({e})"
    try:
        return f"Echo: voice note received ({os.path.getsize(path)} bytes)"
    finally:
        os.remove(path)


def _echo_body(msg: dict) -> str:
    if msg.get("type") == "text":
        return "Echo: " + msg["text"]["body"]
    if msg.get("type") == "audio":
        return _audio_echo(msg)
    return f"Echo: received a {msg.get('type', '?')} message"


def _is_stop(msg: dict) -> bool:
    if msg.get("type") != "text":
        return False
    return " ".join(re.sub(r"[^\w\s]", " ", msg["text"]["body"].casefold()).split()) in STOP_WORDS


def _send(conn, job, seq: int, to: str, body: str) -> None:
    """Send one text through the outbox row (job_id, seq). Raises SendRetryable (worker retries); other failures are kept."""
    existing = conn.execute(
        "SELECT status, wamid FROM outbound_message WHERE job_id = %s AND seq = %s", (job.id, seq)
    ).fetchone()
    if existing:
        status, wamid = existing
        # already sent (crash-safe no-op), or a prior pending/ambiguous we must never blind-resend, or a recorded failure
        if wamid or status != "failed":
            log.info("turn job %s: outbound seq %s already %s; no resend", job.id, seq, status)
        return
    # record the intent BEFORE the network call so a re-claim after a crash sees it and will not double-send (RFC §13)
    conn.execute(
        "INSERT INTO outbound_message (job_id, seq, user_key, body, status) VALUES (%s, %s, %s, %s, 'pending')",
        (job.id, seq, job.user_key, Jsonb({"type": "text", "text": body})),
    )
    try:
        wamid = gateway.send_text(to, body)
    except gateway.SendRetryable:
        # not accepted; clear the intent so the worker's backoff retry starts clean
        conn.execute("DELETE FROM outbound_message WHERE job_id = %s AND seq = %s", (job.id, seq))
        raise  # worker records a failed attempt and re-queues with backoff (max 5)
    except gateway.SendPermanent as e:
        conn.execute(
            "UPDATE outbound_message SET status = 'failed', last_error = %s WHERE job_id = %s AND seq = %s",
            (f"{type(e).__name__}: {e}"[:500], job.id, seq),
        )
        log.error("turn job %s: permanent send failure; not retried", job.id)  # farmer fallback reply is task 17.1
        return
    except gateway.SendAmbiguous as e:
        # maybe delivered: leave the row 'pending' so any re-claim refuses to resend (RFC §13 "no blind resend")
        conn.execute(
            "UPDATE outbound_message SET last_error = %s WHERE job_id = %s AND seq = %s",
            (f"{type(e).__name__}: {e}"[:500], job.id, seq),
        )
        log.error("turn job %s: ambiguous send; left pending, will not resend", job.id)
        return
    conn.execute(
        "UPDATE outbound_message SET wamid = %s, status = 'sent', status_at = now() WHERE job_id = %s AND seq = %s",
        (wamid, job.id, seq),
    )


def _forget(conn, job) -> None:
    """STOP: delete everything keyed to the farmer, keep an anonymous message count (file 06 §3, file 07 §3)."""
    u = job.user_key
    with conn.transaction():
        n = conn.execute("SELECT count(*) FROM inbound_event WHERE user_key = %s AND kind = 'message'", (u,)).fetchone()[0]
        conn.execute("INSERT INTO stop_tally (message_count) VALUES (%s)", (n,))
        conn.execute("DELETE FROM outbound_message WHERE user_key = %s", (u,))
        conn.execute("DELETE FROM job WHERE user_key = %s AND id <> %s", (u, job.id))
        conn.execute("UPDATE job SET user_key = NULL, payload = '{}' WHERE id = %s", (job.id,))  # the running job itself
        conn.execute("DELETE FROM inbound_event WHERE user_key = %s", (u,))  # payloads hold from_enc
        conn.execute("DELETE FROM wa_user WHERE user_key = %s", (u,))  # cascades to query_state
    log.info("turn job %s: STOP, farmer data deleted", job.id)


def handle_turn(conn, job):
    """One serialised farmer turn (the worker holds the farmer's advisory lock). conn is the worker's autocommit connection."""
    u = job.user_key
    if u is None:  # no sender key to serialise or reply on; also a re-claim after STOP nulled this job
        log.warning("turn job %s: no user_key; nothing to do", job.id)
        return
    conn.execute(
        "UPDATE inbound_event SET processed_at = now(), turn_job_id = %s"
        " WHERE user_key = %s AND kind = 'message' AND processed_at IS NULL",
        (job.id, u),
    )
    payloads = [r[0] for r in conn.execute(
        "SELECT payload FROM inbound_event WHERE turn_job_id = %s ORDER BY wa_ts NULLS LAST, id", (job.id,)
    )]
    if not payloads:
        log.info("turn job %s: messages already taken by an earlier turn", job.id)
        return
    msgs = [p["message"] for p in payloads]
    enc = next((p["from_enc"] for p in reversed(payloads) if p.get("from_enc")), None)
    to = crypto.decrypt(os.environ["WA_NUMBER_ENC_KEY"], enc) if enc else None

    if to:
        try:  # read receipt + typing is best-effort: a failure here must not stop the reply
            gateway.mark_read(msgs[-1]["id"], typing=True)
        except gateway.SendError as e:
            log.info("turn job %s: mark_read failed (%s); continuing", job.id, type(e).__name__)

    if any(_is_stop(m) for m in msgs):
        if to:
            _send(conn, job, REPLY_SEQ, to, STOP_TEXT)
        _forget(conn, job)
        return
    if not to:  # BSUID-only sender, no phone to reply to (D-013): no consent shown, so no user row either
        log.warning("turn job %s: no from_enc; cannot reply (deferred edge)", job.id)
        return

    if not conn.execute("SELECT 1 FROM wa_user WHERE user_key = %s", (u,)).fetchone():
        _send(conn, job, CONSENT_SEQ, to, CONSENT_TEXT)
        conn.execute("INSERT INTO wa_user (user_key, consent_at) VALUES (%s, now()) ON CONFLICT DO NOTHING", (u,))

    conn.execute("INSERT INTO query_state (user_key) VALUES (%s) ON CONFLICT DO NOTHING", (u,))
    state = conn.execute("SELECT state FROM query_state WHERE user_key = %s", (u,)).fetchone()[0]
    _send(conn, job, REPLY_SEQ, to, "\n".join(_echo_body(m) for m in msgs))  # 7.1/7.2/9.1: parse, patch state, render
    conn.execute(
        "UPDATE query_state SET state = %s, version = version + 1, updated_at = now() WHERE user_key = %s", (Jsonb(state), u)
    )
    conn.execute(
        "UPDATE wa_user SET last_inbound_at = GREATEST(last_inbound_at,"
        " (SELECT max(wa_ts) FROM inbound_event WHERE turn_job_id = %s)) WHERE user_key = %s",
        (job.id, u),
    )


def _fail_reason(st: dict) -> str:
    errs = st.get("errors") or []
    return f"meta error code={errs[0].get('code')}" if errs else "failed"  # code only; a message can carry the number


def handle_status(conn, job):
    """Advance the outbound_message this status refers to (forward-only). The status's `id` is our outbound WAMID."""
    payload = _load_payload(conn, job.payload["event_id"])
    if payload is None:
        log.error("status job %s: inbound_event %s missing", job.id, job.payload.get("event_id"))
        return
    st = payload["status"]
    wamid, new = st["id"], st["status"]

    if new == "failed":  # terminal; set unless the row already reached 'read'
        conn.execute(
            "UPDATE outbound_message SET status = 'failed', status_at = now(), last_error = %s"
            " WHERE wamid = %s AND status <> 'read'",
            (_fail_reason(st), wamid),
        )
        return
    rank = STATUS_RANK.get(new)
    if not rank:  # unknown or 'pending' from Meta: nothing to advance to
        log.info("status for %s: ignoring status %r", wamid, new)
        return
    # move forward only: skip if the row is already at/after this state, or terminally failed (handles out-of-order/dupes)
    conn.execute(
        "UPDATE outbound_message SET status = %s, status_at = now()"
        " WHERE wamid = %s AND status <> 'failed'"
        " AND CASE status WHEN 'sent' THEN 1 WHEN 'delivered' THEN 2 WHEN 'read' THEN 3 ELSE 0 END < %s",
        (new, wamid, rank),
    )
