"""Turn handler (tasks 5.1 + 6.2) and status handler: replies go out once and idempotently; first contact gets consent;
a burst is one turn; STOP deletes the farmer; status webhooks move outbound forward only (RFC C3, C12, §13).

Each test gets a throwaway database (`db` in conftest.py) and stubs the gateway, so no WhatsApp call leaves the process.
The live "echo on all 3 phones; sent → delivered → read" check runs on the VM with the real token (see D-021).
"""
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg.types.json import Jsonb

from app import crypto, gateway, handlers, render, speech
from app import state as qstate
from app.migrate import migrate
from app.worker import Job, run_one
from mandi.gazetteer import load_gazetteer
from mandi.price import PKT, price_now

ENC_KEY = Fernet.generate_key().decode()
NUMBER = "923001234567"


@pytest.fixture
def url(db, monkeypatch):
    migrate(db)
    monkeypatch.setenv("WA_NUMBER_ENC_KEY", ENC_KEY)
    return db


@pytest.fixture
def conn(url):
    with psycopg.connect(url, autocommit=True) as c:
        yield c


class StubGateway:
    """Records mark_read / send_text / send_buttons calls; a send returns a WAMID or raises a preset error.
    sends holds (to, body) for both kinds; buttons holds the button lists of send_buttons calls."""
    def __init__(self, monkeypatch, send_result="wamid.OUT"):
        self.reads, self.sends, self.buttons, self.result = [], [], [], send_result
        monkeypatch.setattr(gateway, "mark_read", lambda mid, typing=True: self.reads.append((mid, typing)))
        monkeypatch.setattr(gateway, "send_text", self._send)
        monkeypatch.setattr(gateway, "send_buttons", self._send_buttons)

    def _send_buttons(self, to, body, buttons, footer=None):
        self.buttons.append(buttons)
        return self._send(to, body)

    def _send(self, to, body):
        self.sends.append((to, body))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result if len(self.sends) == 1 else f"{self.result}.{len(self.sends)}"  # outbound wamid is UNIQUE


@pytest.fixture
def gw(monkeypatch):
    return StubGateway(monkeypatch)


_n = iter(range(1, 10_000))


def seed_turn(conn, text="aloo ka rate", mtype="text", with_enc=True, user="US.F", consented=True, wa_ts=None):
    """Insert an inbound message event + its turn job; return the Job the worker would hand the handler."""
    wamid_in = f"wamid.IN{next(_n)}"
    message = {"id": wamid_in, "type": mtype, "from": "HASHED"}
    if mtype == "text":
        message["text"] = {"body": text}
    if mtype == "audio":
        message["audio"] = {"id": "MEDIA1", "mime_type": "audio/ogg; codecs=opus", "voice": True}
    payload = {"metadata": {"display_phone_number": "15551914461"}, "message": message}
    if with_enc:
        payload["from_enc"] = crypto.encrypt(ENC_KEY, NUMBER)
    if consented:  # most tests are about the reply, not the consent gate
        conn.execute("INSERT INTO wa_user (user_key, consent_at) VALUES (%s, now()) ON CONFLICT DO NOTHING", (user,))
    eid = conn.execute(
        "INSERT INTO inbound_event (dedup_key, kind, user_key, wa_ts, payload) VALUES (%s,'message',%s,%s,%s) RETURNING id",
        (wamid_in, user, wa_ts, Jsonb(payload)),
    ).fetchone()[0]
    jid = conn.execute(
        "INSERT INTO job (kind, user_key, payload) VALUES ('turn',%s,%s) RETURNING id", (user, Jsonb({"event_id": eid}))
    ).fetchone()[0]
    return Job(jid, "turn", user, {"event_id": eid}, 1)


def outbound(conn, job_id, seq=handlers.REPLY_SEQ):
    """(status, wamid, body text, last_error) or None."""
    return conn.execute(
        "SELECT status, wamid, body->>'text', last_error FROM outbound_message WHERE job_id=%s AND seq=%s", (job_id, seq)
    ).fetchone()


