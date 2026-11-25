"""Price quality rules (file 03 §6; task 5.3, DECISIONS.md D-024). Pure: rows in, reasons out; no DB.

A row with any reason is SUSPECT (12.1 writes price_obs.outlier_flag; 8.2 skips SUSPECT rows). Values are canonical
PKR per 100 kg, so per-40 kg rows must already be converted by the loader (to_price_row) before they reach here.
Thresholds are the file 03 ASSUMPTION values; the 28-day robust-SD floor is ours (E1 tuning, D-024).
"""
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np

WINDOW_DAYS = 28  # trailing calendar days before the row (no look-ahead: the batch runs daily)
K_ROBUST_SD = 4.0
SD_FLOOR = 0.05  # log units; a calm 28-day window otherwise flags ordinary moves (E1 sweep: FP < 1%, recall 100%; D-024)
MIN_WINDOW_OBS = 5  # fewer earlier quotes: the 28-day rule is skipped, the same-day rule still applies
NEIGHBOUR_RATIO = 5.0
MIN_NEIGHBOURS = 2

MIN_GT_MAX, ROBUST_SD, NEIGHBOURS = "MIN_GT_MAX", "ROBUST_SD_4", "NEIGHBOURS_5X"


def mid(row: dict) -> float | None:
    """avg if given, else the middle of min and max (real exports may lack avg)."""
    if row.get("avg_pkr100kg") is not None:
        return float(row["avg_pkr100kg"])
    lo, hi = row.get("min_pkr100kg"), row.get("max_pkr100kg")
    return None if lo is None or hi is None else (float(lo) + float(hi)) / 2


def flag(rows: Sequence[dict]) -> list[set[str]]:
    """Reasons per row (empty set = OK). Rows need crop_id, mandi_id, market_date and the *_pkr100kg values."""
    reasons: list[set[str]] = [set() for _ in rows]
    logs: list[float | None] = []
    series, day = defaultdict(list), defaultdict(list)
    for i, r in enumerate(rows):
        lo, hi = r.get("min_pkr100kg"), r.get("max_pkr100kg")
        if lo is not None and hi is not None and lo > hi:
            reasons[i].add(MIN_GT_MAX)
        m = mid(r)
        logs.append(math.log(m) if m and m > 0 else None)
        if logs[i] is not None:
            d = r["market_date"] if isinstance(r["market_date"], date) else date.fromisoformat(r["market_date"])
            series[(r["crop_id"], r["mandi_id"])].append((d, i))
            day[(r["crop_id"], d)].append(i)

    for pts in series.values():
        pts.sort()
        start = 0
        for j, (d, i) in enumerate(pts):
            while pts[start][0] <= d - timedelta(WINDOW_DAYS):
                start += 1
            if j - start >= MIN_WINDOW_OBS:
                w = np.array([logs[k] for _, k in pts[start:j]])
                med = float(np.median(w))
                sd = max(1.4826 * float(np.median(np.abs(w - med))), SD_FLOOR)
                if abs(logs[i] - med) > K_ROBUST_SD * sd:
                    reasons[i].add(ROBUST_SD)

    lim = math.log(NEIGHBOUR_RATIO)
    for idx in day.values():
        if len(idx) <= MIN_NEIGHBOURS:
            continue
        vals = np.array([logs[i] for i in idx])
        for n, i in enumerate(idx):
            if abs(vals[n] - float(np.median(np.delete(vals, n)))) >= lim:
                reasons[i].add(NEIGHBOURS)
    return reasons
