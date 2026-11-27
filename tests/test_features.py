"""Leakage tests L1-L5 for the FS-S feature builder (task 6.3; file 04 §1.3, DECISIONS.md D-029). DB-free.

L1, L3 and L5 also run a deliberately leaky variant and must catch it (so a pass means the check has power); L4's fixture
carries the wrong rows (realised rain, older forecast, forecast issued on t) and checks they are ignored; L2 is a
robustness check with no leak control.
All inputs stop at the development end (2025-12-18): the holdout year is never read.
"""
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from mandi.features import fs_s
from mandi.ingest import qc
from mandi.ingest.loader import TO_PER_100KG
from mandi.models import harness
from mandi.models.planted import LeadLearner
from scripts.make_synthetic import generate, load_spec

SPEC = load_spec()
DEV_END = date(2025, 12, 18)  # spec period.holdout.start - 1 day
EVENTS = fs_s.spec_events(SPEC)
COL = {f: i for i, f in enumerate(fs_s.XY_COLUMNS)}


def syn_rows(variant="SYN", crops=("ONION", "TOMATO", "POTATO"), end=DEV_END):
    """Generator rows as price_obs rows: canonical units (loader rule), outlier_flag from QC, dev period only."""
    out = []
    for r in generate(SPEC, variant):
        d = date.fromisoformat(r["market_date"])
        if d > end or r["crop_id"] not in crops:
            continue
        f = float(TO_PER_100KG[r["unit_raw"]])
        out.append({"crop_id": r["crop_id"], "mandi_id": r["truth_mandi_id"], "market_date": d,
                    "reported_at": datetime.fromisoformat(r["reported_at"]), "arrivals_qty": float(r["arrivals_qty"]),
                    "late": r["truth_late"] == "1", **{f"{k}_pkr100kg": float(r[f"{k}_raw"]) * f for k in ("min", "max", "avg")}})
    for r, why in zip(out, qc.flag(out), strict=True):
        r["outlier_flag"] = "SUSPECT" if why else "OK"
    return out


@pytest.fixture(scope="module")
def small():
    """ONION, all 15 mandis (spreads need neighbours), 2016-2018 (the arrivals norm needs a year of history)."""
    return syn_rows(crops=("ONION",), end=date(2018, 12, 31))


@pytest.fixture(scope="module")
def issue_days(small):
    """Days whose t-1 row was published late (the T1 boundary) plus evenly spread days."""
    late = sorted({r["market_date"] + timedelta(1) for r in small if r["late"] and r["market_date"].year >= 2017})
    return late[::40][:6] + [date(2016, 3, 1), date(2017, 1, 2), date(2017, 7, 15), date(2018, 6, 30), date(2018, 12, 1)]


def leaky(rows):
    """A builder bug: treats every row as known one day early (e.g. filtering on market_date instead of reported_at)."""
    return [r | {"reported_at": r["reported_at"] - timedelta(1)} for r in rows]


def at(rows, t, **kw):
    """FS-S features of every series on issue day t."""
    keys, days, F = fs_s.feature_table(rows, EVENTS, last_day=t, **kw)
    return keys, F[:, np.flatnonzero(days == np.datetime64(t))[0]]


def cut(t):
    return datetime.combine(t, datetime.min.time(), fs_s.PKT)


def same(a, b):
    return a[0] == b[0] and np.array_equal(a[1], b[1], equal_nan=True)


# ---- L3 (T2): recomputing from truncated data equals the stored feature ---------------------------------------------

def l3_ok(build, rows, ts):
    """Features at t from the full panel == features from rows with reported_at < t 00:00 PKT only."""
    keys, days, F = fs_s.feature_table(build(rows), EVENTS)
    for t in ts:
        trunc = [r for r in rows if r["reported_at"] < cut(t)]
        stored = (keys, F[:, np.flatnonzero(days == np.datetime64(t))[0]])
        if not same(stored, at(build(trunc), t)):
            return False
    return True


def test_L3_truncated_recompute_equals_stored(small, issue_days):
    assert l3_ok(lambda r: r, small, issue_days)


