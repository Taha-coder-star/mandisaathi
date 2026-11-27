"""F1 baselines B-N, B-SN, B-SR (task 7.3, file 04 §1.1-1.2; DECISIONS.md D-033). Harness models: fit(X, y), predict(X).

Every baseline is a fixed point rule q50 plus a range from the fold's TRAINING rows: q10/q90 = q50 x the 0.1/0.9
quantiles of log(y / q50) (file 04 §1.1 "empirical residuals"), exactly like harness.Naive. q50 is the rule itself,
never shifted by the residuals.

  B-N   q50 = LAST = M(t-1)                                         (harness.Naive)
  B-SN  q50 = M(t+h-8), the target's weekday one week earlier, as known at t (fs_s SAME_WEEKDAY columns; newest
        earlier known quote if that day is missing, else LAST). At h = 7 that day is t-1, so B-SN = B-N there.
  B-SR  q50 = LAST x exp(-spread_region / 2): halfway (in logs) to the crop's median LAST over all mandis, same for every h.
"""
import numpy as np

from mandi.features import fs_s
from mandi.models.harness import LAST, QUANTILES, Naive

COLUMNS = fs_s.xy_columns(same_weekday=True)


class _PointPlusResiduals:
    def point(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.rq = np.quantile(np.log(y / self.point(X)), QUANTILES)

    def predict(self, X: np.ndarray) -> np.ndarray:
        p = self.point(X)
        q = p[:, None] * np.exp(self.rq)
        q[:, 1] = p
        return q


class SeasonalNaive(_PointPlusResiduals):
    """B-SN. X must carry fs_s.xy_columns(same_weekday=True)."""

    def __init__(self, columns=COLUMNS):
        self.col = columns.index("same_weekday")

    def point(self, X: np.ndarray) -> np.ndarray:
        sw = X[:, self.col]
        return np.where(np.isnan(sw), X[:, LAST], sw)


class SpreadReversion(_PointPlusResiduals):
    """B-SR. spread_region = log LAST - median log LAST of the crop's mandis at t (the series itself included)."""

    def __init__(self, columns=COLUMNS):
        self.col = columns.index("spread_region")

    def point(self, X: np.ndarray) -> np.ndarray:
        return X[:, LAST] * np.exp(-0.5 * X[:, self.col])


BASELINES = {"B-N": Naive, "B-SN": SeasonalNaive, "B-SR": SpreadReversion}