# --- turn handler: send path ------------------------------------------------------------------------------------------

ASK_PLACE = render.clarify("place", "ru").text  # reply to the default "aloo ka rate" (no place yet, 10.1)


def test_text_turn_sends_and_logs(conn, gw):
    job = seed_turn(conn)
    handlers.handle_turn(conn, job)
    assert gw.reads == [("wamid.IN1", True)]                 # read receipt + typing on the inbound message
    assert gw.sends == [(NUMBER, ASK_PLACE)]                 # decrypted recipient, the place question
    assert outbound(conn, job.id) == ("sent", "wamid.OUT", ASK_PLACE, None)


def test_non_text_message_echoes_a_note(conn, gw):
    job = seed_turn(conn, mtype="image")
    handlers.handle_turn(conn, job)
    assert gw.sends == [(NUMBER, "Echo: received a image message")]


def test_voice_note_is_downloaded_checked_and_deleted(conn, gw, monkeypatch, tmp_path):
    f = tmp_path / "note.ogg"
    f.write_bytes(b"x" * 42)  # not audio: the 8.1 pre-check stops it before any STT call (tests/test_speech.py has the rest)
    monkeypatch.setattr(gateway, "download_media", lambda mid: str(f) if mid == "MEDIA1" else None)
    handlers.handle_turn(conn, seed_turn(conn, mtype="audio"))
    assert gw.sends == [(NUMBER, speech.FAILED_TEXT)]
    assert not f.exists()  # audio is never kept (OPS §3)


def test_voice_note_retryable_download_reraises_before_any_send(conn, gw, monkeypatch):
    def boom(mid):
        raise gateway.SendRetryable("HTTP 503")
    monkeypatch.setattr(gateway, "download_media", boom)
    job = seed_turn(conn, mtype="audio")
    with pytest.raises(gateway.SendRetryable):
        handlers.handle_turn(conn, job)
    assert gw.sends == [] and outbound(conn, job.id) is None  # nothing recorded, so the retry starts clean


def test_rerun_does_not_resend(conn, gw):
    job = seed_turn(conn)
    handlers.handle_turn(conn, job)
    handlers.handle_turn(conn, job)  # a re-claim after the lease, say
    assert len(gw.sends) == 1
    assert outbound(conn, job.id)[0] == "sent"
    # ...and the state is saved once: version 1, one patch-log row (task 7.2)
    assert conn.execute("SELECT version FROM query_state WHERE user_key = 'US.F'").fetchone() == (1,)
    assert conn.execute("SELECT version, turn_job_id FROM query_patch_log WHERE user_key = 'US.F'").fetchall() == [(1, job.id)]


# --- query state (task 7.2) -------------------------------------------------------------------------------------------

def test_each_turn_writes_one_patch_log_row_and_bumps_the_version(conn, gw):
    jobs = []
    for text in ("pyaz ka rate", "tamatar ka rate"):
        jobs.append(seed_turn(conn, text))
        handlers.handle_turn(conn, jobs[-1])
    rows = conn.execute(
        "SELECT version, patch, message_id, turn_job_id FROM query_patch_log WHERE user_key = 'US.F' ORDER BY id"
    ).fetchall()
    assert [(v, [(x["slot"], x["value"]) for x in p], j) for v, p, _, j in rows] == [
        (1, [("intent", "PRICE_NOW"), ("crop", "ONION")], jobs[0].id),
        (2, [("intent", "PRICE_NOW"), ("crop", "TOMATO")], jobs[1].id)]  # parser output as patches (10.1)
    assert all(m.startswith("wamid.IN") for _, _, m, _ in rows)
    state, version = conn.execute("SELECT state, version FROM query_state WHERE user_key = 'US.F'").fetchone()
    assert qstate.snapshot(state)["crop"] == "TOMATO" and version == 2


