"""C16 evaluation harness (task 3.4, file 04 §1.4): rolling-origin folds, F1 metrics, block bootstrap. Offline, numpy only.

Data convention: one row per (series, issue day t, horizon h). `X` is 2-D with column LAST = the last usable price M(t-1)
(PKR/100 kg) and any feature columns after it; `y` is the realised price M(t+h-1); `dates` is the issue day t (datetime64[D]).
Evaluate one horizon at a time (filter rows by h first). A model is anything with fit(X, y) and predict(X) -> (n, 3) quantiles.
"""
from typing import Protocol

import numpy as np

LAST = 0  # column of X holding M(t-1)
QUANTILES = (0.1, 0.5, 0.9)
S1_COVERAGE = (0.75, 0.85)  # file 04 §1.4: coverage of the 80% range must land here


class Model(Protocol):
    def fit(self, X: np.ndarray, y: np.ndarray) -> None: ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...  # (n, 3): q10, q50, q90 in PKR


class Naive:
    """B-N: price stays at M(t-1). Range from training log(y/last) quantiles (file 04 §1.1: baselines use empirical residuals)."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.rq = np.quantile(np.log(y / X[:, LAST]), QUANTILES)

    def predict(self, X: np.ndarray) -> np.ndarray:
        q = X[:, LAST, None] * np.exp(self.rq)
        q[:, 1] = X[:, LAST]  # the point forecast is exactly the last price, so its MASE is exactly 1
        return q


def rolling_origin_folds(dates, first_test, dev_end, n_folds: int = 6, test_len: int = 3, step: int = 3, embargo: int = 0):
    """[(train_idx, test_idx)] for expanding-window folds. Fold i tests months [first_test + i*step, + test_len).

    Train = rows with issue day < test start - embargo (set embargo = h-1 so no training target lands in the test window).
    Raises if any test window would end after dev_end, so rows past dev_end (the sealed holdout year) are never in a fold.
    """
    dates = np.asarray(dates, dtype="datetime64[D]")
    start0, dev_end = np.datetime64(first_test, "M"), np.datetime64(dev_end, "D")
    folds = []
    day = np.timedelta64(1, "D")
    for i in range(n_folds):
        lo = (start0 + np.timedelta64(i * step, "M")).astype("datetime64[D]")
        hi = (start0 + np.timedelta64(i * step + test_len, "M")).astype("datetime64[D]")  # exclusive
        if hi - day > dev_end:
            raise ValueError(f"fold {i} test window ends {hi - day}, past dev_end {dev_end}")
        train = np.flatnonzero(dates < lo - embargo * day)
        test = np.flatnonzero((dates >= lo) & (dates < hi))
        if not len(train) or not len(test):
            raise ValueError(f"fold {i} ({lo}..{hi - day}) has an empty train or test set")
        folds.append((train, test))
    return folds


def pinball(y, q, tau: float) -> float:
    u = y - q
    return float(np.mean(np.maximum(tau * u, (tau - 1) * u)))


def score(y, q, last, move: float = 0.05) -> dict:
    """All file 04 §1.4 metrics for one set of test rows. q is (n, 3) = q10, q50, q90.

    MASE scaling: MAE of the model's q50 divided by MAE of B-N (y vs last) on the SAME test rows (out-of-sample ratio,
    not Hyndman's in-sample scale), so MASE < 1 means "beats naive" on exactly the points scored.
    Direction accuracy: among rows whose actual move |y/last - 1| > move, the share where sign(q50 - last) == sign(y - last).
    """
    y, q, last = np.asarray(y, float), np.asarray(q, float), np.asarray(last, float)
    big = np.abs(y / last - 1) > move
    return {
        "n": len(y),
        "mae": float(np.mean(np.abs(y - q[:, 1]))),
        "mase": float(np.mean(np.abs(y - q[:, 1])) / np.mean(np.abs(y - last))),
        "pinball_10": pinball(y, q[:, 0], 0.1),
        "pinball_50": pinball(y, q[:, 1], 0.5),
        "pinball_90": pinball(y, q[:, 2], 0.9),
        "coverage": float(np.mean((y >= q[:, 0]) & (y <= q[:, 2]))),
        "width": float(np.mean(q[:, 2] - q[:, 0])),
        "direction": float(np.mean(np.sign(q[big, 1] - last[big]) == np.sign(y[big] - last[big]))) if big.any() else float("nan"),
    }


def ratio_ci(num, den, block: int = 10, n_boot: int = 2000, seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Circular block bootstrap CI for sum(num) / sum(den); num/den are time-ordered per-day totals.

    shortcut: fixed block length (10 trading days), no data-driven choice (Politis-White); revisit if residuals show longer memory.
    """
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, (n_boot, -(-n // block)))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    stats = num[idx].sum(axis=1) / den[idx].sum(axis=1)
    lo, hi = np.quantile(stats, [(1 - level) / 2, (1 + level) / 2])
    return float(lo), float(hi)


def predict_folds(model: Model, X, y, folds) -> list[np.ndarray]:
    """Out-of-fold quantiles: for each fold, fit on its train rows and return the sorted (n_test, 3) q10/q50/q90 of its
    test rows (same order as the fold's test index). E5 (12.2) reads these as the P10/P50 of a baseline or model."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    out = []
    for train, test in folds:
        model.fit(X[train], y[train])
        out.append(np.sort(np.asarray(model.predict(X[test]), float), axis=1))  # separately fitted quantiles can cross (D-010)
    return out


def evaluate(model: Model, X, y, dates, folds, block: int = 10, n_boot: int = 2000, seed: int = 0) -> dict:
    """Fit on each fold's train rows, score its test rows. Returns per-fold scores and the pooled score with a MASE CI.

    The bootstrap resamples days, not rows: errors of all series on one day are summed first, so cross-series
    correlation on a day stays inside one resampled unit.
    """
    X, y, dates = np.asarray(X, float), np.asarray(y, float), np.asarray(dates, dtype="datetime64[D]")
    per_fold, rows, preds = [], [], []
    for (_, test), q in zip(folds, predict_folds(model, X, y, folds), strict=True):
        per_fold.append(score(y[test], q, X[test, LAST]))
        rows.append(test)
        preds.append(q)
    test, q = np.concatenate(rows), np.concatenate(preds)
    yt, last = y[test], X[test, LAST]
    _, day = np.unique(dates[test], return_inverse=True)
    lo, hi = ratio_ci(np.bincount(day, np.abs(yt - q[:, 1])), np.bincount(day, np.abs(yt - last)), block, n_boot, seed)
    return {"folds": per_fold, "pooled": score(yt, q, last) | {"mase_lo": lo, "mase_hi": hi}}


def passes_s1(pooled: dict) -> bool:
    """File 04 S1: pooled MASE < 1, its 95% block-bootstrap upper bound < 1, coverage of the 80% range in 75-85%."""
    return pooled["mase"] < 1 and pooled["mase_hi"] < 1 and S1_COVERAGE[0] <= pooled["coverage"] <= S1_COVERAGE[1]
