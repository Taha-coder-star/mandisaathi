"""Task 5.5, M1 (b) live check: replay one signed webhook message and prove no duplicate event or outbound message.

Runs inside the web container on the VM (the image has no scripts/, so pipe it in):
    sudo docker compose exec -T web python - 923XXXXXXXXX < scripts/m1_replay.py

The number is a team phone. It posts one text "from" that phone, waits for the worker's echo, posts the same body again
(as Meta's redelivery would), and checks: 1 inbound_event, 1 job, 1 outbound_message. The phone must get exactly one
"Echo: M1 replay test ..." reply. Exit code 0 = PASS. Needs META_APP_SECRET and DATABASE_URL (the container's .env).
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request

import psycopg

URL = "http://localhost:8000/webhook"


def post(body: bytes) -> int:
    sig = "sha256=" + hmac.new(os.environ["META_APP_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json", "X-Hub-Signature-256": sig})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def counts(conn, wamid):
    """(events, jobs, outbound rows, outbound statuses) for this inbound WAMID."""
    ev = [r[0] for r in conn.execute("SELECT id FROM inbound_event WHERE dedup_key = %s", (wamid,))]
    jobs = [r[0] for r in conn.execute("SELECT id FROM job WHERE payload->>'event_id' = ANY(%s)", ([str(e) for e in ev],))]
    out = [r[0] for r in conn.execute("SELECT status FROM outbound_message WHERE job_id = ANY(%s)", (jobs,))]
    return len(ev), len(jobs), len(out), out


def main(phone: str) -> int:
    ts = int(time.time())
    wamid = f"wamid.M1SMOKE.{ts}"
    message = {"from": phone, "id": wamid, "timestamp": str(ts), "type": "text", "text": {"body": f"M1 replay test {ts}"}}
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "", "phone_number_id": ""},
             "contacts": [{"profile": {"name": "M1"}, "wa_id": phone}], "messages": [message]}
    body = json.dumps({"object": "whatsapp_business_account",
                       "entry": [{"id": "M1", "changes": [{"field": "messages", "value": value}]}]}).encode()

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        print("post 1:", post(body))
        for _ in range(30):  # the worker polls every second; the echo should be out within a few
            out = counts(conn, wamid)[3]
            if out and out[0] != "pending":
                break
            time.sleep(1)
        print("after post 1:", counts(conn, wamid))
        print("post 2 (replay):", post(body))
        time.sleep(5)  # give the worker time to (wrongly) act on a duplicate
        result = counts(conn, wamid)
    print("after replay (events, jobs, outbound, statuses):", result)
    ok = result[:3] == (1, 1, 1) and result[3][0] in ("sent", "delivered", "read")
    print("M1 (b):", "PASS" if ok else "FAIL", "- check the phone got exactly one echo")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
