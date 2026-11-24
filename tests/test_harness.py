"""Task 3.4: evaluation harness (file 04 §1.4) + L6 planted-signal fixture. No DB. DONE check: L6 signal is learned."""
import numpy as np
import pytest

from mandi.models.harness import Naive, evaluate, passes_s1, ratio_ci, rolling_origin_folds, score
from mandi.models.planted import LeadLearner, planted_panel

SEED = 34
FIRST, DEV_END = "2017-04", "2018-09-30"  # panel runs to 2018-12-31, so the last quarter plays the sealed holdout


@pytest.fixture(scope="module")
def planted():
    return planted_panel(seed=SEED)


@pytest.fixture(scope="module")
def folds(planted):
    return rolling_origin_folds(planted[2], FIRST, DEV_END)


def test_score_matches_hand_computed_values():
    y, last = np.array([10.0, 12, 9, 15]), np.full(4, 10.0)
    q = np.array([[9, 11, 12], [9, 11, 12], [9, 10, 12], [9, 13, 14]], float)
    # |e| = 1,1,1,2; naive |e| = 0,2,1,5; moves > 5% are rows 1-3, sign right on rows 1 and 3
    assert score(y, q, last) == pytest.approx({
        "n": 4, "mae": 1.25, "mase": 0.625, "pinball_10": 0.25, "pinball_50": 0.625, "pinball_90": 0.35,
        "coverage": 0.75, "width": 3.5, "direction": 2 / 3,
    })
    assert np.isnan(score(y, q, last, move=0.6)["direction"])


def test_six_rolling_folds_train_before_test_never_past_dev_end(planted, folds):
    dates, dev_end = planted[2], np.datetime64(DEV_END)
    assert len(folds) == 6
    assert (dates[folds[0][1]].min(), dates[folds[0][1]].max()) == (np.datetime64("2017-04-01"), np.datetime64("2017-06-30"))
    assert dates[folds[-1][1]].max() == dev_end
    for i, (train, test) in enumerate(folds):
        assert dates[train].max() < dates[test].min()
        if i:
            prev_train, prev_test = folds[i - 1]
            assert dates[prev_test].max() < dates[test].min()  # windows ordered in time, so no overlap
            assert np.array_equal(train, np.union1d(prev_train, prev_test))  # rolled forward 3 months, expanding window
    used = np.concatenate([np.concatenate(f) for f in folds])
    assert (dates > dev_end).any() and not (dates[used] > dev_end).any()


def test_fold_past_dev_end_refused_and_embargo_trims_train(planted):
    dates = planted[2]
    with pytest.raises(ValueError, match="past dev_end"):
        rolling_origin_folds(dates, "2018-01", DEV_END)
    train, _ = rolling_origin_folds(dates, FIRST, DEV_END, n_folds=1, embargo=2)[0]
    assert dates[train].max() == np.datetime64("2017-03-29")


def test_block_bootstrap_same_seed_same_ci_and_brackets_the_ratio():
    rng = np.random.default_rng(1)
    num, den = rng.uniform(0, 2, 300), rng.uniform(0, 2, 300)
    ci = ratio_ci(num, den, seed=7)
    assert ci == ratio_ci(num, den, seed=7) and ci != ratio_ci(num, den, seed=8)
    assert ci[0] < num.sum() / den.sum() < ci[1]
    assert ratio_ci(2 * den, den, block=1000) == pytest.approx((2.0, 2.0))  # block longer than the series still works


def test_naive_baseline_scores_mase_exactly_one(planted, folds):
    res = evaluate(Naive(), *planted, folds)["pooled"]
    assert res["mase"] == 1.0 and (res["mase_lo"], res["mase_hi"]) == pytest.approx((1.0, 1.0))
    assert not passes_s1(res)


def test_L6_planted_signal_is_learned(planted, folds):
    X, y, dates = planted
    res = evaluate(LeadLearner(), X, y, dates, folds)["pooled"]
    assert res["mase_hi"] < 0.8  # expected MASE about noise / hypot(signal, noise) = 0.71
    assert passes_s1(res)  # pooled MASE < 1, upper bound < 1, coverage 75-85%
    assert res["direction"] > 0.6
    dev = dates <= np.datetime64(DEV_END)
    m = LeadLearner()
    m.fit(X[dev], y[dev])
    assert m.coef[1] == pytest.approx(0.02, rel=0.1)  # the planted lead coefficient is recovered


def test_L6_null_twin_reports_no_skill(folds):
    # same dates as the planted panel, so the same folds apply
    res = evaluate(LeadLearner(), *planted_panel(seed=SEED, null=True), folds)["pooled"]
    assert res["mase_hi"] >= 1 and not passes_s1(res)