def test_L3_catches_a_leak(small, issue_days):
    assert not l3_ok(leaky, small, issue_days)


# ---- L1 (T1): only rows with reported_at < t 00:00 PKT reach issue day t --------------------------------------------

def poison_future(rows, t):
    """Every row not yet known at t gets prices x1000 and arrivals x1000."""
    return [r | {k: r[k] * 1000 for k in ("min_pkr100kg", "max_pkr100kg", "avg_pkr100kg", "arrivals_qty")}
            if r["reported_at"] >= cut(t) else r for r in rows]


@pytest.mark.parametrize("build,clean", [(lambda r: r, True), (leaky, False)])
def test_L1_unknown_rows_cannot_move_features(small, issue_days, build, clean):
    assert all(same(at(build(small), t), at(build(poison_future(small, t)), t)) for t in issue_days) is clean


def test_L1_boundary_is_exactly_t_midnight():
    """Market date t-1 published t-1 18:00 is LAST at t; the same row published t 00:00 (one day later) is not."""
    t = date(2017, 3, 8)
    base = [{"crop_id": "ONION", "mandi_id": "LAHORE", "market_date": t - timedelta(d), "min_pkr100kg": 900.0,
             "max_pkr100kg": 1100.0, "avg_pkr100kg": 1000.0, "arrivals_qty": 50.0,
             "reported_at": datetime.combine(t - timedelta(d), datetime.min.time(), fs_s.PKT) + timedelta(hours=18)}
            for d in range(2, 40)]
    new = base[0] | {"market_date": t - timedelta(1), "min_pkr100kg": 1900.0, "max_pkr100kg": 2100.0}
    on_time = new | {"reported_at": cut(t - timedelta(1)) + timedelta(hours=18)}
    for when, last in [(on_time["reported_at"], 2000.0), (cut(t), 1000.0), (cut(t) - timedelta(microseconds=1), 2000.0)]:
        _, F = at(base + [new | {"reported_at": when}], t)
        assert F[0, fs_s.FEATURES.index("last")] == pytest.approx(last, rel=1e-12), when


# ---- L4 (T3): weather forecast as issued on t-1, never the realised weather -----------------------------------------

def test_L4_rain_uses_forecast_issued_before_t_not_realised():
    t = date(2026, 3, 10)
    pk = fs_s.PKT
    w = [{"date": t - timedelta(1), "rain_mm": 4.0, "is_forecast": False, "issued_at": None},
         {"date": t - timedelta(8), "rain_mm": 99.0, "is_forecast": False, "issued_at": None},   # outside the 7 days
         {"date": t, "rain_mm": 50.0, "is_forecast": False, "issued_at": None},                  # realised: never used
         {"date": t + timedelta(1), "rain_mm": 60.0, "is_forecast": False, "issued_at": None},
         *({"date": t + timedelta(d), "rain_mm": 1.0 + d, "is_forecast": True,                   # issued t-1 06:00
            "issued_at": datetime(2026, 3, 9, 6, tzinfo=pk)} for d in range(3)),
         *({"date": t + timedelta(d), "rain_mm": 7.0, "is_forecast": True,                       # older issue
            "issued_at": datetime(2026, 3, 8, 6, tzinfo=pk)} for d in range(3)),
         *({"date": t + timedelta(d), "rain_mm": 30.0, "is_forecast": True,                      # issued on t
            "issued_at": datetime(2026, 3, 10, 0, tzinfo=pk)} for d in range(3))]
    assert fs_s.rain_features(w, t, 2) == (4.0, 1.0 + 2.0)
    assert fs_s.rain_features(w, t, 3) == (4.0, 1.0 + 2.0 + 3.0)
    seen, fc = fs_s.rain_features(w[:4], t, 1)  # no forecast issued before t -> unknown, never the realised 50 mm
    assert seen == 4.0 and np.isnan(fc)


# ---- L5 (T4-T5): anything fitted sees training rows only ------------------------------------------------------------

