"""ps_v1 (task 8.3, D-041): values also hard-coded in mandi/ must equal the frozen parameter set, and the
pre-registered criteria must be complete (every S has a rule; S1-S3 and S5 carry their valid-null wording)."""
import yaml

from mandi import price, resolve
from mandi.ingest import qc
from mandi.models import f1eval
from scripts.make_synthetic import load_spec

PS = yaml.safe_load(f1eval.PARAMS.read_text(encoding="utf-8"))


def test_code_constants_match_ps_v1():
    cov, q = PS["coverage"], PS["qc"]
    assert (price.WINDOW_DAYS, price.MIN_PCT, price.RECENT_WITHIN, price.STALE_AFTER) == (
        cov["window_days"], cov["min_pct"], cov["recent_within"], cov["stale_after"])
    assert (qc.WINDOW_DAYS, qc.K_ROBUST_SD, qc.SD_FLOOR, qc.MIN_WINDOW_OBS, qc.NEIGHBOUR_RATIO, qc.MIN_NEIGHBOURS) == (
        q["window_days"], q["k_robust_sd"], q["sd_floor"], q["min_window_obs"], q["neighbour_ratio"],
        q["min_neighbours"])
    assert resolve.PIN_MAX_KM == PS["resolve"]["pin_max_km"]
    assert f1eval.load_config() == PS["f1_eval"]


def test_criteria_complete():
    c = PS["criteria"]
    for s in ("S1", "S2", "S3", "S5"):
        assert c[s]["rule"] and c[s]["valid_null"], s
    assert c["S4"] and c["fyp1_pipeline_check"]["rules"]


def test_f2_costs_cover_every_crop_and_load():
    f2 = PS["f2"]
    assert set(f2["spoilage_per_day"]) == set(load_spec()["crops"])
    caps = [v["max_mann"] for v in f2["transport"]["vehicles"]]
    assert caps == sorted(caps)  # smallest vehicle that carries Q is the first match
    sens = f2["sensitivity"]
    assert f2["commission"] in sens["commission"] and 1.0 in sens["transport_scale"] and 1.0 in sens["spoilage_scale"]
