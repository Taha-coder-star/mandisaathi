"""Worker job handlers (task 5.1). Registered in app.worker.HANDLERS.

`handle_turn` is a TEMPORARY echo bot: it replies to the farmer's message with the same text, to prove the inbound →
queue → worker → outbound → status loop end to end (M1). Task 6.2 replaces it with the real orchestrator (consent gate,
coalescing, state, STOP).

`handle_status` is PERMANENT: it advances the matching outbound_message as Meta reports sent → delivered → read
(forward-only; never regresses, never moves past a terminal 'failed').

Send idempotency follows the transactional outbox (RFC §13): one outbound row per (job_id, seq); a row that already
carries a WAMID is a no-op on re-claim; a retryable failure clears the intent so the worker's backoff can try again; an
ambiguous outcome leaves the row 'pending' and is never resent. Choices: DECISIONS.md D-021.
"""
import logging
import os

from psycopg.types.json import Jsonb

from app import crypto, gateway

log = logging.getLogger(__name__)

ECHO_SEQ = 0  # the echo bot sends exactly one message per turn

# Meta delivery states, in order; 'pending' (not yet sent) ranks 0 so the first 'sent' advances it. 'failed' is terminal.
STATUS_RANK = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}


def _load_payload(conn, event_id: int) -> dict | None:
    row = conn.execute("SELECT payload FROM inbound_event WHERE id = %s", (event_id,)).fetchone()
    return row[0] if row else None


def _audio_echo(msg: dict) -> str:
    """Download the voice note (task 5.2), report it, delete it: no STT until 6.x and audio is never kept (OPS §3).

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
    return f"Echo: received a {msg.get('type', '?')} message"  # non-text inbound: a short note (echo bot only, task 6.x parses)


def handle_turn(conn, job):
    """Echo the farmer's message back (temporary; task 6.2 replaces). conn is the worker's autocommit connection."""
    payload = _load_payload(conn, job.payload["event_id"])
    if payload is None:
        log.error("turn job %s: inbound_event %s missing; nothing to echo", job.id, job.payload.get("event_id"))
        return
    msg = payload["message"]

    existing = conn.execute(
        "SELECT status, wamid FROM outbound_message WHERE job_id = %s AND seq = %s", (job.id, ECHO_SEQ)
    ).fetchone()
    if existing:
        status, wamid = existing
        # already sent (crash-safe no-op), or a prior pending/ambiguous we must never blind-resend, or a recorded failure
        if wamid or status != "failed":
            log.info("turn job %s: outbound seq %s already %s; no resend", job.id, ECHO_SEQ, status)
        return

    enc = payload.get("from_enc")
    if not enc:  # BSUID-only sender, no phone to reply to (D-013); nothing to do yet
        log.warning("turn job %s: no from_enc; cannot reply (deferred edge)", job.id)
        return
    to = crypto.decrypt(os.environ["WA_NUMBER_ENC_KEY"], enc)

    try:  # read receipt + typing is best-effort: a failure here must not stop the reply
        gateway.mark_read(msg["id"], typing=True)
    except gateway.SendError as e:
        log.info("turn job %s: mark_read failed (%s); continuing", job.id, type(e).__name__)

    body = _echo_body(msg)
    # record the intent BEFORE the network call so a re-claim after a crash sees it and will not double-send (RFC §13)
    conn.execute(
        "INSERT INTO outbound_message (job_id, seq, user_key, body, status) VALUES (%s, %s, %s, %s, 'pending')",
        (job.id, ECHO_SEQ, job.user_key, Jsonb({"type": "text", "text": body})),
    )
    try:
        wamid = gateway.send_text(to, body)
    except gateway.SendRetryable:
        # not accepted; clear the intent so the worker's backoff retry starts clean
        conn.execute("DELETE FROM outbound_message WHERE job_id = %s AND seq = %s", (job.id, ECHO_SEQ))
        raise  # worker records a failed attempt and re-queues with backoff (max 5)
    except gateway.SendPermanent as e:
        conn.execute(
            "UPDATE outbound_message SET status = 'failed', last_error = %s WHERE job_id = %s AND seq = %s",
            (f"{type(e).__name__}: {e}"[:500], job.id, ECHO_SEQ),
        )
        log.error("turn job %s: permanent send failure; not retried", job.id)  # farmer fallback reply is task 17.1
        return
    except gateway.SendAmbiguous as e:
        # maybe delivered: leave the row 'pending' so any re-claim refuses to resend (RFC §13 "no blind resend")
        conn.execute(
            "UPDATE outbound_message SET last_error = %s WHERE job_id = %s AND seq = %s",
            (f"{type(e).__name__}: {e}"[:500], job.id, ECHO_SEQ),
        )
        log.error("turn job %s: ambiguous send; left pending, will not resend", job.id)
        return
    conn.execute(
        "UPDATE outbound_message SET wamid = %s, status = 'sent', status_at = now() WHERE job_id = %s AND seq = %s",
        (wamid, job.id, ECHO_SEQ),
    )
    log.info("turn job %s: echoed (wamid stored)", job.id)


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
