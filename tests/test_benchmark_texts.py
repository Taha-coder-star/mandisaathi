"""Task 4.4: benchmark texts (40) with gold JSON. DONE check: data/benchmark/text.jsonl holds the 40 items of
data/benchmark/SPEC.md §3.1, each with gold that follows SPEC §2.1/§2.5 and agrees with the gazetteer (D-019, D-020)."""
import json
import re
from collections import Counter
from pathlib import Path

from mandi.gazetteer import norm, read, rows

ROOT = Path(__file__).resolve().parent.parent
RAW = (ROOT / "data/benchmark/text.jsonl").read_bytes()
ITEMS = [json.loads(line) for line in RAW.decode("utf-8").splitlines()]
GAZ = read()
R = rows(GAZ)
CROPS: dict[str, set[str]] = {}
PLACES: dict[str, set[str]] = {}
for a, cid, _ in R["crop_alias"]:
    CROPS.setdefault(a, set()).add(cid)
for a, pid in R["place_alias"]:
    PLACES.setdefault(a, set()).add(pid)
COVERED = {c[0]: c[6] for c in R["crop"]}
PLACE = {p[0]: p for p in R["place"]}  # place_id, name_en, name_ur, kind, district, province, ...
PUNJABI = {norm(a) for c in GAZ["crops"].values() for a in c.get("aliases", {}).get("PUNJABI", [])}

COUNTS = {"EN": 6, "RU": 12, "MX": 8, "UR": 4, "AMB": 6, "OOS": 4}
LANG = {"EN": "EN", "RU": "RU", "MX": "MIX", "UR": "UR"} | {f"T-AMB-0{i}": "RU" for i in range(1, 7)} | {
    "T-OOS-01": "RU", "T-OOS-02": "RU", "T-OOS-03": "MIX", "T-OOS-04": "EN"}
INTENTS = {"PRICE_NOW", "FORECAST", "WHERE_TO_SELL", "OUTLOOK", "ALERT", "STOP", "HELP", "OTHER"}
OUTCOMES = {"ANSWER", "CLARIFY", "OUT_OF_SCOPE", "OUT_OF_COVERAGE", "GRACEFUL_FAIL"}
CLARIFY = {"crop", "place", "quantity_unit", "horizon", "language"}
TAGS = {"quantity", "number_word", "place_alias", "place_urdu", "crop_punjabi", "horizon", "spelling_variant"}
KG = {"MANN": 40, "KG": 1, "TON": 1000, "BORI": None, "NONE": None}
TOOL = {"PRICE_NOW": "price_now", "FORECAST": "get_forecast", "WHERE_TO_SELL": "best_mandis", "OUTLOOK": "get_outlook",
        "ALERT": "set_alert", "STOP": "stop"}
ARGS = {"price_now": {"crop", "mandi"}, "get_forecast": {"crop", "mandi", "h"}, "best_mandis": {"crop", "origin", "quantity_kg"},
        "get_outlook": {"crop", "month"}, "set_alert": {"crop", "mandi", "direction", "threshold"}, "stop": set()}
NUMERIC_PATHS = {"quantity.value", "quantity.value_kg", "horizon.h", "args.quantity_kg", "args.h", "args.threshold"}
ARABIC = re.compile(r"[؀-ۿ]")


def listed(x):
    return x if isinstance(x, list) else [x]


def crops(it):
    return [c for c in listed(it["gold"]["slots"]["crop"]) if c]


def test_ids_and_counts():
    assert len(ITEMS) == 40 and not RAW.startswith(b"\xef\xbb\xbf") and b"\r" not in RAW
    assert [i["id"] for i in ITEMS] == [f"T-{k}-{n:02d}" for k, total in COUNTS.items() for n in range(1, total + 1)]
    assert len({norm(i["input"]) for i in ITEMS}) == 40
    for it in ITEMS:
        assert it["set"] == "text" and it["category"] == it["id"].split("-")[1], it["id"]
        assert it["lang"] == LANG.get(it["id"], LANG.get(it["category"])), it["id"]


def test_schema():
    for it in ITEMS:
        check_schema(it)


