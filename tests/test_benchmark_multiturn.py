"""Task 9.4: benchmark multi-turn + command items (30), SPEC §2.4/§3.4.
Every item is replayed through the real `app.state.apply` (D-032): context state + gold patches must give gold state_after,
and each tool call must follow from that state (or from the ref position / added places)."""
import copy
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.state import apply, snapshot
from tests.test_benchmark_texts import ARABIC, COVERED, CROPS, KG, PLACE, PLACES, norm  # noqa: F401

RAW = (Path(__file__).resolve().parent.parent / "data/benchmark/multiturn.jsonl").read_bytes()
ITEMS = [json.loads(line) for line in RAW.decode("utf-8").splitlines()]
NOW = datetime(2026, 12, 11, tzinfo=UTC)

# SPEC §3.4: (id prefix, first n, last n, category)
_MATRIX = [("M-FU", 1, 4, "CROP_SWITCH"), ("M-FU", 5, 6, "PLACE_SWITCH"), ("M-FU", 7, 8, "PLACE_ADD"),
           ("M-FU", 9, 12, "REFERENCE"), ("M-FU", 13, 16, "HORIZON"), ("M-FU", 17, 20, "CORRECTION"),
           ("M-CMD", 1, 3, "ALERT_SUBSCRIBE"), ("M-CMD", 4, 6, "ALERT_SET_THRESHOLD"), ("M-CMD", 7, 8, "ALERT_LIST"),
           ("M-CMD", 9, 10, "STOP")]
SPEC_IDS = [(f"{p}-{n:02d}", c) for p, lo, hi, c in _MATRIX for n in range(lo, hi + 1)]
ARGS = {"price_now": {"crop", "mandi"}, "get_forecast": {"crop", "mandi", "h"},
        "best_mandis": {"crop", "origin", "quantity_kg", "mandi"},  # mandi only on a detail request ("tafseel", D-045)
        "get_outlook": {"crop", "month", "mandi"}, "set_alert": {"crop", "mandi", "direction", "threshold"},
        "list_alerts": set(), "stop": set()}
TURN_TOOLS = {"PRICE_NOW": "price_now", "FORECAST": "get_forecast", "WHERE_TO_SELL": "best_mandis", "OUTLOOK": "get_outlook",
              "ALERT": {"SUBSCRIBE": "set_alert", "SET_THRESHOLD": "set_alert", "LIST": "list_alerts"}, "STOP": "stop"}
REF_TOOLS = {"PRICE_NOW": "price_now", "FORECAST": "get_forecast", "WHERE_TO_SELL": "best_mandis"}
ACTIONS = {"ALERT_SUBSCRIBE": "SUBSCRIBE", "ALERT_SET_THRESHOLD": "SET_THRESHOLD", "ALERT_LIST": "LIST"}
NUMERIC = {"quantity_kg", "h", "threshold", "position", "value", "value_kg"}


def to_state(snap):
    """Rebuild a state from a SPEC §2.4 snapshot (provenance fields are irrelevant to the merge)."""
    s = {}
    if snap["intent"]:
        s["intent"] = {"value": snap["intent"], "raw": None}
    if snap["crop"]:
        s["crop"] = {"value": snap["crop"], "raw": None}
    if p := snap["place"]:
        s["place"] = {"value": {"canonical": p["canonical"], "status": "RESOLVED", "role": p["role"],
                                "mandi_ids": [p["canonical"]]}, "raw": None}
    if snap["quantity_kg"] is not None:
        s["quantity"] = {"value": {"value_kg": snap["quantity_kg"]}, "raw": None}
    if snap["horizon"]:
        s["horizon"] = {"value": snap["horizon"], "raw": None}
    return s


def calls(it):
    t = it["gold"]["tool"]
    return [] if t is None else t if isinstance(t, list) else [t]


def after_state(it):
    """State after the patches, from the last context turn (empty context = fresh farmer)."""
    before = it["context"][-1]["state_after"] if it["context"] else snapshot({})
    if it["gold"]["intent"] == "STOP":
        return snapshot({})  # STOP deletes the state (6.2 _forget); it is not a patch
    return snapshot(apply(to_state(before), copy.deepcopy(it["gold"]["patch"]), "text", NOW))


def test_ids_counts_and_encoding():
    assert len(ITEMS) == 30 and not RAW.startswith(b"\xef\xbb\xbf") and b"\r" not in RAW
    assert [(i["id"], i["category"]) for i in ITEMS] == SPEC_IDS
    assert len({norm(i["input"]) for i in ITEMS}) == 30
    langs = Counter(i["lang"] for i in ITEMS)
    assert set(langs) <= {"EN", "RU", "MIX", "UR"} and {"EN", "RU", "MIX", "UR"} <= set(langs)
    for it in ITEMS:
        assert it["set"] == "multiturn" and set(it) == {"id", "set", "category", "lang", "context", "input", "gold", "notes"}
        assert (it["lang"] == "UR") == bool(ARABIC.search(it["input"])), it["id"]


def test_state_after_follows_from_context_and_patches():
    for it in ITEMS:
        assert after_state(it) == it["gold"]["state_after"], it["id"]
        for t in it["context"]:
            assert set(t) - {"bot_shown"} == {"user", "state_after"}, it["id"]
            assert set(t["state_after"]) == {"intent", "crop", "place", "quantity_kg", "horizon"}, it["id"]


