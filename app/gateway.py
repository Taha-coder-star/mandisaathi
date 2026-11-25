"""WhatsApp Cloud API adapter (task 5.1, RFC C12). Runs in the worker role.

All outbound Cloud API calls go through here: text, reply buttons, list, location, location request, templates, and
mark-read + typing. One choke point, `_post`, does the HTTP and turns Meta's responses into three typed outcomes the
worker's retry logic (RFC §13) understands:

  SendRetryable  429 / 5xx / connection refused — the message was NOT accepted; the worker backs off and retries (max 5).
  SendPermanent  other 4xx / bad config         — retrying cannot help; the job is dead-lettered.
  SendAmbiguous  timeout / reset after the request left — maybe delivered; RFC §13 "no blind resend", so never retry.

stdlib urllib only (no new runtime dependency, D-021). Config is read from the environment per call, so tests and the
three roles share one import. Message/analysis numbers never appear in exceptions or logs: only the HTTP status and
Meta's numeric error code are surfaced (a Meta error message can echo the recipient number).
"""
import hashlib
import json
import mimetypes
import os
import socket
import tempfile
import urllib.error
import urllib.request

GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_VERSION = "v21.0"
TIMEOUT_S = 10.0  # one send is quick; well under the 12 s turn budget (RFC §13)

# file 06 §1 limits (verified against Meta docs 2026-10-01); a caller that breaks these has a bug, so it is a ValueError.
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_ROW_TITLE = 24
MAX_ROW_DESC = 72
MAX_BODY = 1024


class SendError(Exception):
    """Base for all Cloud API call failures (sends and media downloads)."""


class SendRetryable(SendError):
    """429 / 5xx / connection refused: not accepted, safe to retry (worker backoff, max 5)."""


class SendPermanent(SendError):
    """Other 4xx or bad config: retrying cannot help; dead-letter."""


class SendAmbiguous(SendError):
    """Request left but no usable response (timeout / reset): maybe delivered; never blind-resend (RFC §13)."""


def _version() -> str:
    return os.environ.get("GRAPH_API_VERSION") or DEFAULT_VERSION


def _endpoint() -> str:
    pnid = os.environ.get("WA_PHONE_NUMBER_ID")
    if not pnid:
        raise SendPermanent("WA_PHONE_NUMBER_ID not set")  # deployment error: dead-letter, do not spin on retries
    return f"{GRAPH_HOST}/{_version()}/{pnid}/messages"