def check_schema(it):
    """Per-item gold rules (SPEC §2.1/§2.5); also run on voice items (test_benchmark_voice.py)."""
    g, s, i = it["gold"], it["gold"]["slots"], it["id"]
    assert set(it) == {"id", "set", "category", "lang", "input", "gold", "tags", "notes"}, i
    alert = {"alert_action"} if g["intent"] == "ALERT" else set()
    assert set(g) == {"intent", "slots", "tool", "outcome", "clarify_slot"} | alert, i
    assert set(s) == {"crop", "place", "quantity", "horizon"}, i
    assert g["intent"] in INTENTS and g["outcome"] in OUTCOMES, i
    assert (g["clarify_slot"] in CLARIFY) if g["outcome"] == "CLARIFY" else g["clarify_slot"] is None, i
    assert g.get("alert_action", "SUBSCRIBE") in {"SUBSCRIBE", "SET_THRESHOLD", "LIST", "UNSUBSCRIBE"}, i
    assert isinstance(s["crop"], list) == (i == "T-AMB-06") and len(listed(s["crop"])) == (2 if i == "T-AMB-06" else 1), i
    for c in crops(it):
        assert set(c) == {"raw", "id"} and c["raw"] in it["input"], i
        assert c["id"] in {"ONION", "TOMATO", "POTATO", "WHEAT", "OUT_OF_COVERAGE"}, i
    if p := s["place"]:
        assert set(p) == {"raw", "canonical", "status", "role"} and p["raw"] in it["input"], i
        assert p["status"] in {"RESOLVED", "AMBIGUOUS", "UNKNOWN", "OUT_OF_COVERAGE"}, i
        assert p["role"] == ("ORIGIN" if g["intent"] == "WHERE_TO_SELL" else "MANDI"), i
        assert (p["canonical"] is None) == (p["status"] == "UNKNOWN"), i
    if q := s["quantity"]:
        assert set(q) == {"raw", "value", "unit", "value_kg"} and q["raw"] in it["input"] and q["unit"] in KG, i
        assert q["value_kg"] == (None if KG[q["unit"]] is None else q["value"] * KG[q["unit"]]), i
    if h := s["horizon"]:
        kind = h["kind"]
        assert kind in {"TODAY", "DAYS", "MONTH", "AMBIGUOUS"}, i
        assert set(h) == {"kind"} | {"DAYS": {"h"}, "MONTH": {"month"}}.get(kind, set()), i
        assert kind != "DAYS" or (type(h["h"]) is int and 1 <= h["h"] <= 7), i
        assert kind != "MONTH" or re.fullmatch(r"\d{4}-\d{2}", h["month"]), i
    if g["outcome"] != "ANSWER" or g["intent"] in {"HELP", "OTHER"}:
        assert g["tool"] is None, i
        return
    calls = listed(g["tool"])
    assert len(calls) == len(listed(s["crop"])), i
    for call, crop in zip(calls, listed(s["crop"]), strict=True):
        name, args = call["name"], call["args"]
        assert set(call) == {"name", "args"} and name == TOOL[g["intent"]], i
        assert set(args) == ARGS[name] | ({"mandi"} if name == "get_outlook" and s["place"] else set()), i
        slot = {"crop": crop and crop["id"], "mandi": s["place"] and s["place"]["canonical"],
                "origin": s["place"] and s["place"]["canonical"], "quantity_kg": s["quantity"] and s["quantity"]["value_kg"],
                "h": s["horizon"] and s["horizon"].get("h"), "month": s["horizon"] and s["horizon"].get("month")}
        for k, v in args.items():
            if k in slot:
                assert v == slot[k] and v is not None, (i, k)
        if name == "set_alert":
            assert args["direction"] in {"ABOVE", "BELOW"} and type(args["threshold"]) is int and args["threshold"] > 0, i


def test_slots_agree_with_gazetteer():
    for it in ITEMS:
        check_gazetteer(it)


def check_gazetteer(it):
    g, i = it["gold"], it["id"]
    for c in crops(it):
        found = CROPS.get(norm(c["raw"]))
        if c["id"] == "OUT_OF_COVERAGE":
            assert found and len(found) == 1 and not COVERED[next(iter(found))] and found != {"WHEAT"}, i
        else:
            assert found == {c["id"]}, i
        assert (c["id"] == "WHEAT") <= (g["intent"] == "OUTLOOK"), i
    if p := g["slots"]["place"]:
        found = PLACES.get(norm(p["raw"]))
        if p["status"] == "UNKNOWN":
            assert found is None, i
        else:
            assert found == {p["canonical"]}, i
            assert (PLACE[p["canonical"]][5] == "Punjab") == (p["status"] == "RESOLVED"), i
        if g["intent"] == "WHERE_TO_SELL":
            assert p["canonical"] in {"OKARA", "SAHIWAL", "KASUR", "LAHORE"}, i


