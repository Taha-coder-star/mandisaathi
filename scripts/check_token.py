"""Task 1.2 check: the WhatsApp token in .env works and belongs to this app. Never prints the token.

Usage: python scripts/check_token.py
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GRAPH = "https://graph.facebook.com/v25.0"
NEEDED_SCOPES = {"whatsapp_business_messaging", "whatsapp_business_management"}


def load_env(path=Path(__file__).resolve().parent.parent / ".env"):
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def get(path, **params):
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err = json.load(e).get("error", {})
        sys.exit(f"FAIL {path.split('/')[0]}: {err.get('code')} {err.get('message')}")


def main():
    env = load_env()
    missing = [k for k in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "WA_WABA_ID", "META_APP_ID", "META_APP_SECRET") if not env.get(k)]
    if missing:
        sys.exit(f"FAIL .env missing: {', '.join(missing)}")
    token = env["WA_TOKEN"]

    d = get("debug_token", input_token=token, access_token=f"{env['META_APP_ID']}|{env['META_APP_SECRET']}")["data"]
    if not d.get("is_valid"):
        sys.exit("FAIL token is not valid")
    if d.get("app_id") != env["META_APP_ID"]:
        sys.exit(f"FAIL token belongs to app {d.get('app_id')}, .env says {env['META_APP_ID']} (old account?)")
    if NEEDED_SCOPES - set(d.get("scopes", [])):
        sys.exit(f"FAIL token lacks scopes: {', '.join(NEEDED_SCOPES - set(d.get('scopes', [])))}")
    exp = d.get("expires_at", 0)
    expiry = "never (permanent)" if exp == 0 else datetime.fromtimestamp(exp, timezone.utc).isoformat()

    nums = get(f"{env['WA_WABA_ID']}/phone_numbers", access_token=token).get("data", [])
    num = next((n for n in nums if n["id"] == env["WA_PHONE_NUMBER_ID"]), None)
    if not num:
        sys.exit("FAIL WA_PHONE_NUMBER_ID is not in WA_WABA_ID's phone numbers")

    print(f"OK  token type={d.get('type')} expires={expiry}")
    print(f"OK  number {num.get('display_phone_number')} ({num.get('verified_name')}) in WABA, quality={num.get('quality_rating')}")


if __name__ == "__main__":
    main()