def test_state_idle_over_30_days_is_reset_on_load(conn, gw):
    conn.execute("INSERT INTO wa_user (user_key, consent_at) VALUES ('US.F', now())")
    conn.execute("INSERT INTO query_state (user_key, state, version, updated_at) VALUES ('US.F', %s, 4, now() - interval '31 days')",
                 (Jsonb({"crop": {"value": "ONION"}}),))
    qstate.open_clarification(conn, "US.F", "place", [], None, datetime.now(UTC) - timedelta(days=31))
    handlers.handle_turn(conn, seed_turn(conn, "hello"))  # a turn with no patches, so only the reset shows
    assert conn.execute("SELECT state, version FROM query_state WHERE user_key = 'US.F'").fetchone() == ({}, 5)
    assert conn.execute("SELECT count(*) FROM pending_clarification").fetchone() == (0,)


def test_recent_state_is_kept_on_load(conn, gw):
    conn.execute("INSERT INTO wa_user (user_key, consent_at) VALUES ('US.F', now())")
    conn.execute("INSERT INTO query_state (user_key, state, updated_at) VALUES ('US.F', %s, now() - interval '29 days')",
                 (Jsonb({"crop": {"value": "ONION"}}),))
    handlers.handle_turn(conn, seed_turn(conn, "hello"))  # no patches
    assert conn.execute("SELECT state FROM query_state WHERE user_key = 'US.F'").fetchone() == ({"crop": {"value": "ONION"}},)


def test_no_from_enc_is_a_noop(conn, gw):
    job = seed_turn(conn, with_enc=False)  # BSUID-only sender, no number to reply to (D-013)
    handlers.handle_turn(conn, job)
    assert gw.sends == [] and outbound(conn, job.id) is None


def test_retryable_clears_the_row_and_reraises_then_succeeds(conn, monkeypatch):
    gw = StubGateway(monkeypatch, send_result=gateway.SendRetryable("HTTP 503"))
    job = seed_turn(conn)
    with pytest.raises(gateway.SendRetryable):
        handlers.handle_turn(conn, job)
    assert outbound(conn, job.id) is None  # intent cleared so the worker's backoff retry starts clean
    monkeypatch.setattr(gateway, "send_text", lambda to, body: (gw.sends.append((to, body)), "wamid.RETRY")[1])
    handlers.handle_turn(conn, job)
    assert outbound(conn, job.id) == ("sent", "wamid.RETRY", ASK_PLACE, None)


def test_permanent_marks_failed_and_never_retries(conn, monkeypatch):
    gw = StubGateway(monkeypatch, send_result=gateway.SendPermanent("HTTP 400 (code=131)"))
    job = seed_turn(conn)
    handlers.handle_turn(conn, job)  # no raise: retrying cannot help
    status, wamid, _body, err = outbound(conn, job.id)
    assert status == "failed" and wamid is None and "SendPermanent" in err
    handlers.handle_turn(conn, job)
    assert len(gw.sends) == 1  # not resent


def test_ambiguous_stays_pending_and_never_resends(conn, monkeypatch):
    gw = StubGateway(monkeypatch, send_result=gateway.SendAmbiguous("timeout"))
    job = seed_turn(conn)
    handlers.handle_turn(conn, job)  # no raise: maybe delivered
    status, wamid, _body, err = outbound(conn, job.id)
    assert status == "pending" and wamid is None and "SendAmbiguous" in err
    handlers.handle_turn(conn, job)
    assert len(gw.sends) == 1  # never blind-resent (RFC §13)


def test_mark_read_failure_does_not_stop_the_reply(conn, monkeypatch):
    gw = StubGateway(monkeypatch)
    monkeypatch.setattr(gateway, "mark_read", lambda mid, typing=True: (_ for _ in ()).throw(gateway.SendRetryable("x")))
    job = seed_turn(conn)
    handlers.handle_turn(conn, job)
    assert gw.sends == [(NUMBER, ASK_PLACE)] and outbound(conn, job.id)[0] == "sent"


