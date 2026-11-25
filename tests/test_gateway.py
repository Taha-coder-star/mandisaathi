"""Task 5.1: the Cloud API adapter builds the right payloads and maps Meta's responses to retry outcomes (RFC C12, §13).

No network: payload-shape tests stub `_post`; error-mapping tests stub the one real call `_raw_post`.
"""
import hashlib
import io
import json
import os
import socket
import urllib.error

import pytest

from app import gateway

TO = "923001234567"
OK = {"messages": [{"id": "wamid.OUT"}]}


@pytest.fixture
def capture(monkeypatch):
    """Replace _post with a recorder; return the list it appends each sent payload to. Returns a WAMID so sends succeed."""
    sent = []

    def rec(payload):
        sent.append(payload)
        return OK

    monkeypatch.setattr(gateway, "_post", rec)
    return sent


# --- payload shapes ---------------------------------------------------------------------------------------------------

def test_send_text(capture):
    assert gateway.send_text(TO, "salaam") == "wamid.OUT"
    assert capture[0] == {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": TO, "type": "text", "text": {"body": "salaam"},
    }


def test_send_buttons(capture):
    gateway.send_buttons(TO, "Agle din ka andaza?", [{"id": "yes", "title": "Haan"}, {"id": "no", "title": "Nahi"}], footer="Demo")
    act = capture[0]["interactive"]
    assert capture[0]["type"] == "interactive" and act["type"] == "button"
    assert act["body"] == {"text": "Agle din ka andaza?"} and act["footer"] == {"text": "Demo"}
    assert act["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "yes", "title": "Haan"}},
        {"type": "reply", "reply": {"id": "no", "title": "Nahi"}},
    ]


def test_send_list(capture):
    rows = [{"id": "onion", "title": "Pyaz", "description": "Onion"}]
    gateway.send_list(TO, "Fasal chunein", "Fasal", rows, header="Crops", section_title="Covered")
    act = capture[0]["interactive"]
    assert act["type"] == "list" and act["action"]["button"] == "Fasal"
    assert act["header"] == {"type": "text", "text": "Crops"}
    assert act["action"]["sections"] == [{"rows": rows, "title": "Covered"}]


def test_send_location(capture):
    gateway.send_location(TO, 31.52, 74.35, name="Badami Bagh")
    assert capture[0]["location"] == {"latitude": 31.52, "longitude": 74.35, "name": "Badami Bagh"}


def test_send_location_request(capture):
    gateway.send_location_request(TO, "Apni location bhejein")
    act = capture[0]["interactive"]
    assert act["type"] == "location_request_message" and act["action"] == {"name": "send_location"}


def test_send_template(capture):
    comps = [{"type": "body", "parameters": []}]
    gateway.send_template(TO, "price_alert", "ur", components=comps)
    assert capture[0]["template"] == {"name": "price_alert", "language": {"code": "ur"}, "components": comps}


def test_mark_read_with_and_without_typing(capture):
    gateway.mark_read("wamid.IN", typing=True)
    gateway.mark_read("wamid.IN", typing=False)
    assert capture[0] == {
        "messaging_product": "whatsapp", "status": "read",
        "message_id": "wamid.IN", "typing_indicator": {"type": "text"},
    }
    assert "typing_indicator" not in capture[1]


# --- caller-error validation (file 06 §1 limits) ----------------------------------------------------------------------

def test_too_many_buttons_is_valueerror(capture):
    with pytest.raises(ValueError):
        gateway.send_buttons(TO, "x", [{"id": str(i), "title": "t"} for i in range(4)])


def test_button_title_too_long_is_valueerror(capture):
    with pytest.raises(ValueError):
        gateway.send_buttons(TO, "x", [{"id": "a", "title": "x" * 21}])


def test_too_many_list_rows_is_valueerror(capture):
    with pytest.raises(ValueError):
        gateway.send_list(TO, "x", "b", [{"id": str(i), "title": "t"} for i in range(11)])


# --- response / error mapping (stub the real network call) ------------------------------------------------------------

@pytest.fixture
def net(monkeypatch):
    monkeypatch.setenv("WA_PHONE_NUMBER_ID", "PNID")
    monkeypatch.setenv("WA_TOKEN", "tok")

    def install(result):
        def raw(url, data, headers, timeout):
            assert url.endswith("/PNID/messages") and headers["Authorization"] == "Bearer tok"
            if isinstance(result, BaseException):
                raise result
            return result  # (status, body)
        monkeypatch.setattr(gateway, "_raw_post", raw)
    return install


def http_error(code: int, body: bytes = b'{"error":{"code":131}}'):
    return urllib.error.HTTPError("u", code, "e", {}, io.BytesIO(body))


def test_2xx_returns_wamid(net):
    net((200, b'{"messages":[{"id":"wamid.Z"}]}'))
    assert gateway.send_text(TO, "hi") == "wamid.Z"


