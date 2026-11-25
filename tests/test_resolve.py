"""Task 6.1: crop/place resolver. DONE check (file 11): the alias list resolves 100% (exact hits correct, designed-ambiguous
AMBIGUOUS, "Hyderabad" OUT_OF_COVERAGE): test_alias_list_resolves."""
import csv
import json
from pathlib import Path

import pytest

from mandi.gazetteer import read
from mandi.resolve import Resolution, resolve_crop, resolve_pin, resolve_place

ROOT = Path(__file__).resolve().parent.parent
CASES = list(csv.DictReader((ROOT / "tests/fixtures/alias_cases.csv").read_text(encoding="utf-8").splitlines()))
RESOLVE = {"crop": resolve_crop, "place": resolve_place}


@pytest.mark.parametrize("c", CASES, ids=lambda c: f"{c['kind']}:{c['input']}")
def test_alias_list_resolves(c):
    r = RESOLVE[c["kind"]](c["input"])
    assert (r.status, set(r.ids)) == (c["expect"], set(filter(None, c["ids"].split("|"))))
    assert r.exact == (c["expect"] != "UNKNOWN")  # every fixture hit is an alias hit, so no echo needed


def test_resolved_place_carries_its_mandis_and_hyderabad_is_out_of_coverage():
    assert resolve_place("Okara") == Resolution("RESOLVED", ("OKARA",), True, ("OKARA",))
    assert resolve_place("Hyderabad") == Resolution("OUT_OF_COVERAGE", ("HYDERABAD",), True)


@pytest.mark.parametrize("fn, raw, expected", [
    (resolve_crop, "tamatr", Resolution("RESOLVED", ("TOMATO",), False)),
    (resolve_crop, "pyz", Resolution("RESOLVED", ("ONION",), False)),
    (resolve_place, "okra", Resolution("RESOLVED", ("OKARA",), False, ("OKARA",))),
    (resolve_place, "faisalabd", Resolution("RESOLVED", ("FAISALABAD",), False, ("FAISALABAD",))),
    (resolve_place, "peshawr", Resolution("OUT_OF_COVERAGE", ("PESHAWAR",), False)),  # fuzzy hit outside Punjab
    (resolve_place, "d g khn", Resolution("AMBIGUOUS", ("DGKHAN", "DIKHAN"), False)),  # two within the 0.15 margin
    (resolve_crop, "ganna", Resolution("UNKNOWN", (), False)),  # sugarcane: 0.80 to "ganda", below 0.85
    (resolve_place, "Jaranwala", Resolution("UNKNOWN", (), False)),  # 0.84 to Gujranwala: a different town
    (resolve_place, " ?! ", Resolution("UNKNOWN", (), True)),
])
def test_fuzzy_needs_085_and_015_margin_and_is_never_exact(fn, raw, expected):
    assert fn(raw) == expected


def test_pin_resolves_to_nearest_place_or_out_of_coverage():
    okara = next(m for m in read()["mandis"] if m["id"] == "OKARA")
    assert resolve_pin(okara["lat"], okara["lon"]) == Resolution("RESOLVED", ("OKARA",), True, ("OKARA",))
    assert resolve_pin(30.70, 73.60).ids == ("OKARA",)  # a field ~15 km from Okara
    assert resolve_pin(24.860, 67.010) == Resolution("OUT_OF_COVERAGE", ("RYKHAN",), True)  # Karachi; names nearest mandi
    assert resolve_pin(33.693, 73.064) == Resolution("OUT_OF_COVERAGE", ("SARGODHA",), True)  # Islamabad: > 150 km from all 15


def test_benchmark_gold_spans_resolve_to_gold():
    """Every crop/place raw span in the benchmark texts resolves to its gold label (D-020 rules)."""
    checked = 0
    for line in (ROOT / "data/benchmark/text.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        for kind in ("crop", "place"):
            slot = item["gold"]["slots"].get(kind)
            for s in slot if isinstance(slot, list) else [slot]:
                if not s or not s.get("raw"):
                    continue
                r = RESOLVE[kind](s["raw"])
                if kind == "crop":
                    got = "OUT_OF_COVERAGE" if r.status == "OUT_OF_COVERAGE" and s["id"] != "WHEAT" else r.ids[0]
                    assert got == s["id"], item["id"]
                else:
                    assert (r.status, r.ids[0] if r.ids else None) == (s["status"], s["canonical"]), item["id"]
                checked += 1
    assert checked >= 40