# --- orchestrator skeleton (task 6.2 DONE: consent, burst = 1 turn, STOP deletes) ---------------------------------------

FARMER_TABLES = ("wa_user", "query_state", "inbound_event", "outbound_message", "job",
                 "query_patch_log", "answer_shown", "pending_clarification",  # task 7.2, migration 004
                 "message_log")  # task 8.1, migration 005


def count_for(conn, user):
    """Rows still keyed to this farmer, per table."""
    return {t: conn.execute(f"SELECT count(*) FROM {t} WHERE user_key = %s", (user,)).fetchone()[0] for t in FARMER_TABLES}


def test_first_contact_gets_consent_then_reply_and_only_once(conn, gw):
    handlers.handle_turn(conn, seed_turn(conn, user="US.NEW", consented=False))
    assert gw.sends == [(NUMBER, handlers.CONSENT_TEXT), (NUMBER, ASK_PLACE)]
    assert conn.execute("SELECT consent_at IS NOT NULL FROM wa_user WHERE user_key = 'US.NEW'").fetchone() == (True,)
    handlers.handle_turn(conn, seed_turn(conn, "pyaz", user="US.NEW", consented=False))
    assert gw.sends[2:] == [(NUMBER, render.out_of_scope("ru").text)]  # consent shown once


def test_burst_of_three_pending_messages_is_one_turn(conn, gw):
    t0 = datetime(2026, 11, 30, 9, tzinfo=UTC)
    # stored out of WhatsApp order (webhooks can arrive late): the turn must read them by wa_ts
    jobs = [seed_turn(conn, text, wa_ts=t0 + timedelta(seconds=s)) for text, s in (("Lahore", 2), ("pyaz", 0), ("50 mann", 5))]
    while run_one(conn):
        pass
    assert gw.sends == [(NUMBER, render.out_of_scope("ru").text)]  # one reply: the 3 texts are parsed as one turn text
    assert conn.execute("SELECT DISTINCT status FROM job").fetchall() == [("done",)]
    assert conn.execute("SELECT DISTINCT turn_job_id FROM inbound_event").fetchall() == [(jobs[0].id,)]
    assert conn.execute("SELECT version FROM query_state WHERE user_key = 'US.F'").fetchone() == (1,)
    assert conn.execute("SELECT last_inbound_at FROM wa_user WHERE user_key = 'US.F'").fetchone() == (t0 + timedelta(seconds=5),)


def test_stop_confirms_and_deletes_the_farmer(conn, gw):
    handlers.handle_turn(conn, seed_turn(conn, user="US.GONE", consented=False))  # consent + reply, state + patch log saved
    now = datetime.now(UTC)  # rows the echo turn cannot write yet (7.2 tables), so STOP is proven to delete them too
    qstate.record_answer(conn, "US.GONE", "F2", "run-1", ["LAHORE", "OKARA"], "wamid.ANS", now)
    qstate.open_clarification(conn, "US.GONE", "place", ["OKARA", "LAHORE"], "wamid.Q", now)
    insert_outbound(conn, wamid="wamid.OTHER", user="US.OTHER")  # another farmer's data must survive
    assert all(count_for(conn, "US.GONE")[t] > 0 for t in ("query_patch_log", "answer_shown", "pending_clarification"))
    job = seed_turn(conn, "STOP!", user="US.GONE", consented=False)
    handlers.handle_turn(conn, job)
    assert gw.sends[-1] == (NUMBER, handlers.STOP_TEXT)
    assert count_for(conn, "US.GONE") == dict.fromkeys(FARMER_TABLES, 0)
    assert conn.execute("SELECT message_count FROM stop_tally").fetchall() == [(2,)]  # anonymous count only
    assert conn.execute("SELECT user_key, payload FROM job WHERE id = %s", (job.id,)).fetchone() == (None, {})
    assert count_for(conn, "US.OTHER")["outbound_message"] == 1
    handlers.handle_turn(conn, job._replace(user_key=None))  # re-claim after STOP: nothing to do
    assert len(gw.sends) == 3


