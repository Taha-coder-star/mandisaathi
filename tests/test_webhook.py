import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app.web import app

SECRET = "test-app-secret"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", SECRET)
    monkeypatch.setenv("WA_VERIFY_TOKEN", "test-verify-token")
    return TestClient(app)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post(client, headers):
    return client.post("/webhook", content=BODY, headers={"Content-Type": "application/json", **headers})


def test_verify_handshake(client):
    r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token", "hub.challenge": "11582014"})
    assert r.status_code == 200
    assert r.text == "11582014"


@pytest.mark.parametrize("params", [
    {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "x"},
    {"hub.mode": "unsubscribe", "hub.verify_token": "test-verify-token", "hub.challenge": "x"},
    {},
])
def test_verify_rejects(client, params):
    assert client.get("/webhook", params=params).status_code == 403


def test_verify_rejects_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("WA_VERIFY_TOKEN")
    assert client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "x"}).status_code == 403


def test_signed_post_accepted(client):
    assert post(client, {"X-Hub-Signature-256": sign(BODY)}).status_code == 200


@pytest.mark.parametrize("headers", [
    {},                                                     # unsigned
    {"X-Hub-Signature-256": sign(BODY, "other-secret")},   # wrong key
    {"X-Hub-Signature-256": sign(BODY + b" ")},            # body tampered
    {"X-Hub-Signature-256": sign(BODY)[7:]},               # missing sha256= prefix
    {"X-Hub-Signature-256": "sha256=zz"},
])
def test_bad_post_rejected(client, headers):
    assert post(client, headers).status_code == 401


def test_post_rejected_when_secret_unset(client, monkeypatch):
    monkeypatch.delenv("META_APP_SECRET")
    assert post(client, {"X-Hub-Signature-256": sign(BODY, "")}).status_code == 401