def _headers() -> dict:
    token = os.environ.get("WA_TOKEN")
    if not token:
        raise SendPermanent("WA_TOKEN not set")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _raw_post(url: str, data: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
    """The one real network call (monkeypatched in tests). 2xx → (status, body); >=400 raises urllib HTTPError."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return resp.status, resp.read()


def _raw_get(url: str, headers: dict, timeout: float, limit: int) -> bytes:
    """The one real GET (monkeypatched in tests). Reads at most limit+1 bytes so an oversized body is detectable."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (Graph host or the URL Meta gave us)
        return resp.read(limit + 1)


def _meta_code(body: bytes) -> str:
    """Meta's numeric error code only (its error.message can contain the recipient number)."""
    try:
        err = json.loads(body).get("error", {})
        return f"code={err.get('code')} subcode={err.get('error_subcode')}"
    except (ValueError, AttributeError):
        return "unparsable error body"


def _post(payload: dict) -> dict:
    """Send one Cloud API payload; return the parsed 2xx response. Raises a typed SendError otherwise."""
    url, headers = _endpoint(), _headers()
    data = json.dumps(payload).encode()
    try:
        _status, body = _raw_post(url, data, headers, TIMEOUT_S)
    except urllib.error.HTTPError as e:  # server answered with an error → outcome known, nothing was created
        code, ebody = e.code, e.read()
        if code == 429 or code >= 500:
            raise SendRetryable(f"HTTP {code}") from e
        raise SendPermanent(f"HTTP {code} ({_meta_code(ebody)})") from e
    except urllib.error.URLError as e:  # HTTPError is a subclass, so it was handled above
        reason = e.reason
        if isinstance(reason, ConnectionRefusedError | socket.gaierror):
            raise SendRetryable(f"connection failed: {type(reason).__name__}") from e
        raise SendAmbiguous(f"network error: {type(reason).__name__}") from e  # timeout/reset after send → do not resend
    except TimeoutError as e:  # bare socket timeout not wrapped in URLError
        raise SendAmbiguous("timeout") from e
    try:
        return json.loads(body)
    except ValueError as e:
        raise SendAmbiguous("2xx with unparsable body") from e  # accepted but we cannot read the WAMID → do not resend


def _wamid(resp: dict) -> str:
    return resp["messages"][0]["id"]


def _check(cond: bool, msg: str):
    if not cond:
        raise ValueError(msg)


# --- sends (each returns the new message's WAMID) ---------------------------------------------------------------------

def send_text(to: str, body: str) -> str:
    _check(0 < len(body) <= 4096, "text body must be 1..4096 chars")
    return _wamid(_post({
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to, "type": "text", "text": {"body": body},
    }))


def send_buttons(to: str, body: str, buttons: list[dict], footer: str | None = None) -> str:
    """buttons: [{"id": ..., "title": ...}] (<=3, title <=20). file 06 §1."""
    _check(1 <= len(buttons) <= MAX_BUTTONS, f"1..{MAX_BUTTONS} buttons")
    _check(len(body) <= MAX_BODY, f"body <= {MAX_BODY}")
    for b in buttons:
        _check(0 < len(b["title"]) <= MAX_BUTTON_TITLE, f"button title 1..{MAX_BUTTON_TITLE}")
    interactive = {
        "type": "button", "body": {"text": body},
        "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]},
    }
    if footer:
        interactive["footer"] = {"text": footer}
    return _wamid(_post({"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": interactive}))


def send_list(to: str, body: str, button: str, rows: list[dict], header: str | None = None, section_title: str | None = None) -> str:
    """rows: [{"id","title","description"?}] (<=10 total, title <=24, desc <=72). Single section. file 06 §1."""
    _check(1 <= len(rows) <= MAX_LIST_ROWS, f"1..{MAX_LIST_ROWS} rows")
    for r in rows:
        _check(0 < len(r["title"]) <= MAX_ROW_TITLE, f"row title 1..{MAX_ROW_TITLE}")
        _check(len(r.get("description", "")) <= MAX_ROW_DESC, f"row description <= {MAX_ROW_DESC}")
    section: dict = {"rows": [{k: r[k] for k in ("id", "title", "description") if k in r} for r in rows]}
    if section_title:
        section["title"] = section_title
    interactive: dict = {"type": "list", "body": {"text": body}, "action": {"button": button, "sections": [section]}}
    if header:
        interactive["header"] = {"type": "text", "text": header}
    return _wamid(_post({"messaging_product": "whatsapp", "to": to, "type": "interactive", "interactive": interactive}))


def send_location(to: str, latitude: float, longitude: float, name: str | None = None, address: str | None = None) -> str:
    loc: dict = {"latitude": latitude, "longitude": longitude}
    if name:
        loc["name"] = name
    if address:
        loc["address"] = address
    return _wamid(_post({"messaging_product": "whatsapp", "to": to, "type": "location", "location": loc}))


def send_location_request(to: str, body: str) -> str:
    """Native 'share your location' prompt (file 06 §2.5: missing place → location request)."""
    return _wamid(_post({
        "messaging_product": "whatsapp", "to": to, "type": "interactive",
        "interactive": {"type": "location_request_message", "body": {"text": body}, "action": {"name": "send_location"}},
    }))


def send_template(to: str, name: str, lang: str, components: list[dict] | None = None) -> str:
    """Only outside the 24 h window; the two approved templates are price_alert / daily_rates (D-005, file 06 §2.6)."""
    template: dict = {"name": name, "language": {"code": lang}}
    if components:
        template["components"] = components
    return _wamid(_post({"messaging_product": "whatsapp", "to": to, "type": "template", "template": template}))


def mark_read(message_id: str, typing: bool = True) -> dict:
    """Mark an inbound message read, optionally showing the typing indicator while we work (file 06 §1). No WAMID."""
    payload: dict = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    if typing:
        payload["typing_indicator"] = {"type": "text"}
    return _post(payload)


# --- media download (task 5.2, RFC §4 step 2) -------------------------------------------------------------------------

MAX_MEDIA_BYTES = 16 * 1024 * 1024  # Cloud API audio limit is 16 MB; anything bigger is not a WhatsApp voice note


class _Expired(Exception):
    """The short-lived download URL no longer serves the file (any 4xx or a sha256 mismatch)."""


def _get(url: str, limit: int) -> bytes:
    """GET with the bearer token. GETs are idempotent, so a timeout/reset is retryable (unlike a send)."""
    try:
        body = _raw_get(url, _headers(), TIMEOUT_S, limit)
    except urllib.error.HTTPError as e:
        if e.code == 429 or e.code >= 500:
            raise SendRetryable(f"HTTP {e.code}") from e
        raise SendPermanent(f"HTTP {e.code} ({_meta_code(e.read())})") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SendRetryable(f"network error: {type(getattr(e, 'reason', e)).__name__}") from e
    if len(body) > limit:
        raise SendPermanent(f"body larger than {limit} bytes")
    return body


def media_info(media_id: str) -> dict:
    """Ask Graph for a fresh download URL: {url, mime_type, sha256, file_size, id}. The URL is valid ~5 min (file 06)."""
    try:
        return json.loads(_get(f"{GRAPH_HOST}/{_version()}/{media_id}", 64 * 1024))
    except ValueError as e:
        raise SendRetryable("media info: unparsable body") from e


def _fetch(info: dict) -> bytes:
    try:
        data = _get(info["url"], MAX_MEDIA_BYTES)
    except SendPermanent as e:  # 401/403/404 etc. from the CDN: treat as an expired URL, the caller re-queries once
        raise _Expired(str(e)) from e
    if info.get("sha256") and hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise _Expired("sha256 mismatch")  # e.g. an HTML error page served with 200
    return data


def download_media(media_id: str, info: dict | None = None) -> str:
    """Download a media file into a new temp file and return its path; the CALLER deletes it (audio is never kept, OPS §3).

    `info` is an earlier media_info() result; if its URL has expired, the media ID is re-queried once for a fresh URL
    (RFC §4: "5-min URL, re-query on expiry"). Passing a stale `info` is how the forced-expiry test exercises that path.
    """
    info = info or media_info(media_id)
    try:
        data = _fetch(info)
    except _Expired:
        info = media_info(media_id)
        try:
            data = _fetch(info)
        except _Expired as e:
            raise SendPermanent(f"media download failed after re-query: {e}") from e
    mime = (info.get("mime_type") or "").split(";")[0].strip()
    fd, path = tempfile.mkstemp(prefix="wa-media-", suffix=mimetypes.guess_extension(mime) or "")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path
