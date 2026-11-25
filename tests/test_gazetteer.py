"""Task 4.3: crop + place gazetteer v0. DONE check: the gazetteer loads; the alias test list (>= 60 cases) is committed
and agrees with the gazetteer. Task 6.1 is scored on tests/fixtures/alias_cases.csv (D-019)."""
import copy
import csv
from pathlib import Path

import psycopg
import pytest
import yaml

from app.migrate import migrate
from mandi.gazetteer import COLS, load_gazetteer, norm, read, rows

ROOT = Path(__file__).resolve().parent.parent
CASES = list(csv.DictReader((ROOT / "tests/fixtures/alias_cases.csv").read_text(encoding="utf-8").splitlines()))
SPEC = yaml.safe_load((ROOT / "data/synthetic/spec.yaml").read_text(encoding="utf-8"))
CATEGORIES = {"OFFICIAL", "COMMON", "MISSPELLING", "URDU_SCRIPT", "VOICE_STT", "PUNJABI", "AMBIGUOUS", "OUT_OF_COVERAGE", "UNKNOWN"}


@pytest.mark.parametrize("raw, expected", [
    ("  PYAZ! ", "pyaz"),
    ("D.G. Khan", "d g khan"),
    ("پياز", "پیاز"),  # Arabic yeh -> Urdu yeh (پياز -> پیاز)
    ("سبزى", "سبزی"),  # alef maksura -> Urdu yeh
    ("کنك", "کنک"),  # Arabic kaf -> keheh (کنك -> کنک)
    ("لاهور", "لاہور"),  # Arabic heh -> heh goal (لاهور -> لاہور)
    ("آلُوّ", "آلو"),  # harakat dropped
    ("ٹماـٹر", "ٹماٹر"),  # tatweel dropped
    ("فیصل‌آباد", "فیصل آباد"),  # ZWNJ -> space
    ("प्याज", "प्याज"),  # प्याज: Devanagari virama/matra survive
])
def test_norm_folds_case_punctuation_and_arabic_letter_forms(raw, expected):
    assert norm(raw) == expected


def test_alias_list_has_at_least_60_cases():
    assert len(CASES) >= 60
    assert {c["category"] for c in CASES} == CATEGORIES
    named = {i for c in CASES for i in c["ids"].split("|") if i}
    assert {"ONION", "TOMATO", "POTATO", "WHEAT", "COTTON", "RICE"} <= named
    assert {m["id"] for m in SPEC["mandis"]} <= named
    hyderabad = {"input": "Hyderabad", "kind": "place", "expect": "OUT_OF_COVERAGE", "ids": "HYDERABAD", "category": "OUT_OF_COVERAGE"}
    assert hyderabad in CASES


def test_alias_list_matches_gazetteer():
    r = rows(read())
    lookup: dict[tuple[str, str], set[str]] = {}
    for a, cid, _ in r["crop_alias"]:
        lookup.setdefault(("crop", a), set()).add(cid)
    for a, pid in r["place_alias"]:
        lookup.setdefault(("place", a), set()).add(pid)
    covered = {c[0]: c[6] for c in r["crop"]} | {p[0]: p[5] == "Punjab" for p in r["place"]}
    for c in CASES:
        found, ids = lookup.get((c["kind"], norm(c["input"]))), set(filter(None, c["ids"].split("|")))
        if c["expect"] in ("RESOLVED", "OUT_OF_COVERAGE"):
            assert found == ids and len(ids) == 1, c
            assert covered[next(iter(ids))] == (c["expect"] == "RESOLVED"), c
        elif c["expect"] == "AMBIGUOUS":
            assert found == ids and len(ids) >= 2, c
        else:
            assert c["expect"] == "UNKNOWN" and found is None and not ids, c


def test_spec_mandis_are_in_gazetteer_with_same_names_and_coordinates():
    fields = ("id", "name_en", "name_ur", "district", "lat", "lon")
    assert [tuple(m[f] for f in fields) for m in read()["mandis"]] == [tuple(m[f] for f in fields) for m in SPEC["mandis"]]


TINY = {
    "crops": {
        "ONION": {"name_en": "Onion", "name_ur": "پیاز", "perishability": "MED", "default_unit": "mann", "covered": True},
        "TOMATO": {"name_en": "Tomato", "name_ur": "ٹماٹر", "perishability": "HIGH", "default_unit": "mann", "covered": True},
    },
    "mandis": [{"id": "OKARA", "name_en": "Okara", "name_ur": "اوکاڑہ", "district": "Okara", "lat": 30.8, "lon": 73.5}],
    "other_places": [],
    "ambiguous": {"crop": {"sabzi": ["ONION", "TOMATO"]}},
}


@pytest.mark.parametrize("change", [
    lambda g: g["crops"]["TOMATO"].update(aliases={"COMMON": ["ONION!"]}),  # unplanned collision with ONION's name
    lambda g: g["crops"]["ONION"].update(aliases={"COMMON": ["?!"]}),  # empty after normalisation
    lambda g: g["ambiguous"]["crop"].update(sabzi=["ONION", "GARLIC"]),  # ambiguous target that does not exist
    lambda g: g["other_places"].append({"id": "X", "name_en": "X", "name_ur": "ایکس", "kind": "CITY", "district": "X",
                                        "province": "Punjab", "lat": 31.0, "lon": 73.0, "candidate_mandi_ids": ["NOPE"]}),
])
def test_unplanned_alias_collision_or_unknown_candidate_is_an_error(change):
    rows(TINY)  # the base gazetteer is valid
    g = copy.deepcopy(TINY)
    change(g)
    with pytest.raises(ValueError):
        rows(g)


# --- with a database -------------------------------------------------------

def table(c, name):
    return sorted(c.execute(f"SELECT {', '.join(COLS[name])} FROM {name}").fetchall())


def test_gazetteer_loads_and_reload_changes_nothing(db):
    migrate(db)
    expected = {t: sorted(v) for t, v in rows(read()).items()}
    with psycopg.connect(db, autocommit=True) as c:
        counts = load_gazetteer(c)
        assert counts == {t: len(v) for t, v in expected.items()}
        first = {t: table(c, t) for t in COLS}
        assert load_gazetteer(c) == counts
        assert {t: table(c, t) for t in COLS} == first == expected
        mandis = {r[0] for r in c.execute("SELECT mandi_id FROM mandi")}
        assert {i for (ids,) in c.execute("SELECT candidate_mandi_ids FROM place") for i in ids} <= mandis
