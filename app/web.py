"""Web role: webhook gateway (tasks 2.2, 3.1) and health check."""
import hashlib
import hmac
import json
import logging
import os

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from app import ingest
from app.privacy import PRIVACY_HTML

log = logging.getLogger(__name__)
app = FastAPI(title="MandiSaathi")


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return PRIVACY_HTML


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
    body = await request.body()
    if not signature_ok(body, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=401)  # RFC §9: invalid → 401, never processed
    key = os.environ.get("PHONE_HASH_KEY", "")
    if not key:
        log.error("webhook: PHONE_HASH_KEY not set; not storing")
        return Response(status_code=503)  # fail closed: never store unhashed numbers; Meta redelivers
    try:
        evs = ingest.events(json.loads(body), key)
    except (ValueError, KeyError, TypeError, AttributeError):
        log.warning("webhook: signed but malformed payload")
        return Response(status_code=400)
    if evs:
        try:
            await run_in_threadpool(ingest.store, os.environ["DATABASE_URL"], evs)
        except (KeyError, psycopg.Error) as e:
            # type name only: psycopg messages can carry row data
            log.error("webhook: store failed (%s); rolled back, Meta redelivers", type(e).__name__)
            return Response(status_code=503)
    return Response(status_code=200)  # duplicates land here too (RFC §13)


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
