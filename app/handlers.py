"""Worker job handlers. Registered in app.worker.HANDLERS.

`handle_turn` is the conversation orchestrator skeleton (task 6.2, RFC C3; choices: DECISIONS.md D-028):
  1. coalesce: take every not-yet-taken message of the farmer (stamped with this job's id), in WhatsApp-timestamp order;
     the other turn jobs of the same burst then find nothing and finish silently;
  2. STOP / "band karo" anywhere in the turn: confirm, then delete the farmer's rows, keeping only an anonymous count;
  3. consent gate: first contact gets the consent + AI disclosure text, then the turn is answered (file 10 scenario 1);
  4. load query_state (reset after 30 days idle), apply the turn's patches, build the reply, save query_state (version + 1)
     with one query_patch_log row, once per turn job (app/state.py, task 7.2, D-032).
Text turns (task 10.1, D-047): the turn's texts, joined in order → rule parser (7.1) → RESOLVED slots as state patches →
the parser's outcome for this turn decides the reply: PRICE_NOW → price service (8.2) → price template (9.1); CLARIFY,
out of coverage / scope and HELP → their fixed templates; intents not wired yet (FORECAST, WHERE_TO_SELL, OUTLOOK, ALERT:
13.1/16.1) → the fixed "maloomat nahi" reply. Every reply goes through render.compose (no LLM until 11.2) and is logged in
message_log with the parser's intent, tool calls and the validator result. Follow-ups from the stored state are 14.2.
Voice notes and other message types keep the echo reply (the 6.4 recording procedure expects it; voice → parser is 13.2).
Voice notes are transcribed inside the turn by app/speech.py (task 8.1, D-035) and logged in message_log.

`handle_status` advances the matching outbound_message as Meta reports sent → delivered → read (forward-only; never
regresses, never moves past a terminal 'failed').

Send idempotency follows the transactional outbox (RFC §13): one outbound row per (job_id, seq); a row that already
carries a WAMID is a no-op on re-claim; a retryable failure clears the intent so the worker's backoff can try again; an
ambiguous outcome leaves the row 'pending' and is never resent. Choices: DECISIONS.md D-021.
"""
import logging
import os
import re
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app import crypto, gateway, render, speech
from app import state as qstate
from app.render import CONSENT_TEXT, STOP_TEXT  # noqa: F401  (tests read them as handlers.*)
from mandi import price as prices
from mandi.gazetteer import read as read_gazetteer
from mandi.parse import STOP_WORDS, parse  # STOP_WORDS: single source of truth for the stop keywords (7.1, handoff §3.2)
from mandi.resolve import resolve_place

log = logging.getLogger(__name__)

CONSENT_SEQ, REPLY_SEQ = 0, 1  # fixed per turn, so a re-claimed job finds what it already sent

# Meta delivery states, in order; 'pending' (not yet sent) ranks 0 so the first 'sent' advances it. 'failed' is terminal.
STATUS_RANK = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}


def _load_payload(conn, event_id: int) -> dict | None:
    row = conn.execute("SELECT payload FROM inbound_event WHERE id = %s", (event_id,)).fetchone()
    return row[0] if row else None


def _voice(conn, user_key: str, msg: dict) -> str:
    """Transcribe the voice note inside the turn (task 8.1, RFC §4; never its own job, file 09 R-02) and store it in message_log.

    A re-claimed turn finds the row by WAMID and reuses it: no second download, no second STT call (free-tier quota).
    Download SendRetryable propagates so the worker retries the turn (no STT spent yet); STT failures never raise.
    The audio file is deleted right after transcription (OPS §3).
    """
    row = conn.execute("SELECT text_or_transcript, stt_meta FROM message_log WHERE wamid = %s", (msg["id"],)).fetchone()
    if row:
        text, meta = row
    else:
        try:
            path = gateway.download_media(msg["audio"]["id"])
        except gateway.SendPermanent as e:
            log.error("voice %s: download failed (%s)", msg["id"], type(e).__name__)
            text, meta = None, {"precheck": "DOWNLOAD_FAILED", "attempts": []}
        else:
            try:
                text, meta = speech.transcribe(path)
            finally:
                os.remove(path)
        conn.execute(
            "INSERT INTO message_log (user_key, wamid, direction, modality, text_or_transcript, stt_meta)"
            " VALUES (%s, %s, 'in', 'voice', %s, %s) ON CONFLICT (wamid) DO NOTHING",
            (user_key, msg["id"], text, Jsonb(meta)),
        )
    out = speech.reply(text, meta)
    return "Echo: " + out if text else out  # 9.1: the transcript goes to the parser instead of being echoed