def test_gold_shape_and_outcomes():
    for it in ITEMS:
        g, i = it["gold"], it["id"]
        alert = {"alert_action"} if g["intent"] == "ALERT" else set()
        assert set(g) == {"intent", "patch", "state_after", "tool", "outcome", "clarify_slot"} | alert, i
        assert g["outcome"] in {"ANSWER", "CLARIFY"}, i
        assert (g["clarify_slot"] in {"crop", "place", "quantity_unit", "horizon"}) == (g["outcome"] == "CLARIFY"), i
        assert (g["tool"] is None) == (g["outcome"] == "CLARIFY"), i
        if g["intent"] == "ALERT":
            assert g["alert_action"] == ACTIONS[it["category"]], i
        else:
            assert it["category"] not in ACTIONS, i
        for p in g["patch"]:
            assert p["op"] in {"set", "add", "correct", "ref", "clear"} and p["slot"] in {
                "intent", "crop", "place", "quantity", "horizon"}, i
            assert p["raw"] in it["input"], (i, p["raw"])
            assert (p["op"] == "ref") == ("position" in p), i


def test_patches_agree_with_gazetteer():
    for it in ITEMS:
        i = it["id"]
        for p in it["gold"]["patch"]:
            if p["slot"] == "crop":
                assert CROPS.get(norm(p["raw"])) == {p["value"]} and COVERED[p["value"]], i
            if p["slot"] == "place" and p["op"] != "ref":
                v = p["value"]
                assert PLACES.get(norm(p["raw"])) == {v["canonical"]} and PLACE[v["canonical"]][5] == "Punjab", i
                assert v["mandi_ids"] == [v["canonical"]] and v["status"] == "RESOLVED", i
            if p["slot"] == "quantity":
                v = p["value"]
                assert v["value_kg"] == (None if KG[v["unit"]] is None else v["value"] * KG[v["unit"]]), i
        shown = it["context"][-1].get("bot_shown") if it["context"] else None
        for p in it["gold"]["patch"]:
            if p["op"] == "ref":  # position n of the last list the bot sent
                assert shown and 1 <= p["position"] <= len(shown) and p["value"] == shown[p["position"] - 1], i
        if it["category"] != "REFERENCE":
            assert not shown, i


def test_tool_calls_follow_from_state():
    for it in ITEMS:
        g, i, s = it["gold"], it["id"], it["gold"]["state_after"]
        if g["outcome"] == "CLARIFY":
            continue
        cs = calls(it)
        ref = next((p for p in g["patch"] if p["op"] == "ref"), None)
        add = [p["value"]["canonical"] for p in g["patch"] if p["op"] == "add"]
        name = TURN_TOOLS[g["intent"]]
        if isinstance(name, dict):
            name = name[g["alert_action"]]
        if ref:  # the referenced mandi: F2 detail card ("tafseel"), its price ("rate") or its forecast ("andaza")
            name = REF_TOOLS[g["intent"]]
        mandis = [ref["value"]] if ref else ([s["place"]["canonical"]] + add if s["place"] else [None])
        assert len(cs) == len(mandis) and all(c["name"] == name for c in cs), i
        for c, m in zip(cs, mandis, strict=True):
            a = c["args"]
            assert set(c) == {"name", "args"} and set(a) <= ARGS[name] and ARGS[name] - set(a) <= {"mandi"}, i
            if name == "best_mandis":  # a mandi arg narrows F2 to one ranked mandi; only a reference does that
                assert ("mandi" in a) == bool(ref), i
            origin = s["place"]["canonical"] if ref and s["place"] else m  # a reference keeps the state's origin
            slot = {"crop": s["crop"], "mandi": m, "origin": origin, "quantity_kg": s["quantity_kg"],
                    "h": (s["horizon"] or {}).get("h"), "month": (s["horizon"] or {}).get("month")}
            for k, v in a.items():
                if k in slot:
                    assert v == slot[k] and v is not None, (i, k)
            if name == "set_alert":
                assert a["direction"] in {"ABOVE", "BELOW"} and type(a["threshold"]) is int and a["threshold"] > 0, i
                assert re.search(rf"\b{a['threshold']}\b", it["input"]), i
            if g["intent"] == "WHERE_TO_SELL":
                assert origin in {"OKARA", "SAHIWAL", "KASUR", "LAHORE"}, i
        if g["intent"] == "FORECAST":
            assert s["horizon"]["kind"] == "DAYS", i


def test_state_ops_covered():
    ops = Counter((p["slot"], p["op"]) for it in ITEMS for p in it["gold"]["patch"])
    for k in [("crop", "set"), ("place", "set"), ("place", "add"), ("place", "ref"), ("horizon", "set"),
              ("quantity", "correct")]:
        assert ops[k] >= 2, k
    assert ops[("place", "correct")] >= 1
    intents = Counter(it["gold"]["intent"] for it in ITEMS)
    assert {"PRICE_NOW", "FORECAST", "WHERE_TO_SELL", "OUTLOOK", "ALERT", "STOP"} <= set(intents)
    assert Counter(it["gold"].get("alert_action") for it in ITEMS if it["gold"]["intent"] == "ALERT") == {
        "SUBSCRIBE": 3, "SET_THRESHOLD": 3, "LIST": 2}
    assert sum(it["gold"]["outcome"] == "CLARIFY" for it in ITEMS) == 2


def test_only_expected_numbers_and_no_personal_data():
    def nums(x, k=""):
        if isinstance(x, dict):
            for kk, v in x.items():
                yield from nums(v, kk)
        elif isinstance(x, list):
            for v in x:
                yield from nums(v, k)
        elif isinstance(x, int | float) and not isinstance(x, bool):
            yield k
    for it in ITEMS:
        assert set(nums(it["gold"])) | set(nums(it["context"])) <= NUMERIC, it["id"]
        text = " ".join([it["input"]] + [t["user"] for t in it["context"]])
        assert not re.search(r"\d{7,}|\+\d|@", text), it["id"]
