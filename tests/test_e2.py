"""E2 baselines (task 7.3; file 04 §1.1-1.4; DECISIONS.md D-033): B-SN / B-SR rules by hand, the opt-in make_xy columns,
known-from for B-SN, holdout guard, embargo = h, byte-identical output. DB-free; small panels only (the full run is
scripts/score_e2.py)."""
import copy
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from mandi.features import fs_s
from mandi.gazetteer import read
from mandi.models import baselines, devdata, f1eval, harness
from scripts import score_e2
from scripts.make_synthetic import generate, load_spec

SPEC = load_spec()
EVENTS = fs_s.spec_events(SPEC)
COLS = fs_s.xy_columns(same_weekday=True)
C = {c: i for i, c in enumerate(COLS)}
MANDIS = [m["id"] for m in read()["mandis"]][:3]
D0 = date(2020, 1, 1)


def row(mandi, d, price, published=None):
    """One hand-made price_obs row; published = the PKT calendar day of reported_at (18:00), default the market day."""
    at = datetime.combine(published or d, datetime.min.time(), fs_s.PKT) + timedelta(hours=18)
    return {"crop_id": "ONION", "mandi_id": mandi, "market_date": d, "reported_at": at, "arrivals_qty": 10.0,
            "min_pkr100kg": price, "max_pkr100kg": price, "avg_pkr100kg": price}


def hand_panel(drop=(), late=()):
    """3 mandis x 30 days; mandi 0 prices 100 + day index, mandis 1/2 at 0.8x and 1.25x of it."""
    out = []
    for i in range(30):
        d = D0 + timedelta(i)
        for k, f in enumerate((1.0, 0.8, 1.25)):
            if k == 0 and i in drop:
                continue
            out.append(row(MANDIS[k], d, f * (100 + i), d + timedelta(1) if k == 0 and i in late else None))
    return out


def at(X, dates, t, h, mandi=MANDIS[0]):
    code = list(read()["mandis"]).index(mandi) if isinstance(read()["mandis"], dict) else \
        [m["id"] for m in read()["mandis"]].index(mandi)
    m = (dates == np.datetime64(t)) & (X[:, C["h"]] == h) & (X[:, C["mandi"]] == code)
    assert m.sum() == 1
    return X[m][0]


# ---- B-SN: the target's weekday one week earlier, as known at t ----

@pytest.mark.parametrize("h", range(1, 8))
def test_same_weekday_is_day_t_plus_h_minus_8(h):
    X, _, dates = fs_s.make_xy(hand_panel(), horizons=(h,), events=EVENTS, same_weekday=True)
    t = D0 + timedelta(20)
    x = at(X, dates, t, h)
    assert x[C["same_weekday"]] == pytest.approx(100 + 20 + h - 8, rel=1e-12)  # market day index 20 + h - 8
    assert x[C["same_weekday_lag"]] == 8 - h


def test_same_weekday_missing_day_falls_back_to_newest_earlier_quote():
    t = D0 + timedelta(20)
    X, _, dates = fs_s.make_xy(hand_panel(drop=(13,)), horizons=(1,), events=EVENTS, same_weekday=True)  # t+1-8 = day 13
    x = at(X, dates, t, 1)
    assert x[C["same_weekday"]] == pytest.approx(112, rel=1e-12) and x[C["same_weekday_lag"]] == 8


def test_same_weekday_late_row_is_not_used_before_it_is_known():
    # h = 7 reads day t-1; published one day late it is known only from t+1, so t falls back to day t-2 (= LAST)
    t = D0 + timedelta(20)
    X, _, dates = fs_s.make_xy(hand_panel(late=(19,)), horizons=(7,), events=EVENTS, same_weekday=True)
    x = at(X, dates, t, 7)
    assert x[C["same_weekday"]] == pytest.approx(118, rel=1e-12) and x[C["same_weekday_lag"]] == 2
    assert x[C["same_weekday"]] == x[harness.LAST]


def test_same_weekday_needs_h_at_most_7():
    with pytest.raises(ValueError):
        fs_s.make_xy(hand_panel(), horizons=(8,), events=EVENTS, same_weekday=True)