def scores(X, y, dates, fold, prep=lambda X: X):
    return harness.evaluate(LeadLearner(), prep(X), y, dates, [fold], n_boot=50)["folds"][0]


def poison_outside(X, y, fold):
    """y of every non-training row and X of rows after the test window x1000 (test rows keep X so they can be scored)."""
    train, test = fold
    X, y = X.copy(), y.copy()
    other = np.setdiff1d(np.arange(len(y)), train)
    y[other] *= 1000
    after = np.setdiff1d(other, test)
    X[after, 1:] *= 1000
    return X, y


def test_L5_fit_sees_training_rows_only(small):
    X, y, dates = fs_s.make_xy(small, horizons=(1,), events=EVENTS)
    ok = ~np.isnan(X).any(axis=1)
    X, y, dates = X[ok], y[ok], dates[ok]
    fold = harness.rolling_origin_folds(dates, "2018-03", "2018-12-31", n_folds=1, embargo=2)[0]
    Xp, yp = poison_outside(X, y, fold)
    clean = scores(X, y, dates, fold)
    _, test = fold
    yp[test] = y[test]  # score both runs against the true targets
    assert scores(Xp, yp, dates, fold) == clean

    # a T4 violation: winsorising X at quantiles of ALL rows before the folds (fitted outside fit()) must be caught.
    # (Not z-scaling: OLS with an intercept is invariant to it, so that leak would not move the predictions.)
    def winsorise(X):
        Z = X.copy()
        Z[:, 1:] = np.clip(X[:, 1:], *np.quantile(X[:, 1:], [0.05, 0.95], axis=0))
        return Z
    leak, base = scores(Xp, yp, dates, fold, winsorise), scores(X, y, dates, fold, winsorise)
    assert abs(leak["mae"] - base["mae"]) > 1e-6 * base["mae"]


# ---- L2 (T1): delay every row one more day; accuracy must not collapse (rule fixed in D-029 before the first run) ----

@pytest.fixture(scope="module")
def dev():
    return syn_rows()


def skill(rows, h):
    X, y, dates = fs_s.make_xy(rows, horizons=(h,), events=EVENTS)
    ok = ~np.isnan(X).any(axis=1)
    X, y, dates = X[ok], y[ok], dates[ok]
    folds = harness.rolling_origin_folds(dates, "2024-06", DEV_END, embargo=h + 1)
    return 1 - harness.evaluate(LeadLearner(), X, y, dates, folds, n_boot=50)["pooled"]["mase"]


@pytest.mark.parametrize("h", [1, 2, 3])
def test_L2_one_more_day_of_lag_does_not_collapse_skill(dev, h):
    base = skill(dev, h)
    delayed = skill([r | {"reported_at": r["reported_at"] + timedelta(1)} for r in dev], h)
    assert base > 0, f"h={h}: FS-S + OLS shows no skill on SYN (base skill {base:.3f})"
    assert delayed >= 0.5 * base, f"h={h}: skill {base:.3f} -> {delayed:.3f} with one more day of lag"


def test_make_xy_contract(small):
    X, y, dates = fs_s.make_xy(small, horizons=(1, 3), events=EVENTS)
    assert X.shape[1] == len(fs_s.XY_COLUMNS) and len(X) == len(y) == len(dates)
    assert set(np.unique(X[:, COL["h"]])) == {1, 3}
    assert not np.isnan(X[:, harness.LAST]).any() and (y > 0).all()
    assert dates.dtype == np.dtype("datetime64[D]")
    assert np.nanmax(X[:, COL["days_to_event"]]) <= fs_s.EVENT_CAP


def test_naive_reported_at_rejected():
    with pytest.raises(ValueError):
        fs_s.known_from(datetime(2020, 1, 1, 18))


def test_calendar_columns(small):
    X, _, dates = fs_s.make_xy(small, horizons=(1,), events=EVENTS)
    py = [np.datetime64(d, "D").astype(object) for d in dates[:50]]
    assert X[:50, COL["weekday"]].tolist() == [d.weekday() for d in py]
    assert X[:50, COL["doy"]].tolist() == [d.timetuple().tm_yday for d in py]