def test_stop_as_first_message_skips_consent(conn, gw):
    handlers.handle_turn(conn, seed_turn(conn, "band karo", user="US.S", consented=False))
    assert gw.sends == [(NUMBER, handlers.STOP_TEXT)]
    assert count_for(conn, "US.S")["wa_user"] == 0


@pytest.mark.parametrize("text,stop", [("STOP", True), (" Band  karo ", True), ("بند کرو", True), ("stop!!", True),
                                       ("stop alert", False), ("band", False), ("pyaz ka rate", False)])
def test_stop_words_whole_message_only(text, stop):
    assert handlers._is_stop({"type": "text", "text": {"body": text}}) is stop


def test_retry_after_consent_does_not_resend_consent(conn, monkeypatch):
    sent = []

    def send(to, body):
        sent.append(body)
        if len(sent) == 2:  # consent accepted, then the reply hits a 503
            raise gateway.SendRetryable("HTTP 503")
        return f"wamid.{len(sent)}"
    monkeypatch.setattr(gateway, "mark_read", lambda mid, typing=True: None)
    monkeypatch.setattr(gateway, "send_text", send)
    job = seed_turn(conn, user="US.R", consented=False)
    with pytest.raises(gateway.SendRetryable):
        handlers.handle_turn(conn, job)
    handlers.handle_turn(conn, job)  # the worker's retry
    assert sent == [handlers.CONSENT_TEXT, ASK_PLACE, ASK_PLACE]
    assert conn.execute("SELECT version FROM query_state WHERE user_key = 'US.R'").fetchone() == (1,)


# --- task 10.1: PRICE_NOW end to end (parser → state → price service → renderer → gateway), D-047 ----------------------

@pytest.fixture
def mandi_db(conn):
    load_gazetteer(conn)  # crop / mandi rows for the price_obs foreign keys
    return conn


def put_price(conn, crop, mandi, avg, market_date=None):
    """One OK SYN row, min/max = avg -/+ 100 PKR/100 kg, published a minute ago (so price_now(now) sees it)."""
    now = datetime.now(UTC)
    conn.execute(
        "INSERT INTO price_obs (source, mandi_id, crop_id, market_date, reported_at, min_pkr100kg, max_pkr100kg,"
        " avg_pkr100kg, unit_raw, value_raw, outlier_flag, raw_ref, raw_sha256)"
        " VALUES ('SYN', %s, %s, %s, %s, %s, %s, %s, 'PKR/100kg', %s, 'OK', 't', 'h')",
        (mandi, crop, market_date or now.astimezone(PKT).date(), now - timedelta(minutes=1), avg - 100, avg + 100, avg, avg))


def log_rows(conn, user="US.F"):
    return conn.execute("SELECT direction, intent, tool_calls_json, validator_result FROM message_log WHERE user_key = %s"
                        " ORDER BY id", (user,)).fetchall()