def test_default_make_xy_is_unchanged_by_the_opt_in():
    rows = hand_panel(drop=(5,), late=(9,))
    X0, y0, d0 = fs_s.make_xy(rows, horizons=(1, 4, 7), events=EVENTS)
    X1, y1, d1 = fs_s.make_xy(rows, horizons=(1, 4, 7), events=EVENTS, same_weekday=True)
    assert X0.shape[1] == len(fs_s.XY_COLUMNS) and fs_s.xy_columns() == fs_s.XY_COLUMNS
    assert COLS == [*fs_s.FEATURES, *fs_s.SAME_WEEKDAY, "h"]
    keep = [C[c] for c in fs_s.XY_COLUMNS]
    assert np.array_equal(X0, X1[:, keep], equal_nan=True) and np.array_equal(y0, y1) and np.array_equal(d0, d1)


def sw_at(rows, t):
    """SAME_WEEKDAY columns of every series x h on issue day t, from rows up to t + 7 (enough for every target)."""
    X, _, dates = fs_s.make_xy([r for r in rows if r["market_date"] <= t + timedelta(7)], events=EVENTS, same_weekday=True)
    m = dates == np.datetime64(t)
    order = np.lexsort((X[m][:, C["h"]], X[m][:, C["mandi"]]))
    return X[m][order][:, [C[c] for c in fs_s.SAME_WEEKDAY]]


def test_same_weekday_ignores_rows_not_known_at_t(onion):
    """L1-style (T1): rows with reported_at >= t 00:00 PKT x1000 leave B-SN's input at t unchanged; a builder that treats
    rows as known one day early (leaky control) is caught on days whose t-1 row was published late."""
    late = sorted({r["market_date"] + timedelta(1) for r in onion if r["late"] and r["market_date"].year == 2018})[:4]
    caught = False
    for t in late:
        cut = datetime.combine(t, datetime.min.time(), fs_s.PKT)
        poison = [r | {k: r[k] * 1000 for k in ("min_pkr100kg", "max_pkr100kg", "avg_pkr100kg")} if r["reported_at"] >= cut else r
                  for r in onion]
        assert np.array_equal(sw_at(onion, t), sw_at(poison, t), equal_nan=True), t
        early = [r | {"reported_at": r["reported_at"] - timedelta(1)} for r in onion]
        early_p = [r | {"reported_at": r["reported_at"] - timedelta(1)} for r in poison]
        caught |= not np.array_equal(sw_at(early, t), sw_at(early_p, t), equal_nan=True)
    assert late and caught


# ---- B-SN / B-SR / ranges by hand ----

def test_seasonal_naive_point_and_last_fallback():
    X = np.full((2, len(COLS)), np.nan)
    X[:, harness.LAST] = [100, 200]
    X[:, C["same_weekday"]] = [90, np.nan]
    assert baselines.SeasonalNaive().point(X).tolist() == [90, 200]


def test_spread_reversion_goes_halfway_to_the_regional_median():
    # mandis at 80 / 100 / 125: median log = log 100; the 125 mandi moves halfway in logs, to 125 / sqrt(1.25)
    t = D0 + timedelta(20)
    X, _, dates = fs_s.make_xy(hand_panel(), horizons=(3,), events=EVENTS, same_weekday=True)
    x = at(X, dates, t, 3, MANDIS[2])
    assert x[C["spread_region"]] == pytest.approx(np.log(1.25), rel=1e-12)
    assert baselines.SpreadReversion().point(x[None])[0] == pytest.approx(1.25 * 119 / np.sqrt(1.25), rel=1e-12)


def test_ranges_come_from_training_residuals_and_q50_is_the_rule():
    X = np.full((4, len(COLS)), np.nan)
    X[:, harness.LAST] = [100, 110, 120, 130]
    X[:, C["spread_region"]] = 0.0
    X[:, C["same_weekday"]] = [100, 110, 120, 130]
    for cls in baselines.BASELINES.values():
        m = cls()
        m.fit(X, 2 * X[:, harness.LAST])
        q = m.predict(X)
        assert np.allclose(q[:, 0], 2 * X[:, 0]) and np.allclose(q[:, 2], 2 * X[:, 0]) and np.array_equal(q[:, 1], X[:, 0])


# ---- folds, holdout, embargo, scoring ----

