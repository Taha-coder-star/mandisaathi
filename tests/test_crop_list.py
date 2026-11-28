"""Task 10.2, gate G1: the FYP-I crop list is frozen (D-048). Changing it after G1 needs a new decision, a regenerated
synthetic world and resealed lockboxes (D-039/D-040), so this test fails on any drift.

Frozen list: ONION, TOMATO, POTATO daily (price now, F1, F2); WHEAT monthly (F3 outlook only)."""
from pathlib import Path

import yaml

from mandi.gazetteer import read

SPEC = yaml.safe_load((Path(__file__).resolve().parent.parent / "data/synthetic/spec.yaml").read_text(encoding="utf-8"))
DAILY = {"ONION", "TOMATO", "POTATO"}
MONTHLY = {"WHEAT"}


def test_synthetic_world_has_exactly_the_frozen_crops():
    crops = SPEC["crops"]
    assert set(crops) == DAILY | MONTHLY
    assert {c for c, v in crops.items() if v.get("frequency") == "monthly"} == MONTHLY  # wheat: F3 panel only
    assert SPEC["period"]["wheat"]["frequency"] == "monthly"


def test_bot_answers_daily_questions_only_for_the_frozen_daily_crops():
    covered = {c for c, v in read()["crops"].items() if v["covered"]}
    assert covered == DAILY  # wheat, cotton, rice -> "not covered" for price now / F1 / F2 (wheat: F3 only)
