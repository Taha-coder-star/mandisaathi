"""Task 7.1: rule-based parser. parse() returns the benchmark gold shape (SPEC §2.1/§2.5).

One case per intent and per producible outcome (GRACEFUL_FAIL is a voice-control outcome, not reachable from text);
spans for alias / Urdu script / number words / Punjabi crop names; the two-crop list; STOP; a fuzzy span; plus a
regression floor on the overall D9 scores set just below the first measured numbers (D-031)."""
import json
from datetime import date
from pathlib import Path

import pytest

from mandi.parse import parse
from scripts.score_parser import metrics, score

ROOT = Path(__file__).resolve().parent.parent
NOW = date(2026, 12, 11)  # S-DEMO reference so MONTH horizons match gold (D-025)


def _gold():
    items = {}
    for name, use_roman in (("text.jsonl", False), ("voice.jsonl", True)):
        for line in (ROOT / "data/benchmark" / name).read_text(encoding="utf-8").splitlines():
            it = json.loads(line)
            items[it["id"]] = (it["gold_transcript"]["roman"] if use_roman else it["input"], it["gold"])
    return items


GOLD = _gold()

# id -> what it exercises. Together these cover every intent, every text-reachable outcome, and each span kind.
CASES = {
    "T-EN-01": "PRICE_NOW / ANSWER / English alias",
    "T-RU-04": "FORECAST / 'kal' + future verb / spelling variant",
    "T-RU-07": "WHERE_TO_SELL / number word 'dedh sau' / origin role",
    "T-RU-01": "OUTLOOK / Punjabi crop 'kanak' / month horizon / WHEAT-only-under-OUTLOOK",
    "T-RU-11": "ALERT / direction + threshold / alert_action",
    "T-EN-05": "STOP",
    "T-EN-06": "HELP / no tool",
    "T-OOS-03": "OTHER -> OUT_OF_SCOPE",
    "T-AMB-01": "CLARIFY crop (no crop, no place)",
    "T-AMB-03": "CLARIFY place ('<word> mandi' -> UNKNOWN)",
    "T-AMB-02": "CLARIFY quantity_unit (bori, value_kg null)",
    "T-AMB-04": "CLARIFY horizon (bare 'kal ka rate' -> AMBIGUOUS)",
    "T-AMB-06": "two crops -> crop list + two tool calls",
    "T-OOS-01": "OUT_OF_COVERAGE crop (kapas)",
    "T-OOS-02": "OUT_OF_COVERAGE place (Hyderabad)",
    "T-UR-01": "Urdu-script spans + Urdu 'ریٹ' intent trigger",
    "T-UR-03": "Urdu-script sell verb 'بیچوں' -> WHERE_TO_SELL",
    "T-RU-06": "number word 'sau'",
    "V16": "Punjabi crop 'ganda' (voice transcript)",
}


@pytest.mark.parametrize("item_id", CASES, ids=lambda i: f"{i}:{CASES[i]}")
def test_parses_benchmark_item_to_gold(item_id):
    text, gold = GOLD[item_id]
    assert parse(text, NOW) == gold


def test_two_crops_make_a_list():
    out = parse("Bahawalpur mein pyaz aur aloo ka rate", NOW)
    assert [c["id"] for c in out["slots"]["crop"]] == ["ONION", "POTATO"]
    assert [t["args"]["crop"] for t in out["tool"]] == ["ONION", "POTATO"]


def test_fuzzy_span_resolves_a_misspelled_crop():
    out = parse("tamatr ka rate Lahore mein", NOW)  # 'tamatr' is not an exact alias -> fuzzy to TOMATO
    assert out["slots"]["crop"]["id"] == "TOMATO" and out["intent"] == "PRICE_NOW"


def test_alert_message_keeps_quantity_null():
    # the threshold sits after the crop, so it is never read as a quantity (quantity stays null, as gold wants)
    out = parse("Gujranwala mein aloo 2000 se upar jaye to mujhe bata dena", NOW)
    assert out["slots"]["quantity"] is None
    assert out["tool"]["args"]["threshold"] == 2000 and out["tool"]["args"]["direction"] == "ABOVE"


def test_stop_is_detected_whole_message_only():
    assert parse("STOP", NOW)["intent"] == "STOP"
    assert parse("band karo", NOW)["tool"] == {"name": "stop", "args": {}}
    assert parse("Lahore mein pyaz ka rate", NOW)["intent"] != "STOP"  # 'stop' not present


# --- regression floor: overall D9 scores must not silently drop below the first measured numbers (D-031) ------------
# First measured (2026-11-27): intent 100%, critical-slot text 100% / voice 96.7%, tool 100%, clarify-AMB 100%,
# unneeded-clarify 0%, OOS redirect 100%. Floors are set a few points below, so a later change that regresses fails.
FLOOR = {
    "intent accuracy (all)": (98.0, "min"),
    "critical-slot exact match (text)": (97.0, "min"),
    "critical-slot exact match (voice)": (93.0, "min"),
    "clarification asked on AMB": (95.0, "min"),
    "unnecessary clarifications on clear items": (5.0, "max"),
    "out-of-scope requests redirected": (100.0, "min"),
    "correct tool": (97.0, "min"),
}


def test_regression_floor_on_the_benchmark():
    rows, parsed_by_id = score()
    mx = {k: v for k, (v, _thr) in metrics(rows, parsed_by_id).items()}
    for name, (bound, kind) in FLOOR.items():
        value = mx[name]
        if kind == "min":
            assert value >= bound, f"{name} = {value:.1f}% dropped below floor {bound}%"
        else:
            assert value <= bound, f"{name} = {value:.1f}% rose above ceiling {bound}%"