def check_tags(it):
    s, tags, i = it["gold"]["slots"], set(it["tags"]), it["id"]
    p, q = s["place"], s["quantity"]
    assert tags <= TAGS and len(tags) == len(it["tags"]), i
    assert ("quantity" in tags) == bool(q) and ("horizon" in tags) == bool(s["horizon"]), i
    assert ("number_word" in tags) == bool(q and not re.search(r"\d", q["raw"])), i
    assert ("place_urdu" in tags) == bool(p and ARABIC.search(p["raw"])), i
    alias = bool(p and p["status"] == "RESOLVED" and norm(p["raw"]) not in {norm(x) for x in PLACE[p["canonical"]][1:3]})
    assert ("place_alias" in tags) == alias, i
    assert ("crop_punjabi" in tags) == any(norm(c["raw"]) in PUNJABI for c in crops(it)), i


def test_coverage_counts():
    for it in ITEMS:
        check_tags(it)
    tagged = Counter(t for it in ITEMS for t in it["tags"])
    assert tagged["quantity"] >= 12 and tagged["horizon"] >= 8 and tagged["place_alias"] >= 1 and tagged["place_urdu"] >= 2
    places = [it["gold"]["slots"]["place"]["raw"] for it in ITEMS if it["gold"]["slots"]["place"]]
    assert len(places) >= 15 and len({norm(x) for x in places}) >= 15
    crop_raws = {norm(c["raw"]) for it in ITEMS for c in crops(it)}
    assert len(crop_raws) >= 4 and crop_raws & PUNJABI
    intents = Counter(it["gold"]["intent"] for it in ITEMS)
    assert set(intents) == INTENTS and min(intents.values()) >= 2
    text = {k: " ".join(it["input"] for it in ITEMS if it["category"] == k) for k in COUNTS}
    for k, words in {"RU": ["piaz", "timatar", "kro", "aloo", "sau", "dedh sau"], "MX": ["next week"], "UR": ["لاہور", "اوکاڑہ"],
                     "AMB": ["rate batao", "10 bori pyaz", "Block mandi", "kal ka rate", "50 pyaz"],
                     "OOS": ["kapas", "Hyderabad", "fertilizer kab dalun", "write a poem"]}.items():
        for w in words:
            assert w in text[k], (k, w)
    assert re.search(r"best mandi .* se\b", text["MX"])
    amb = [it["gold"] for it in ITEMS if it["category"] == "AMB"]
    assert Counter(g["clarify_slot"] for g in amb if g["outcome"] == "CLARIFY") == Counter(
        ["crop", "quantity_unit", "place", "horizon", "quantity_unit"])
    assert sum(isinstance(g["slots"]["crop"], list) for g in amb) == 1
    assert Counter(it["gold"]["outcome"] for it in ITEMS if it["category"] == "OOS") == {"OUT_OF_COVERAGE": 2, "OUT_OF_SCOPE": 2}
    assert {"PRICE_NOW", "FORECAST", "WHERE_TO_SELL"} <= {it["gold"]["intent"] for it in ITEMS if it["category"] == "EN"}


def numbers(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from numbers(v, k if not path else f"{path.rsplit('.', 1)[-1]}.{k}")
    elif isinstance(x, list):
        for v in x:
            yield from numbers(v, path)
    elif isinstance(x, int | float) and not isinstance(x, bool):
        yield path, x


def test_no_reply_numbers_or_personal_data():
    for it in ITEMS:
        check_numbers(it)


def check_numbers(it):
    found = list(numbers(it["gold"]))
    assert {p for p, _ in found} <= NUMERIC_PATHS, it["id"]
    assert {int(d) for d in re.findall(r"\d+", it["input"])} <= {v for _, v in found}, it["id"]
    assert not re.search(r"\d{7,}|\+\d|@", it["input"]), it["id"]
