"""Development-period price rows for F1 experiments (E2 task 7.3, E3 11.1, E5 12.2; DECISIONS.md D-033). Pure, no DB.

One adapter shared by the leakage tests and every results script, so all of them score the same rows:
generator rows -> price_obs-shaped rows (canonical PKR/100 kg via the loader's unit table, outlier_flag from QC),
development period only. Everything on or after the first holdout-year day is dropped here, before QC, features or
folds can see it.

shortcut: mandi_id comes from the generator's answer key (truth_mandi_id), not from 4.2 name matching: the same rows
as L1-L5 (D-029). FYP-II skips this adapter: it reads price_obs rows of ONE source (DB) and passes them on directly.
"""
from datetime import date, datetime

from mandi.ingest import qc
from mandi.ingest.loader import TO_PER_100KG

DAILY_CROPS = ("ONION", "TOMATO", "POTATO")


def dev_end(spec: dict) -> date:
    """Last development day = the day before the spec's holdout-year start (2025-12-18 for spec v1, D-014)."""
    return date.fromordinal(spec["period"]["holdout"]["start"].toordinal() - 1)


def price_rows(gen_rows, end: date, crops=DAILY_CROPS) -> list[dict]:
    """Generator rows (scripts.make_synthetic.generate) -> price_obs rows up to `end` inclusive, QC-flagged.

    QC runs on the kept rows only, so no row after `end` can influence a flag. Known limit (D-033): QC's same-day
    NEIGHBOURS_5X rule may read a neighbour row published late, i.e. not yet known on the first issue day that uses
    the flagged row; the trailing 28-day rule only reads earlier rows, which are all known by then.
    """
    out = []
    for r in gen_rows:
        d = date.fromisoformat(r["market_date"])
        if d > end or r["crop_id"] not in crops:
            continue
        f = float(TO_PER_100KG[r["unit_raw"]])
        out.append({"crop_id": r["crop_id"], "mandi_id": r["truth_mandi_id"], "market_date": d,
                    "reported_at": datetime.fromisoformat(r["reported_at"]), "arrivals_qty": float(r["arrivals_qty"]),
                    "late": r["truth_late"] == "1", **{f"{k}_pkr100kg": float(r[f"{k}_raw"]) * f for k in ("min", "max", "avg")}})
    for r, why in zip(out, qc.flag(out), strict=True):
        r["outlier_flag"] = "SUSPECT" if why else "OK"
        r["qc_reasons"] = why
    return out