def test_done_scenario_1_consent_then_price_template_with_buttons(mandi_db, gw):
    conn = mandi_db
    put_price(conn, "ONION", "LAHORE", 7000)  # 6,900–7,100 PKR/100 kg = Rs 2,760–2,840 fi mann
    handlers.handle_turn(conn, seed_turn(conn, "Assalam o alaikum, Lahore mein pyaz ka aaj ka rate kya hai?",
                                         user="US.S1", consented=False))
    expected = render.price(price_now(conn, "ONION", "LAHORE", datetime.now(UTC)), "ru")  # the oracle: the seeded row
    assert gw.sends == [(NUMBER, handlers.CONSENT_TEXT), (NUMBER, expected.text)]  # consent once, then the price
    body = gw.sends[1][1]
    assert body.startswith("Pyaz · Lahore · Rs 2,760–2,840 fi mann (40 kg) · ") and "Demo data (synthetic)" in body
    assert gw.buttons == [expected.buttons] and [b["id"] for b in gw.buttons[0]] == ["F1", "F2", "ALERT"]
    (d_in, i_in, t_in, v_in), (d_out, i_out, _, v_out) = log_rows(conn, "US.S1")
    assert (d_in, i_in, t_in, v_in) == ("in", "PRICE_NOW", [{"name": "price_now", "args": {"crop": "ONION", "mandi": "LAHORE"}}], None)
    assert (d_out, i_out, v_out) == ("out", "PRICE_NOW", {"used": "template_only", "attempts": []})  # no LLM-written number
    state = conn.execute("SELECT state FROM query_state WHERE user_key = 'US.S1'").fetchone()[0]
    assert qstate.snapshot(state) == {"intent": "PRICE_NOW", "crop": "ONION", "place": {"canonical": "LAHORE", "role": "MANDI"},
                                      "quantity_kg": None, "horizon": {"kind": "TODAY"}}
    body_json = conn.execute("SELECT body FROM outbound_message WHERE user_key = 'US.S1' AND seq = 1").fetchone()[0]
    assert body_json["type"] == "buttons" and body_json["buttons"] == expected.buttons


def test_price_now_without_a_rate_says_so_and_sends_no_number(mandi_db, gw):
    handlers.handle_turn(mandi_db, seed_turn(mandi_db, "Multan mein tamatar ka rate"))
    assert gw.sends == [(NUMBER, render.price(None, "ru", "TOMATO", "MULTAN").text)] and gw.buttons == []
    assert "maujood nahi" in gw.sends[0][1] and not any(c.isdigit() for c in gw.sends[0][1])


def test_two_crops_get_both_rates_in_one_message(mandi_db, gw):
    put_price(mandi_db, "ONION", "LAHORE", 7000)
    put_price(mandi_db, "POTATO", "LAHORE", 4000)
    handlers.handle_turn(mandi_db, seed_turn(mandi_db, "Lahore mein pyaz aur aloo ka rate"))
    body = gw.sends[0][1]
    lines = body.split("\n")
    assert lines[0].startswith("Pyaz · Lahore") and lines[1].startswith("Aloo · Lahore") and len(lines) == 2
    assert all(line.endswith(" · Demo data (synthetic)") for line in lines)  # date + source on every rate (never cut)


def test_stale_rate_gets_the_stale_line(mandi_db, gw):
    put_price(mandi_db, "ONION", "LAHORE", 7000, market_date=datetime.now(UTC).date() - timedelta(days=10))
    handlers.handle_turn(mandi_db, seed_turn(mandi_db, "Lahore mein pyaz ka rate"))
    assert "Taaza rate nahi mila" in gw.sends[0][1]


@pytest.mark.parametrize("text, lang", [("onion rate in Lahore", "en"), ("لاہور میں پیاز کا ریٹ کیا ہے", "ur")])
def test_reply_language_follows_the_message(mandi_db, gw, text, lang):
    put_price(mandi_db, "ONION", "LAHORE", 7000)
    handlers.handle_turn(mandi_db, seed_turn(mandi_db, text))
    assert gw.sends == [(NUMBER, render.price(price_now(mandi_db, "ONION", "LAHORE", datetime.now(UTC)), lang).text)]


def test_ambiguous_place_asks_with_candidate_buttons_and_is_not_stored(conn, gw):
    handlers.handle_turn(conn, seed_turn(conn, "Khan mein pyaz ka rate"))
    assert [b["id"] for b in gw.buttons[0]] == ["PLACE:DGKHAN", "PLACE:RYKHAN"]
    state = conn.execute("SELECT state FROM query_state WHERE user_key = 'US.F'").fetchone()[0]
    assert "place" not in state and state["crop"]["value"] == "ONION"  # only RESOLVED slots become state


