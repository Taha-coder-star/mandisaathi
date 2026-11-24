"""L6 planted-signal fixture (file 04 §1.3) and a tiny reference learner. Dev/test only: proves the harness can find skill
when skill exists, and reports none on the SYN-NULL-style twin, so a null result on real data is a valid finding.
"""
import numpy as np

from mandi.models.harness import LAST, QUANTILES


def planted_panel(seed: int = 0, n_series: int = 10, n_days: int = 1096, signal: float = 0.02, noise: float = 0.02,
                  null: bool = False):
    """(X, y, dates) in the harness convention: X = [M(t-1), s(t-1)], y = M(t), dates = issue day t from 2016-01-02.

    Planted: log M(t) - log M(t-1) = signal * s(t-1) + noise * e(t), with s, e iid N(0, 1) and s(t-1) known on issue day t
    (a lead feature like an arrivals shock). Null twin: same draws, returns = hypot(signal, noise) * e(t), a pure random walk
    with the same daily volatility; s is still in X but carries nothing.
    """
    rng = np.random.default_rng(seed)
    s = rng.standard_normal((n_series, n_days))
    e = rng.standard_normal((n_series, n_days))
    base = np.log(rng.uniform(2000, 8000, (n_series, 1)))  # PKR/100 kg starting levels
    r = np.hypot(signal, noise) * e[:, 1:] if null else signal * s[:, :-1] + noise * e[:, 1:]
    p = np.exp(base + np.concatenate([np.zeros((n_series, 1)), np.cumsum(r, axis=1)], axis=1))
    X = np.stack([p[:, :-1].ravel(), s[:, :-1].ravel()], axis=1)
    dates = np.tile(np.datetime64("2016-01-01") + np.arange(1, n_days), n_series)
    return X, p[:, 1:].ravel(), dates


class LeadLearner:
    """Reference learner for L6 only: OLS of log(y/last) on X's feature columns; range from training residual quantiles."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        A = np.column_stack([np.ones(len(X)), X[:, LAST + 1:]])
        z = np.log(y / X[:, LAST])
        self.coef = np.linalg.lstsq(A, z, rcond=None)[0]
        self.rq = np.quantile(z - A @ self.coef, QUANTILES)

    def predict(self, X: np.ndarray) -> np.ndarray:
        A = np.column_stack([np.ones(len(X)), X[:, LAST + 1:]])
        return X[:, LAST, None] * np.exp((A @ self.coef)[:, None] + self.rq)
