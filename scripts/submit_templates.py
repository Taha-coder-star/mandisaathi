"""Task 1.3: submit the price_alert and daily_rates templates (en + ur) and report their status/category.

Safe to re-run: a (name, language) that already exists is not resubmitted, only reported.
Usage: PYTHONIOENCODING=utf-8 python scripts/submit_templates.py
"""
import json
import re
import urllib.error
import urllib.request

from check_token import GRAPH, get, load_env

FOOTER = {"en": "Reply STOP to stop alerts", "ur": "Alert band karne ke liye STOP likhein"}
ALERT_EX = ["Tomato", "Multan", "2,550", "2,500", "23 Nov 2026", "Demo data (synthetic)"]
RATES_EX = ["23 Nov 2026", "Tomato, Multan: Rs 2,400", "Onion, Lahore: Rs 3,100", "Potato, Okara: Rs 1,800",
            "Demo data (synthetic)"]

# shortcut: digest always shows exactly 3 rate lines, revisit in FYP-II S4 when digests are built
TEMPLATES = {
    ("price_alert", "en"): ("Price alert: {{1}} at {{2}} mandi is now Rs {{3}} and has crossed your limit of "
                            "Rs {{4}}. Date: {{5}}. Source: {{6}}. Prices are per 100 kg.", ALERT_EX),
    ("price_alert", "ur"): ("Qeemat alert: {{2}} mandi mein {{1}} ki qeemat ab Rs {{3}} hai, jo aap ki had "
                            "Rs {{4}} se guzar gayi hai. Tareekh: {{5}}. Zariya: {{6}}. Qeemat fi 100 kg hai.",
                            ALERT_EX),
    ("daily_rates", "en"): ("Today's mandi rates ({{1}}):\n1. {{2}}\n2. {{3}}\n3. {{4}}\n"
                            "Source: {{5}}. Rates are per 100 kg.", RATES_EX),
    ("daily_rates", "ur"): ("Aaj ke mandi rates ({{1}}):\n1. {{2}}\n2. {{3}}\n3. {{4}}\n"
                            "Zariya: {{5}}. Rates fi 100 kg hain.", RATES_EX),
}


def check(body, examples, footer):
    """Meta's common rejection reasons, caught before sending."""
    nums = sorted({int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)})
    assert nums == list(range(1, len(examples) + 1)), f"vars {nums} vs {len(examples)} examples"
    assert not re.match(r"\s*\{\{", body) and not re.search(r"\}\}\W*$", body), "body starts/ends with a variable"
    assert all("\n" not in e and "\t" not in e for e in examples), "newline/tab in an example"
    assert len(footer) <= 60, "footer > 60 chars"


def post(path, token, payload):
    req = urllib.request.Request(f"{GRAPH}/{path}", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err = json.load(e).get("error", {})
        return {"error": f"{err.get('code')} {err.get('error_user_msg') or err.get('message')}"}


def existing(waba, token, name):
    rows = get(f"{waba}/message_templates", name=name, fields="name,language,status,category",
               access_token=token).get("data", [])
    return {r["language"]: r for r in rows if r["name"] == name}


def main():
    env = load_env()
    token, waba = env["WA_TOKEN"], env["WA_WABA_ID"]
    for (_name, lang), (body, ex) in TEMPLATES.items():
        check(body, ex, FOOTER[lang])

    for (name, lang), (body, ex) in TEMPLATES.items():
        if lang in existing(waba, token, name):
            continue
        r = post(f"{waba}/message_templates", token, {
            "name": name, "language": lang, "category": "UTILITY",
            "components": [{"type": "BODY", "text": body, "example": {"body_text": [ex]}},
                           {"type": "FOOTER", "text": FOOTER[lang]}]})
        print(f"submit {name}/{lang}: {r.get('error') or r.get('status')}")

    print(f"\n{'name':<12} {'lang':<5} {'status':<10} category (requested UTILITY)")
    for name in sorted({n for n, _ in TEMPLATES}):
        for lang, r in sorted(existing(waba, token, name).items()):
            print(f"{name:<12} {lang:<5} {r.get('status', '?'):<10} {r.get('category', '?')}")


if __name__ == "__main__":
    main()