def _echo_body(conn, user_key: str, msg: dict) -> str:
    if msg.get("type") == "text":
        return "Echo: " + msg["text"]["body"]
    if msg.get("type") == "audio":
        return _voice(conn, user_key, msg)
    return f"Echo: received a {msg.get('type', '?')} message"


def _is_stop(msg: dict) -> bool:
    if msg.get("type") != "text":
        return False
    return " ".join(re.sub(r"[^\w\s]", " ", msg["text"]["body"].casefold()).split()) in STOP_WORDS


def _send(conn, job, seq: int, to: str, body: str, buttons: list[dict] | None = None) -> str | None:
    """Send one text (or text + reply buttons) through the outbox row (job_id, seq). Returns the WAMID once sent (also on a
    re-claim that finds it sent), else None. Raises SendRetryable (worker retries); other failures are kept."""
    existing = conn.execute(
        "SELECT status, wamid FROM outbound_message WHERE job_id = %s AND seq = %s", (job.id, seq)
    ).fetchone()
    if existing:
        status, wamid = existing
        # already sent (crash-safe no-op), or a prior pending/ambiguous we must never blind-resend, or a recorded failure
        if wamid or status != "failed":
            log.info("turn job %s: outbound seq %s already %s; no resend", job.id, seq, status)
        return wamid
    out = {"type": "buttons", "text": body, "buttons": buttons} if buttons else {"type": "text", "text": body}
    # record the intent BEFORE the network call so a re-claim after a crash sees it and will not double-send (RFC §13)
    conn.execute(
        "INSERT INTO outbound_message (job_id, seq, user_key, body, status) VALUES (%s, %s, %s, %s, 'pending')",
        (job.id, seq, job.user_key, Jsonb(out)),
    )
    try:
        wamid = gateway.send_buttons(to, body, buttons) if buttons else gateway.send_text(to, body)
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
        return None
    except gateway.SendAmbiguous as e:
        # maybe delivered: leave the row 'pending' so any re-claim refuses to resend (RFC §13 "no blind resend")
        conn.execute(
            "UPDATE outbound_message SET last_error = %s WHERE job_id = %s AND seq = %s",
            (f"{type(e).__name__}: {e}"[:500], job.id, seq),
        )
        log.error("turn job %s: ambiguous send; left pending, will not resend", job.id)
        return None
    conn.execute(
        "UPDATE outbound_message SET wamid = %s, status = 'sent', status_at = now() WHERE job_id = %s AND seq = %s",
        (wamid, job.id, seq),
    )
    return wamid


# --- text turn: parser → state → tool → template (task 10.1, D-047) ----------------------------------------------------

STATE_INTENTS = ("PRICE_NOW", "FORECAST", "WHERE_TO_SELL", "OUTLOOK", "ALERT")  # HELP / OTHER / STOP are not stored


def _patches(parsed: dict) -> list[dict]:
    """The turn's RESOLVED slots as state patches (op set). An unknown, ambiguous or out-of-coverage place, a crop list, a
    bori without weight or a bare 'kal' is never stored: the reply asks about it instead."""
    s, out = parsed["slots"], []
    if parsed["intent"] in STATE_INTENTS:
        out.append({"slot": "intent", "op": "set", "raw": None, "value": parsed["intent"]})
    crop = s["crop"]
    if isinstance(crop, dict) and crop["id"] in read_gazetteer()["crops"]:
        out.append({"slot": "crop", "op": "set", "raw": crop["raw"], "value": crop["id"]})
    place = s["place"]
    if place and place["status"] == "RESOLVED":
        mandis = list(resolve_place(place["raw"]).mandi_ids) or [place["canonical"]]
        out.append({"slot": "place", "op": "set", "raw": place["raw"], "value": {
            "canonical": place["canonical"], "status": "RESOLVED", "role": place["role"], "mandi_ids": mandis}})
    q = s["quantity"]
    if q and q.get("value_kg") is not None:
        out.append({"slot": "quantity", "op": "set", "raw": q.get("raw"),
                    "value": {"value": q["value"], "unit": q["unit"], "value_kg": q["value_kg"]}})
    h = s["horizon"]
    if h and h["kind"] != "AMBIGUOUS":
        out.append({"slot": "horizon", "op": "set", "raw": None, "value": h})
    return out