@pytest.fixture(scope="module")
def onion():
    """ONION, all 15 mandis, 2016-2018 (as test_features' small panel)."""
    return devdata.price_rows(generate(SPEC, "SYN"), date(2018, 12, 31), ("ONION",))


def small_cfg():
    cfg = copy.deepcopy(f1eval.load_config())
    cfg["folds"]["first_test"], cfg["folds"]["n_folds"] = "2018-01", 2
    cfg["horizons"], cfg["bootstrap"]["n_boot"] = [1, 7], 50
    return cfg


def test_config_and_dev_end():
    cfg = f1eval.load_config()
    assert devdata.dev_end(SPEC) == date(2025, 12, 18)
    assert f1eval.embargo(cfg, 3) == 3 and cfg["horizons"] == list(range(1, 8)) and cfg["folds"]["n_folds"] >= 6


def test_holdout_year_never_reaches_the_scored_rows():
    rows = devdata.price_rows(generate(SPEC, "SYN-NULL"), devdata.dev_end(SPEC), ("TOMATO",))
    assert max(r["market_date"] for r in rows) == date(2025, 12, 18)
    with pytest.raises(ValueError):
        f1eval.score_rows(rows + [row(MANDIS[0], date(2025, 12, 19), 100.0)], devdata.dev_end(SPEC), EVENTS, small_cfg())


def test_dev_folds_stop_before_the_holdout_and_embargo_is_h():
    cfg = f1eval.load_config()
    dates = np.arange(np.datetime64("2016-01-02"), np.datetime64("2025-12-19"))
    for h in (1, 3, 7):
        folds = f1eval.folds_for(dates, h, devdata.dev_end(SPEC), cfg)
        assert len(folds) == 6 and dates[folds[-1][1]].max() == np.datetime64("2025-11-30")
        for train, test in folds:
            start = dates[test].min()
            # a training target (market day t+h-1) published a day late is known from t+h+1: still known by the test start
            assert (dates[train] + np.timedelta64(h + 1, "D") <= start).all()
            assert dates[train].max() + np.timedelta64(h + 1, "D") == start  # and no extra day is lost
    with pytest.raises(ValueError):
        cfg2 = copy.deepcopy(cfg)
        cfg2["folds"]["first_test"] = "2024-07"
        f1eval.folds_for(dates, 1, devdata.dev_end(SPEC), cfg2)


@pytest.fixture(scope="module")
def table(onion):
    return f1eval.score_rows(onion, date(2018, 12, 31), EVENTS, small_cfg(), ("ONION",))


def test_naive_mase_is_exactly_one_and_bsn_equals_bn_at_h7(table):
    for r in table:
        if r["baseline"] == "B-N":
            assert r["mase"] == r["mase_lo"] == r["mase_hi"] == 1.0
    by = {(r["crop"], r["h"], r["baseline"]): r for r in table}
    for crop in ("ONION", f1eval.ALL):
        assert by[(crop, 7, "B-SN")]["mae"] == by[(crop, 7, "B-N")]["mae"]
        assert by[(crop, 7, "B-SN")]["mase"] == 1.0
        assert by[(crop, 7, "B-SN")]["sn_exact"] + by[(crop, 7, "B-SN")]["sn_older"] + by[(crop, 7, "B-SN")]["sn_last"] == \
            pytest.approx(1.0)
    assert {r["crop"] for r in table} == {"ONION", f1eval.ALL} and len(table) == 2 * 2 * 3


def test_scorer_output_is_byte_identical_and_lf(onion):
    a = f1eval.score_rows(onion, date(2018, 12, 31), EVENTS, small_cfg(), ("ONION",))
    b = f1eval.score_rows(onion, date(2018, 12, 31), EVENTS, small_cfg(), ("ONION",))
    ca, cb = (score_e2.to_csv([{"variant": "SYN", **r} for r in t]) for t in (a, b))
    assert ca.encode() == cb.encode() and "\r" not in ca and ca.endswith("\n")
    assert ca.splitlines()[0].split(",") == score_e2.FIELDS


def test_sanity_rule_flags_false_skill():
    ok = {"mase_hi": 1.0}
    bad = {"mase_hi": 0.97}
    assert f1eval.sanity_failures([ok]) == [] and f1eval.sanity_failures([ok, bad]) == [bad]
