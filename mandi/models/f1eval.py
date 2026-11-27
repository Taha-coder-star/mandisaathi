"""Shared F1 development-fold evaluation (task 7.3; DECISIONS.md D-033). Imported by E2 (scripts/score_e2.py), E3 (11.1)
and E5 (12.2) so every experiment uses the same folds, embargo and bootstrap from params/ps_v1.yaml (f1_eval).

Source-agnostic: score_rows takes price_obs-shaped rows of ONE source (SYN, SYN-NULL, or a real source in FYP-II) and
the last development day; nothing here knows how the rows were made.
"""
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from mandi.features import fs_s
from mandi.gazetteer import read
from mandi.models import harness
from mandi.models.baselines import BASELINES

PARAMS = Path(__file__).resolve().parents[2] / "params" / "ps_v1.yaml"
ALL = "ALL"  # crop label of the pooled-over-crops rows
METRICS = ["n", "mase", "mase_lo", "mase_hi", "mae", "pinball_10", "pinball_50", "pinball_90", "coverage", "width", "direction"]


def load_config(path: Path = PARAMS) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["f1_eval"]


def embargo(cfg: dict, h: int) -> int:
    e = cfg["folds"]["embargo"]
    return h if e == "h" else int(e)


def folds_for(dates, h: int, dev_end: date, cfg: dict):
    f = cfg["folds"]
    return harness.rolling_origin_folds(dates, f["first_test"], dev_end, n_folds=f["n_folds"], test_len=f["test_months"],
                                        step=f["step_months"], embargo=embargo(cfg, h))


def panel(rows, events, horizons):
    """make_xy with the B-SN columns: (X, y, dates) on the common row set every baseline is scored on."""
    return fs_s.make_xy(rows, horizons=horizons, events=events, same_weekday=True)


def score_rows(rows, dev_end: date, events, cfg: dict, crops=None):
    """E2 table rows for one source: [{crop, h, baseline, **metrics, sn_exact, sn_older, sn_last}] for each crop and ALL.

    sn_* = share of rows where B-SN used the exact day t+h-8, an older known quote, or fell back to LAST.
    """
    if max(r["market_date"] for r in rows) > dev_end:
        raise ValueError("rows after the development end reached the scorer")
    X, y, dates = panel(rows, events, cfg["horizons"])
    col = {c: i for i, c in enumerate(fs_s.xy_columns(same_weekday=True))}
    crop_ids = list(read()["crops"]) if crops is None else list(crops)
    code = {c: i for i, c in enumerate(read()["crops"])}
    present = [c for c in crop_ids if (X[:, col["crop"]] == code[c]).any()]
    b = cfg["bootstrap"]
    out = []
    for crop in [*present, ALL]:
        for h in cfg["horizons"]:
            m = X[:, col["h"]] == h
            if crop != ALL:
                m &= X[:, col["crop"]] == code[crop]
            Xc, yc, dc = X[m], y[m], dates[m]
            folds = folds_for(dc, h, dev_end, cfg)
            test = np.concatenate([t for _, t in folds])
            lag = Xc[test, col["same_weekday_lag"]]
            sn = {"sn_exact": float(np.mean(lag == 8 - h)), "sn_older": float(np.mean(lag > 8 - h)),
                  "sn_last": float(np.mean(np.isnan(lag)))}
            for name, cls in BASELINES.items():
                res = harness.evaluate(cls(), Xc, yc, dc, folds, block=b["block_days"], n_boot=b["n_boot"], seed=b["seed"])
                pooled = res["pooled"]
                out.append({"crop": crop, "h": h, "baseline": name, **{k: pooled[k] for k in METRICS}, **sn})
    return out


def sanity_failures(table: list[dict]) -> list[dict]:
    """Rows breaking the pre-registered rule (params f1_eval.sanity): on the null variant no baseline has mase_hi < 1."""
    return [r for r in table if r["mase_hi"] < 1]
