"""Task 5.1: the Cloud API adapter builds the right payloads and maps Meta's responses to retry outcomes (RFC C12, §13).

No network: payload-shape tests stub `_post`; error-mapping tests stub the one real call `_raw_post`.
"""
import io
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