@pytest.mark.parametrize("code", [429, 500, 503])
def test_429_and_5xx_are_retryable(net, code):
    net(http_error(code))
    with pytest.raises(gateway.SendRetryable):
        gateway.send_text(TO, "hi")


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_other_4xx_is_permanent(net, code):
    net(http_error(code))
    with pytest.raises(gateway.SendPermanent):
        gateway.send_text(TO, "hi")


def test_connection_refused_is_retryable(net):
    net(urllib.error.URLError(ConnectionRefusedError()))
    with pytest.raises(gateway.SendRetryable):
        gateway.send_text(TO, "hi")


def test_dns_failure_is_retryable(net):
    net(urllib.error.URLError(socket.gaierror()))
    with pytest.raises(gateway.SendRetryable):
        gateway.send_text(TO, "hi")


def test_timeout_is_ambiguous(net):
    net(urllib.error.URLError(TimeoutError()))
    with pytest.raises(gateway.SendAmbiguous):
        gateway.send_text(TO, "hi")


def test_bare_timeout_is_ambiguous(net):
    net(TimeoutError())
    with pytest.raises(gateway.SendAmbiguous):
        gateway.send_text(TO, "hi")


def test_2xx_unparsable_body_is_ambiguous(net):
    net((200, b"not json"))
    with pytest.raises(gateway.SendAmbiguous):
        gateway.send_text(TO, "hi")


def test_missing_config_is_permanent(monkeypatch):
    monkeypatch.delenv("WA_PHONE_NUMBER_ID", raising=False)
    monkeypatch.setenv("WA_TOKEN", "tok")
    with pytest.raises(gateway.SendPermanent):
        gateway.send_text(TO, "hi")


# --- media download (task 5.2): fresh URL per media ID, re-query once when the 5-min URL has expired -------------------

AUDIO = b"OggS fake voice note"
AUDIO_SHA = hashlib.sha256(AUDIO).hexdigest()


@pytest.fixture
def media(monkeypatch):
    """Fake Graph + CDN. Graph hands out url-1, url-2, ...; `dead` URLs answer like an expired link. Returns the state."""
    monkeypatch.setenv("WA_TOKEN", "tok")
    st = {"queries": 0, "dead": set(), "cdn": None, "graph": None}

    def raw(url, headers, timeout, limit):
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/MEDIA1"):  # Graph media lookup
            if st["graph"]:
                raise st["graph"]
            st["queries"] += 1
            return json.dumps({"id": "MEDIA1", "url": f"https://cdn.test/url-{st['queries']}",
                               "mime_type": "audio/ogg; codecs=opus", "sha256": AUDIO_SHA, "file_size": len(AUDIO)}).encode()
        if url in st["dead"]:
            raise http_error(404, b"")
        return st["cdn"](url) if st["cdn"] else AUDIO[: limit + 1]

    monkeypatch.setattr(gateway, "_raw_get", raw)
    return st


def _raise(err):
    raise err


def _read_and_delete(path):
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data


def test_download_media_writes_temp_file(media):
    path = gateway.download_media("MEDIA1")
    assert os.path.basename(path).startswith("wa-media-")
    assert _read_and_delete(path) == AUDIO and media["queries"] == 1


def test_forced_expiry_requeries_and_succeeds(media):
    """DONE test for 5.2: a stale (expired) URL makes the download re-query the media ID once, then succeed."""
    stale = gateway.media_info("MEDIA1")      # url-1, as if fetched >5 min ago
    media["dead"].add(stale["url"])            # ... and now expired
    path = gateway.download_media("MEDIA1", stale)
    assert media["queries"] == 2               # re-queried exactly once, got url-2
    assert _read_and_delete(path) == AUDIO


@pytest.mark.parametrize("code", [401, 403])
def test_auth_style_expiry_also_requeries(media, code):
    media["cdn"] = lambda url: _raise(http_error(code, b"")) if url.endswith("url-1") else AUDIO
    assert _read_and_delete(gateway.download_media("MEDIA1")) == AUDIO and media["queries"] == 2


def test_sha_mismatch_requeries_then_fails_permanent(media):
    media["cdn"] = lambda url: b"<html>error page</html>"
    with pytest.raises(gateway.SendPermanent, match="after re-query"):
        gateway.download_media("MEDIA1")
    assert media["queries"] == 2               # one re-query, no loop


def test_cdn_5xx_is_retryable_without_requery(media):
    media["cdn"] = lambda url: _raise(http_error(503, b""))
    with pytest.raises(gateway.SendRetryable):
        gateway.download_media("MEDIA1")
    assert media["queries"] == 1


def test_bad_media_id_is_permanent(media):
    media["graph"] = http_error(400)
    with pytest.raises(gateway.SendPermanent):
        gateway.download_media("MEDIA1")


def test_oversized_media_is_refused(media, monkeypatch):
    monkeypatch.setattr(gateway, "MAX_MEDIA_BYTES", 4)
    with pytest.raises(gateway.SendPermanent):
        gateway.download_media("MEDIA1")
