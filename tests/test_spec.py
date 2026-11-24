"""Structural checks on data/synthetic/spec.yaml (task 2.4). Not a model test: the generator (3.2) has its own."""
import math
from datetime import date
from pathlib import Path

import yaml

SPEC = yaml.safe_load((Path(__file__).parent.parent / "data/synthetic/spec.yaml").read_text(encoding="utf-8"))
MANDIS = {m["id"]: m for m in SPEC["mandis"]}
CROPS3 = ["ONION", "TOMATO", "POTATO"]


def km(a, b):
    p = math.pi / 180
    dlat, dlon = (b["lat"] - a["lat"]) * p, (b["lon"] - a["lon"]) * p
    h = math.sin(dlat / 2) ** 2 + math.cos(a["lat"] * p) * math.cos(b["lat"] * p) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def test_mandis_in_punjab_box_and_unique():
    assert len(MANDIS) == len(SPEC["mandis"]) == 15
    for m in MANDIS.values():
        assert 27.5 <= m["lat"] <= 34 and 69.5 <= m["lon"] <= 75.5, m["id"]
        assert m["name_ur"] and m["variants"] and m["name_en"] not in m["variants"], m["id"]


def test_coverage_constraints():
    c = SPEC["coverage_constraints"]
    thin = {i for i, m in MANDIS.items() if m["thin"]}
    assert len(thin) == 3 and not thin & set(c["must_not_be_thin"])
    assert len(MANDIS) - len(thin) >= c["min_non_thin_mandis_per_crop"]
    near = [i for i in MANDIS if i not in thin and i != "OKARA" and km(MANDIS["OKARA"], MANDIS[i]) <= 150]
    assert len(near) >= c["min_non_thin_within_150km_of_okara"], near


def test_period_and_holdout():
    p = SPEC["period"]
    assert p["start"] < p["end"] and p["holdout"]["start"] < p["holdout"]["end"] == p["end"]
    assert (p["holdout"]["end"] - p["holdout"]["start"]).days == 364
    assert isinstance(SPEC["meta"]["seed"], int) and SPEC["units"]["mann_kg"] * SPEC["units"]["per_40kg_to_100kg"] == 100


def test_crops_reference_real_mandis_and_rates_sane():
    for c in CROPS3:
        assert SPEC["crops"][c]["producing_mandi"] in MANDIS
        assert all(1 <= d["month"] <= 13 and 0 < d["depth"] < 0.5 for d in SPEC["crops"][c]["dips"])
    for k, v in SPEC["defects"].items():
        if k.endswith("_rate"):
            assert 0 < v < 0.2, k
    assert SPEC["defects"]["thin_mandi_coverage"]["high"] < 0.6  # must trip the coverage gate


def test_plausibility_has_source_and_base_level_fits():
    pl = SPEC["plausibility"]
    for c in CROPS3:
        a = pl["anchors"][c]
        assert a["source"] and a["url"].startswith("https://") and a["tag"] == "ASSUMPTION" and a["low"] < a["high"]
        cr = SPEC["crops"][c]
        years = (date(2025, 7, 1) - date(2016, 1, 1)).days / 365.25
        mann = cr["base_pkr100kg"] * 0.4 * (1 + cr["annual_trend"]) ** years
        assert a["low"] <= mann <= a["high"], (c, round(mann))
