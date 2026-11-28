"""Task 5.3: QC rules (file 03 §6, D-024). DONE check: QC flags 100% of injected defects in generated data."""
import copy
from datetime import date, timedelta

from mandi.ingest import qc
from mandi.ingest.loader import TO_PER_100KG
from scripts.e1_realism import canon
from scripts.make_synthetic import generate, load_spec


def series(vals, mandi="LAHORE", start=date(2024, 1, 1)):
    return [{"crop_id": "ONION", "mandi_id": mandi, "market_date": start + timedelta(i),
             "min_pkr100kg": v * 0.95, "max_pkr100kg": v * 1.05, "avg_pkr100kg": v} for i, v in enumerate(vals)]


def test_min_gt_max():
    r = series([5000.0])
    r[0]["min_pkr100kg"], r[0]["max_pkr100kg"] = 5300, 4700
    assert qc.flag(r) == [{qc.MIN_GT_MAX}]


def test_robust_sd_flags_10x_both_ways_and_not_normal_noise():
    vals = [5000 * (1 + 0.01 * ((i % 5) - 2)) for i in range(40)]
    vals[30], vals[35] = 50000.0, 500.0
    f = qc.flag(series(vals))
    assert [i for i, x in enumerate(f) if x] == [30, 35]
    assert f[30] == {qc.ROBUST_SD}


def test_neighbour_rule_catches_a_typo_on_the_first_day():
    rows = [r for m, v in [("LAHORE", 5000), ("OKARA", 4800), ("KASUR", 4600), ("MULTAN", 49000)] for r in series([v], m)]
    assert qc.flag(rows) == [set(), set(), set(), {qc.NEIGHBOURS}]


def test_no_look_ahead_and_mid_from_min_max():
    rows = series([5000.0] * 10 + [9000.0] * 10)
    for r in rows:
        r["avg_pkr100kg"] = None  # mid = (min+max)/2
    f = qc.flag(rows)
    assert f[10] == {qc.ROBUST_SD} and not any(f[:10])  # the jump day is flagged from the past only


def test_done_qc_flags_every_injected_defect():
    spec = copy.deepcopy(load_spec())
    spec["period"]["end"] = date(2016, 12, 31)
    gen = generate(spec, "SYN")
    f = qc.flag(canon(gen))
    bad = [i for i, g in enumerate(gen) if g["truth_typo10x"] == "1" or g["truth_swap"] == "1"]
    assert len(bad) > 30 and all(f[i] for i in bad)
    per40 = [i for i, g in enumerate(gen) if g["truth_per40"] == "1"]
    assert per40 and all(TO_PER_100KG[gen[i]["unit_raw"]] == 2.5 for i in per40)
    clean = [i for i in range(len(gen)) if i not in set(bad)]
    assert sum(1 for i in clean if f[i]) / len(clean) < 0.02  # false positives stay rare


def test_e1_verdict_fails_above_envelope_but_not_below():
    """Task 9.2 (D-043): above env high or a moved trough fails G1 realism; under the retail low edge does not."""
    from collections import Counter

    from scripts.e1_realism import verdict
    elig = Counter({"ONION": 12, "TOMATO": 12})
    season = [["ONION", 5, 5], ["TOMATO", 5, 5]]
    below = {"TOMATO": [(2025, 4349, 0, 0, 4400, 8000)]}  # (year, median, p10, p90, env low, env high)
    assert all(r[2] for r in verdict(True, below, season, elig))
    above = {"TOMATO": [(2025, 8100, 0, 0, 4400, 8000)]}
    assert [r[2] for r in verdict(True, above, season, elig)] == [True, False, True, True]
    assert not verdict(True, below, [["ONION", 5, 4]], elig)[2][2]
    assert not verdict(True, below, season, Counter({"ONION": 4}))[3][2]
    assert not verdict(False, below, season, elig)[0][2]