def _calls(parsed: dict) -> list[dict]:
    t = parsed["tool"]
    return [] if t is None else t if isinstance(t, list) else [t]


def _facts(conn, parsed: dict, lang: str, now: datetime) -> tuple[render.Reply, set[str]]:
    """The template reply for this turn's parse, and the place ids it may name (validator `allowed`)."""
    outcome, intent = parsed["outcome"], parsed["intent"]
    if outcome == "OUT_OF_COVERAGE":
        return render.out_of_coverage(lang), set()
    if outcome == "OUT_OF_SCOPE":
        return render.out_of_scope(lang), set()
    if outcome == "CLARIFY":
        slot, place = parsed["clarify_slot"], parsed["slots"]["place"]
        cands = list(resolve_place(place["raw"]).ids) if slot == "place" and place and place["status"] == "AMBIGUOUS" else None
        unknown = slot == "place" and place is not None and place["status"] == "UNKNOWN"  # named but not found (D-045)
        return render.clarify(slot, lang, cands, unknown_place=unknown), set(cands or ())
    if intent == "HELP":
        return render.help_text(lang), set()
    if intent == "PRICE_NOW":
        calls = _calls(parsed)
        replies = [render.price(prices.price_now(conn, c["args"]["crop"], c["args"]["mandi"], now), lang,
                                c["args"]["crop"], c["args"]["mandi"]) for c in calls]
        return (replies[0] if len(replies) == 1 else render.join(replies)), {c["args"]["mandi"] for c in calls}
    return render.unknown(lang), set()  # FORECAST / WHERE_TO_SELL / OUTLOOK / ALERT answers: 13.1 / 16.1


def _text_turn(conn, job, to: str, msgs: list[dict], state: dict, now: datetime) -> tuple[dict, list[dict]]:
    """Answer a text-only turn; returns (state after the patches, patches) for the caller's save."""
    u = job.user_key
    text = "\n".join(m["text"]["body"] for m in msgs)
    lang = render.pick_lang(text)
    parsed = parse(text, now.astimezone(prices.PKT).date())
    patches = _patches(parsed)
    state = qstate.apply(state, patches, "text", now)
    facts, allowed = _facts(conn, parsed, lang, now)
    reply, validator = render.compose(facts, None, allowed)  # no framing LLM until 11.2: template only
    calls = Jsonb(_calls(parsed))
    for i, m in enumerate(msgs):  # the parse belongs to the turn: logged on its last message
        last = i == len(msgs) - 1
        conn.execute(
            "INSERT INTO message_log (user_key, wamid, direction, modality, text_or_transcript, intent, tool_calls_json)"
            " VALUES (%s, %s, 'in', 'text', %s, %s, %s) ON CONFLICT (wamid) DO NOTHING",
            (u, m["id"], m["text"]["body"], parsed["intent"] if last else None, calls if last else None),
        )
    wamid = _send(conn, job, REPLY_SEQ, to, reply.text, reply.buttons)
    if wamid:
        conn.execute(
            "INSERT INTO message_log (user_key, wamid, direction, modality, text_or_transcript, intent, tool_calls_json,"
            " validator_result) VALUES (%s, %s, 'out', 'text', %s, %s, %s, %s) ON CONFLICT (wamid) DO NOTHING",
            (u, wamid, reply.text, parsed["intent"], calls, Jsonb(validator)),
        )
    return state, patches


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
        conn.execute("DELETE FROM wa_user WHERE user_key = %s", (u,))
        # ^ cascades to query_state, query_patch_log, answer_shown, pending_clarification, message_log
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

    now = datetime.now(UTC)
    state = qstate.load(conn, u, now)
    if all(m.get("type") == "text" for m in msgs):
        state, patches = _text_turn(conn, job, to, msgs, state, now)
    else:  # voice / other types: echo (voice → parser is 13.2); no patches, the state round-trips unchanged
        patches = []
        # voice notes are transcribed here, after STOP and the consent row (message_log references wa_user), in wa_ts order
        _send(conn, job, REPLY_SEQ, to, "\n".join(_echo_body(conn, u, m) for m in msgs))
    qstate.save(conn, u, state, patches, msgs[-1].get("id"), job.id)  # version + 1 and one query_patch_log row
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
