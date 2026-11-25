"""Task 4.2: mandi name matching (no DB). DONE check: >= 95% of generated name variants map to their mandi, none to a
wrong one; near-miss places are refused. The matcher sees only (mandi_id, name_en); truth_* is read here, never by it."""
import importlib.util
from pathlib import Path

import pytest

from mandi.ingest.loader import make_matcher

ROOT = Path(__file__).resolve().parent.parent
_mod = importlib.util.spec_from_file_location("make_synthetic", ROOT / "scripts" / "make_synthetic.py")
ms = importlib.util.module_from_spec(_mod)
_mod.loader.exec_module(ms)

SPEC = ms.load_spec()
MATCH = make_matcher((m["id"], m["name_en"]) for m in SPEC["mandis"])


def test_generated_variants_map_back_to_their_mandi():
    got = [(r, MATCH(r["mandi_raw"])) for r in ms.generate(SPEC, "SYN")]
    variants = [(r, m) for r, m in got if r["truth_variant"] == "1"]
    assert sum(m == r["truth_mandi_id"] for r, m in variants) / len(variants) >= 0.95
    assert {r["mandi_raw"] for r, m in got if m is not None and m != r["truth_mandi_id"]} == set()  # never a wrong mandi
    assert all(m == r["truth_mandi_id"] for r, m in got if r["truth_variant"] != "1")
    assert {r["mandi_raw"] for r, m in got if m is None} == {"Ukara"}  # pins the reviewed list (D-018)


@pytest.mark.parametrize("raw", [
    "Jaranwala", "Bahawalnagar", "Dera Ismail Khan", "D.I. Khan", "Mandi Bahauddin", "Khanewal", "Sialkot", "Lodhran",
    "Karachi", "Hyderabad", "Jhelum", "Gujrat", "Kasowal", "Layyah", "Narowal", "Hafizabad", "Toba Tek Singh", "Khan",
    "Rawalpindi", "Peshawar", "", "Mandi", "(Badami Bagh)",
])
def test_near_miss_places_are_refused(raw):
    assert MATCH(raw) is None


@pytest.mark.parametrize("raw, mandi_id", [
    ("Lahore (Badami Bagh)", "LAHORE"), ("D.G. Khan", "DGKHAN"), ("LHR", "LAHORE"), ("Lyallpur", "FAISALABAD"),
    ("Pak Pattan", "PAKPATTAN"), ("Montgomery", "SAHIWAL"), ("RYK", "RYKHAN"), ("  SAHIWAL mandi ", "SAHIWAL"),
])
def test_known_spellings_resolve(raw, mandi_id):
    assert MATCH(raw) == mandi_id


def test_two_equally_close_mandis_is_refused():
    m = make_matcher([("A", "Jhang"), ("B", "Jhung")])
    assert m("Jhong") is None and m("Jhung") == "B"


def test_one_key_for_two_mandis_is_an_error():
    with pytest.raises(ValueError):
        make_matcher([("A", "Okara"), ("B", "okara")])
