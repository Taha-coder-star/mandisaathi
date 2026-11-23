"""Web role: webhook gateway (task 2.2) and health check."""
import hashlib
import hmac
import os

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

app = FastAPI(title="MandiSaathi")


@app.get("/webhook")
def webhook_verify(request: Request):
    """Meta's subscribe handshake: echo hub.challenge only if our verify token matches."""
    q = request.query_params
    token = os.environ.get("WA_VERIFY_TOKEN", "")
    if token and q.get("hub.mode") == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", ""), token):
        return PlainTextResponse(q.get("hub.challenge", ""))
    return Response(status_code=403)


def signature_ok(body: bytes, header: str | None) -> bool:
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret or not header or not header.startswith("sha256="):
        return False  # fail closed: an empty secret would make signatures forgeable
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


@app.post("/webhook")
async def webhook_receive(request: Request):
    if not signature_ok(await request.body(), request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=401)  # RFC §9: invalid → 401, never processed
    # shortcut: acknowledged but not stored yet; task 3.1 adds inbound_event + job in one transaction
    return Response(status_code=200)


def db_ok() -> bool:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except (KeyError, psycopg.Error):
        return False


@app.get("/health")
def health():
    if db_ok():
        return {"status": "ok", "db": "ok"}
    return JSONResponse({"status": "degraded", "db": "down"}, status_code=503)
