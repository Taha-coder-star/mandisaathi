"""Task 3.2: synthetic generator (no DB). DONE check: same seed -> identical file hash."""
import copy
import importlib.util
import math
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_mod = importlib.util.spec_from_file_location("make_synthetic", ROOT / "scripts" / "make_synthetic.py")
ms = importlib.util.module_from_spec(_mod)
_mod.loader.exec_module(ms)

SPEC = ms.load_spec()
SEED = SPEC["meta"]["seed"]
TRUTH = ["truth_mandi_id", "truth_typo10x", "truth_swap", "truth_per40", "truth_variant", "truth_late"]


def short(end=date(2016, 3, 31)):
    s = copy.deepcopy(SPEC)
    s["period"]["end"] = end
    return s


@pytest.fixture(scope="module")
def syn():
    return ms.generate(SPEC, "SYN", SEED)


@pytest.fixture(scope="module")
def null():
    return ms.generate(SPEC, "SYN-NULL", SEED)


def test_same_seed_same_file_hash(syn, tmp_path):
    a = ms.write_csv(syn, tmp_path / "a.csv")
    assert ms.write_csv(ms.generate(SPEC, "SYN", SEED), tmp_path / "b.csv") == a
    data = (tmp_path / "a.csv").read_bytes()
    assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")
    assert ms.wheat_monthly(SPEC) == ms.wheat_monthly(SPEC)


def test_different_seed_different_hash(tmp_path):
    s = short()
    assert ms.write_csv(ms.generate(s, "SYN", 1), tmp_path / "a.csv") != ms.write_csv(ms.generate(s, "SYN", 2), tmp_path / "b.csv")


def test_rows_sorted_and_one_per_series_day(syn):
    keys = [(r["market_date"], r["crop_id"], r["truth_mandi_id"]) for r in syn]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert {r["crop_id"] for r in syn} == {"ONION", "TOMATO", "POTATO"}


def test_no_sundays_or_holidays(syn):
    dates = {date.fromisoformat(r["market_date"]) for r in syn}
    assert not any(d.weekday() == 6 for d in dates)
    assert not any(d.strftime("%m-%d") in SPEC["period"]["holidays"]["fixed_mmdd"] for d in dates)
    assert date(2016, 7, 6) not in dates  # Eid ul Fitr anchor (a Wednesday)
    assert date(2026, 3, 18) not in dates  # the same block drifted -11 days x 10 years (a Wednesday)
    assert min(dates) >= SPEC["period"]["start"] and max(dates) <= SPEC["period"]["end"]


def test_thin_mandis_trip_the_coverage_gate_others_do_not(syn):
    n = int(ms.calendar(SPEC)[1].sum())
    thin = {m["id"] for m in SPEC["mandis"] if m["thin"]}
    count = Counter((r["crop_id"], r["truth_mandi_id"]) for r in syn)
    assert len(count) == 3 * len(SPEC["mandis"])
    for (crop, mid), k in count.items():
        assert (k / n < 0.6) if mid in thin else (k / n >= 0.95), (crop, mid, k / n)


@pytest.mark.parametrize("col, rate", [
    ("truth_typo10x", SPEC["defects"]["typo_10x_rate"]),
    ("truth_swap", SPEC["defects"]["min_gt_max_rate"]),
    ("truth_per40", SPEC["defects"]["per_40kg_unit_rate"]),
    ("truth_variant", SPEC["defects"]["name_variant_rate"]),
    ("truth_late", SPEC["timing"]["late_publish_rate"]),
])
def test_defect_rates_within_binomial_tolerance(syn, col, rate):
    n, k = len(syn), sum(r[col] == "1" for r in syn)
    assert abs(k - n * rate) <= 5 * math.sqrt(n * rate * (1 - rate)), (col, k / n)


def test_truth_columns_match_the_raw_values(syn):
    mandis = {m["id"]: m for m in SPEC["mandis"]}
    for r in syn:
        m = mandis[r["truth_mandi_id"]]
        per40 = r["truth_per40"] == "1"
        assert r["unit_raw"] == ("PKR/40kg" if per40 else "PKR/100kg")
        assert (r["mandi_raw"] in m["variants"]) if r["truth_variant"] == "1" else r["mandi_raw"] == m["name_en"]
        lo, hi, avg = (Decimal(r[k]) for k in ("min_raw", "max_raw", "avg_raw"))
        assert (lo > hi) == (r["truth_swap"] == "1")
        assert (not min(lo, hi) <= avg <= max(lo, hi)) == (r["truth_typo10x"] == "1")
        if per40:  # x2.5 must land on whole paisa: the conversion is exact
            for v in (lo, hi, avg):
                assert v * Decimal("2.5") == (v * Decimal("2.5")).quantize(Decimal("0.01"))


def test_reported_at_is_1800_pkt_or_next_day_when_late(syn):
    for r in syn:
        d = date.fromisoformat(r["market_date"]) + timedelta(int(r["truth_late"]))
        assert r["reported_at"] == f"{d} 18:00+05:00"


def test_null_variant_shares_rows_defects_and_timing(syn, null):
    same = ["market_date", "crop_id", "mandi_raw", "unit_raw", "reported_at", *TRUTH]
    assert [[r[k] for k in same] for r in syn] == [[r[k] for k in same] for r in null]
    assert [r["avg_raw"] for r in syn] != [r["avg_raw"] for r in null]


def test_wheat_is_one_punjab_value_per_month():
    rows = ms.wheat_monthly(SPEC)
    assert [r["month"] for r in rows][:2] == ["2016-01-01", "2016-02-01"] and rows[-1]["month"] == "2026-12-01"
    assert len(rows) == 132 and {r["region"] for r in rows} == {"PUNJAB"}
    assert all(float(r["avg_pkr100kg"]) > 0 for r in rows)


def test_unknown_variant_refused():
    with pytest.raises(ValueError):
        ms.generate(short(), "XYZ")