@pytest.mark.parametrize("text, reply", [
    ("Hyderabad mein pyaz ka rate", render.out_of_coverage("ru")),        # outside Punjab
    ("Multan mein kapaas ka bhaao", render.out_of_coverage("ru")),        # crop not covered
    ("mausam kaisa hai", render.out_of_scope("ru")),                      # not a mandi question
    ("help", render.help_text("en")),
    ("Lahore mein kal pyaz ka rate kya hoga", render.unknown("ru")),      # FORECAST: wired in 13.1
])
def test_other_outcomes_get_their_fixed_template(conn, gw, text, reply):
    handlers.handle_turn(conn, seed_turn(conn, text))
    assert gw.sends == [(NUMBER, reply.text)]


def test_voice_turn_keeps_the_echo_and_writes_no_patches(conn, gw, monkeypatch, tmp_path):
    f = tmp_path / "note.ogg"
    f.write_bytes(b"x" * 42)
    monkeypatch.setattr(gateway, "download_media", lambda mid: str(f))
    handlers.handle_turn(conn, seed_turn(conn, mtype="audio"))
    assert gw.sends == [(NUMBER, speech.FAILED_TEXT)]  # the 6.4 recording procedure relies on this path (D-047)
    assert conn.execute("SELECT patch FROM query_patch_log WHERE user_key = 'US.F'").fetchone() == ([],)


# --- status handler (forward-only) ------------------------------------------------------------------------------------

def insert_outbound(conn, wamid="wamid.OUT", status="sent", user="US.F"):
    jid = conn.execute("INSERT INTO job (kind, user_key) VALUES ('turn',%s) RETURNING id", (user,)).fetchone()[0]
    conn.execute(
        "INSERT INTO outbound_message (job_id, seq, user_key, wamid, body, status) VALUES (%s,0,%s,%s,%s,%s)",
        (jid, user, wamid, Jsonb({"type": "text", "text": "hi"}), status),
    )
    return wamid


def seed_status(conn, wamid, st, errors=None):
    status = {"id": wamid, "status": st, "recipient_id": "HASHED"}
    if errors:
        status["errors"] = errors
    payload = {"metadata": {"display_phone_number": "15551914461"}, "status": status}
    eid = conn.execute(
        "INSERT INTO inbound_event (dedup_key, kind, user_key, payload) VALUES (%s,'status','US.F',%s) RETURNING id",
        (f"{wamid}:{st}:{next(_n)}", Jsonb(payload)),
    ).fetchone()[0]
    jid = conn.execute(
        "INSERT INTO job (kind, user_key, payload) VALUES ('status','US.F',%s) RETURNING id", (Jsonb({"event_id": eid}),)
    ).fetchone()[0]
    return Job(jid, "status", "US.F", {"event_id": eid}, 1)


def current(conn, wamid):
    return conn.execute("SELECT status, last_error FROM outbound_message WHERE wamid=%s", (wamid,)).fetchone()


def test_status_advances_sent_delivered_read(conn):
    w = insert_outbound(conn, status="sent")
    for st in ("delivered", "read"):
        handlers.handle_status(conn, seed_status(conn, w, st))
    assert current(conn, w)[0] == "read"


def test_status_never_regresses(conn):
    w = insert_outbound(conn, status="read")
    handlers.handle_status(conn, seed_status(conn, w, "delivered"))  # out-of-order / duplicate
    assert current(conn, w)[0] == "read"


def test_status_failed_is_terminal(conn):
    w = insert_outbound(conn, status="sent")
    handlers.handle_status(conn, seed_status(conn, w, "failed", errors=[{"code": 131026}]))
    assert current(conn, w) == ("failed", "meta error code=131026")
    handlers.handle_status(conn, seed_status(conn, w, "delivered"))  # a late delivered must not revive it
    assert current(conn, w)[0] == "failed"


def test_status_for_unknown_wamid_is_a_noop(conn):
    insert_outbound(conn, wamid="wamid.KNOWN", status="sent")
    handlers.handle_status(conn, seed_status(conn, "wamid.GHOST", "delivered"))  # no row: must not error
    assert current(conn, "wamid.KNOWN")[0] == "sent"
