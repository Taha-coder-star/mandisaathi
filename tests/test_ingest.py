"""Task 3.1 DONE check: the same webhook payload posted twice -> exactly 1 inbound_event and 1 job (RFC §3 step 1, §13)."""
import hashlib
import hmac
import json
import re

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import ingest
from app.migrate import migrate
from app.web import app

SECRET = "test-app-secret"
KEY = "test-hash-key"
PHONE = "923001234567"


def setenv(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    monkeypatch.setenv("PHONE_HASH_KEY", KEY)
    return TestClient(app)


@pytest.fixture
def client(db, monkeypatch):
    migrate(db)
    return setenv(monkeypatch, db)


@pytest.fixture
def nodb(monkeypatch):
    return setenv(monkeypatch, "postgresql://x@127.0.0.1:1/x")  # nothing listens on port 1


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def post(client, payload, signed=True):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} | ({"X-Hub-Signature-256": sign(body)} if signed else {})
    return client.post("/webhook", content=body, headers=headers)


def envelope(field="messages", **value):
    """Meta Cloud API (v27) webhook body with one change."""
    metadata = {"display_phone_number": "15551914461", "phone_number_id": "PNID"}
    value = {"messaging_product": "whatsapp", "metadata": metadata, **value}
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{"field": field, "value": value}]}]}


def msg(wamid, frm=PHONE, user_id="US.111", ts=1764000000):
    m = {"id": wamid, "timestamp": str(ts), "type": "text", "text": {"body": "aloo ka rate"}}
    return m | ({"from": frm} if frm else {}) | ({"from_user_id": user_id} if user_id else {})


def messages(*ms):
    contacts = [{"profile": {"name": "Farmer"}} | ({"wa_id": m["from"]} if "from" in m else {})
                | ({"user_id": m["from_user_id"]} if "from_user_id" in m else {}) for m in ms]
    return envelope(contacts=contacts, messages=list(ms))


def status(wamid, st, ts=1764000100):
    return envelope(statuses=[{"id": wamid, "status": st, "timestamp": str(ts), "recipient_id": PHONE}])


def rows(db):
    with psycopg.connect(db) as c:
        events = c.execute("SELECT id, dedup_key, kind, user_key, payload::text FROM inbound_event ORDER BY id").fetchall()
        jobs = c.execute("SELECT kind, user_key, payload->>'event_id', payload::text FROM job ORDER BY id").fetchall()
    return events, jobs


def test_phash_ignores_formatting():
    assert ingest.phash(KEY, "+92 300-1234567") == ingest.phash(KEY, PHONE) != ingest.phash("other-key", PHONE)


def test_same_payload_twice_one_event_one_job(client, db):
    payload = messages(msg("wamid.A"))
    assert post(client, payload).status_code == 200
    assert post(client, payload).status_code == 200
    events, jobs = rows(db)
    assert len(events) == 1 and len(jobs) == 1
    assert jobs[0][0] == "turn"
    assert int(jobs[0][2]) == events[0][0]
    assert jobs[0][1] == events[0][3] == "US.111"


def test_multi_message_payload(client, db):
    payload = messages(msg("wamid.A"), msg("wamid.B"))
    assert post(client, payload).status_code == 200
    assert [len(r) for r in rows(db)] == [2, 2]
    assert post(client, payload).status_code == 200
    assert [len(r) for r in rows(db)] == [2, 2]
    assert post(client, messages(msg("wamid.B"), msg("wamid.C"))).status_code == 200
    assert [len(r) for r in rows(db)] == [3, 3]


def test_status_key_is_wamid_and_status(client, db):
    for st in ("sent", "delivered", "delivered"):
        assert post(client, status("wamid.X", st)).status_code == 200
    events, jobs = rows(db)
    assert [(e[1], e[2]) for e in events] == [("wamid.X:sent", "status"), ("wamid.X:delivered", "status")]
    assert [j[0] for j in jobs] == ["status", "status"]


def test_user_id_only_message(client, db):
    assert post(client, messages(msg("wamid.U", frm=None, user_id="US.123"))).status_code == 200
    events, jobs = rows(db)
    assert events[0][3] == jobs[0][1] == "US.123"


def test_phone_numbers_not_stored(client, db):
    phones = [{"phone": "+92 321 7654321", "wa_id": "923217654321", "type": "CELL"}]
    card = {"name": {"formatted_name": "Bhai"}, "phones": phones}
    shared = msg("wamid.S", user_id=None) | {"type": "contacts", "contacts": [card]}
    assert post(client, messages(shared)).status_code == 200
    assert post(client, messages(msg("wamid.T", user_id=None))).status_code == 200
    events, jobs = rows(db)
    stored = " ".join(e[4] for e in events) + " ".join(j[3] for j in jobs)
    for number in (PHONE, "7654321", "923217654321"):
        assert number not in stored
    assert re.fullmatch(r"[0-9a-f]{64}", events[0][3])
    assert events[0][3] == events[1][3] == jobs[0][1] == jobs[1][1]  # same number -> same key, so rows join


def test_failure_rolls_back_event_and_job(client, db):
    with psycopg.connect(db, autocommit=True) as c:
        c.execute("ALTER TABLE job ADD CONSTRAINT no_jobs CHECK (false)")
    payload = messages(msg("wamid.R"))
    assert post(client, payload).status_code == 503
    assert rows(db) == ([], [])
    with psycopg.connect(db, autocommit=True) as c:
        c.execute("ALTER TABLE job DROP CONSTRAINT no_jobs")
    assert post(client, payload).status_code == 200  # Meta's redelivery now lands
    assert [len(r) for r in rows(db)] == [1, 1]


def test_db_down_is_503(nodb):
    assert post(nodb, messages(msg("wamid.D"))).status_code == 503


def test_missing_hash_key_is_503(nodb, monkeypatch):
    monkeypatch.delenv("PHONE_HASH_KEY")
    assert post(nodb, messages(msg("wamid.K"))).status_code == 503


@pytest.mark.parametrize("body", [b"{not json", b"[1]", json.dumps(envelope(messages=[{"timestamp": "1"}])).encode()])
def test_signed_but_malformed_is_400(nodb, body):
    assert post(nodb, body).status_code == 400
    assert post(nodb, body, signed=False).status_code == 401


def test_other_fields_acked_not_stored(client, db):
    payload = envelope(field="message_template_status_update", event="APPROVED", message_template_name="price_alert")
    assert post(client, payload).status_code == 200
    assert rows(db) == ([], [])
