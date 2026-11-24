"""Synthetic price generator (task 3.2; data/synthetic/spec.yaml, file 03 §9.1, DECISIONS.md D-014).

  python scripts/make_synthetic.py [--seed N] [--variant SYN|SYN-NULL] [--out DIR]

Writes syn.csv, syn_null.csv and wheat_monthly.csv into DIR (default data/synthetic) and prints each sha256
(--variant writes only that variant's file). Same seed + same spec -> same bytes on the same machine.
truth_* columns are the generator's answer key (QC, name matching, timing tests); the loader never reads them.
"""
import argparse
import csv
import hashlib
import math
import zlib
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "data" / "synthetic" / "spec.yaml"
FILES = {"SYN": "syn.csv", "SYN-NULL": "syn_null.csv"}
PER40 = Decimal("0.4")  # per-100kg -> per-40kg; the loader multiplies by 2.5


def load_spec(path: Path = SPEC_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rng(seed: int, *key: str) -> np.random.Generator:
    """One independent stream per named key, so adding a mandi or crop never shifts another stream (D-014)."""
    return np.random.default_rng(np.random.SeedSequence([seed, *(zlib.crc32(k.encode()) for k in key)]))


def km(a: dict, b: dict) -> float:
    p = math.pi / 180
    dlat, dlon = (b["lat"] - a["lat"]) * p, (b["lon"] - a["lon"]) * p
    h = math.sin(dlat / 2) ** 2 + math.cos(a["lat"] * p) * math.cos(b["lat"] * p) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def calendar(spec: dict) -> tuple[list[date], np.ndarray]:
    """All calendar days of the period and a mask of trading days (Mon-Sat, not a holiday)."""
    p = spec["period"]
    days = [p["start"] + timedelta(i) for i in range((p["end"] - p["start"]).days + 1)]
    h, mv = p["holidays"], p["holidays"]["moving"]
    off = set()
    for y in {d.year for d in days}:
        off |= {date(y, int(md[:2]), int(md[3:])) for md in h["fixed_mmdd"]}
        for b in mv["blocks"]:
            first = date(y, b["anchor"].month, b["anchor"].day) + timedelta(mv["drift_days_per_year"] * (y - mv["anchor_year"]))
            off |= {first + timedelta(i) for i in range(b["days"])}
    return days, np.array([d.weekday() != 6 and d not in off for d in days])


def month_pos(d: date) -> float:
    """1.0 = 1 Jan, 2.5 = mid-Feb (spec crops note)."""
    start = date(d.year, 1, 1)
    return 1 + 12 * (d - start).days / (date(d.year + 1, 1, 1) - start).days


def dip_sum(dips: list[dict], m: np.ndarray) -> np.ndarray:
    total = np.zeros_like(m)
    for dp in dips:
        dist = (m - dp["month"] + 6) % 12 - 6  # circular month distance
        total += dp["depth"] * np.exp(-0.5 * (dist / dp["width"]) ** 2)  # width read as the Gaussian sigma (D-014)
    return total


def ar1(e: np.ndarray, phi: float, start: float) -> np.ndarray:
    """x[0] = start, x[t] = phi * x[t-1] + e[t]."""
    out = [start]
    for v in e[1:].tolist():
        out.append(phi * out[-1] + v)
    return np.array(out)


def stationary_ar1(r: np.random.Generator, phi: float, sigma: float, n: int) -> np.ndarray:
    e = r.standard_normal(n) * sigma
    return ar1(e, phi, e[0] / math.sqrt(1 - phi**2))


def money(x: float, per40: bool) -> str:
    s = f"{x:.2f}"
    return str(Decimal(s) * PER40) if per40 else s  # <= 3 dp, so the loader's x2.5 gives back s exactly


def generate(spec: dict, variant: str = "SYN", seed: int | None = None) -> list[dict]:
    """Daily rows for the non-monthly crops, sorted by (market_date, crop_id, mandi_id); values already formatted."""
    if variant not in FILES:
        raise ValueError(f"unknown variant {variant!r}")
    seed = spec["meta"]["seed"] if seed is None else seed
    p, pm, df = spec["period"], spec["price_model"], spec["defects"]
    hw, thin_cov = pm["daily_range"]["half_width"], df["thin_mandi_coverage"]
    days, trading = calendar(spec)
    n = len(days)
    iso = [d.isoformat() for d in days]
    # spec timing: knowable at 18:00 Asia/Karachi (fixed +05:00, no DST); late rows the next calendar day
    rep = [f"{s} 18:00+05:00" for s in iso]
    rep_late = [f"{d + timedelta(1)} 18:00+05:00" for d in days]
    years = np.array([(d - p["start"]).days for d in days]) / 365.25
    mpos = np.array([month_pos(d) for d in days])
    mandis = {m["id"]: m for m in spec["mandis"]}
    flag = {False: "0", True: "1"}
    rows = []
    for crop, c in spec["crops"].items():
        if c.get("frequency") == "monthly":
            continue  # wheat: wheat_monthly(), no mandi dimension
        dips = dip_sum(c["dips"], mpos)
        base = math.log(c["base_pkr100kg"])
        common = rng(seed, variant, crop, "common")
        if variant == "SYN":
            j = c["jumps"]
            r = rng(seed, variant, crop, "jumps")
            shocks = r.standard_normal(n) * j["size_sd"] * np.sqrt(r.poisson(j["per_year"] / 365.25, n))
            crop_log = (base + math.log1p(c["annual_trend"]) * years - dips
                        + stationary_ar1(common, c["ar1_common"]["phi"], c["ar1_common"]["sigma"], n)
                        + ar1(shocks, 0.5 ** (1 / j["half_life_days"]), shocks[0]))
            seasonal = dips  # arrivals rise when the seasonal price component falls
        else:  # SYN-NULL: pure random walk with the same shock sizes, no trend, dips or jumps
            crop_log = base + np.cumsum(common.standard_normal(n) * c["ar1_common"]["sigma"])
            seasonal = 0.0
        prod, a = mandis[c["producing_mandi"]], c["arrivals"]
        for mid, m in mandis.items():
            effect = (pm["distance_slope_per_100km"] * km(m, prod) / 100
                      + rng(seed, "mandi_effect", crop, mid).normal(0, pm["mandi_fixed_sd"]))
            r, sig = rng(seed, variant, crop, mid, "mandi"), c["ar1_mandi"]["sigma"]
            own = stationary_ar1(r, c["ar1_mandi"]["phi"], sig, n) if variant == "SYN" else np.cumsum(r.standard_normal(n) * sig)
            avg = np.exp(crop_log + own + effect)
            w = rng(seed, "range", crop, mid).uniform(hw["low"], hw["high"], n)
            noise = rng(seed, "arrivals", crop, mid).normal(0, a["noise_sd"], n)
            arrivals = a["base_tonne"] * np.exp(a["price_elasticity"] * seasonal + noise)

            # defect and timing streams leave out the variant, so SYN and SYN-NULL carry identical masks
            k = ("defect", crop, mid)
            keep = trading & (rng(seed, *k, "missing").random(n) >= df["missing_day_rate"])
            if m["thin"]:
                r = rng(seed, *k, "thin")
                cover = r.uniform(thin_cov["low"], thin_cov["high"])
                keep &= r.random(n) < cover
            r = rng(seed, *k, "typo")
            typo, up = r.random(n) < df["typo_10x_rate"], r.random(n) < 0.5
            swap = rng(seed, *k, "swap").random(n) < df["min_gt_max_rate"]
            per40 = rng(seed, *k, "per40").random(n) < df["per_40kg_unit_rate"]
            r = rng(seed, *k, "variant")
            var, pick = r.random(n) < df["name_variant_rate"], r.integers(0, len(m["variants"]), n)
            late = rng(seed, "timing", crop, mid).random(n) < spec["timing"]["late_publish_rate"]

            lo, hi = avg * (1 - w), avg * (1 + w)
            lo, hi = np.where(swap, hi, lo), np.where(swap, lo, hi)
            shown = np.where(typo, np.where(up, avg * 10, avg / 10), avg)  # typo hits the average only
            for t in np.flatnonzero(keep).tolist():
                p4 = bool(per40[t])
                rows.append({
                    "market_date": iso[t],
                    "crop_id": crop,
                    "mandi_raw": m["variants"][pick[t]] if var[t] else m["name_en"],
                    "unit_raw": "PKR/40kg" if p4 else "PKR/100kg",
                    "min_raw": money(lo[t], p4),
                    "max_raw": money(hi[t], p4),
                    "avg_raw": money(shown[t], p4),
                    "arrivals_qty": f"{arrivals[t]:.2f}",
                    "arrivals_unit": "tonne",
                    "reported_at": rep_late[t] if late[t] else rep[t],
                    "truth_mandi_id": mid,
                    "truth_typo10x": flag[bool(typo[t])],
                    "truth_swap": flag[bool(swap[t])],
                    "truth_per40": flag[p4],
                    "truth_variant": flag[bool(var[t])],
                    "truth_late": flag[bool(late[t])],
                })
    rows.sort(key=lambda r: (r["market_date"], r["crop_id"], r["truth_mandi_id"]))
    return rows


def wheat_monthly(spec: dict, seed: int | None = None) -> list[dict]:
    """One regional value per month (F3 panel). Separate file: price_obs needs a mandi (D-014). No defects."""
    seed = spec["meta"]["seed"] if seed is None else seed
    p, c = spec["period"], spec["crops"]["WHEAT"]
    months = sorted({d.replace(day=1) for d in calendar(spec)[0]})
    years = np.array([(d - p["start"]).days for d in months]) / 365.25
    ar = c["ar1_common"]
    log_p = (math.log(c["base_pkr100kg"]) + math.log1p(c["annual_trend"]) * years
             - dip_sum(c["dips"], np.array([month_pos(d) for d in months]))
             + stationary_ar1(rng(seed, "SYN", "WHEAT", "common"), ar["phi"], ar["sigma"], len(months)))
    region = p["wheat"]["region"]
    return [{"month": d.isoformat(), "crop_id": "WHEAT", "region": region, "avg_pkr100kg": f"{v:.2f}"}
            for d, v in zip(months, np.exp(log_p).tolist(), strict=True)]


def write_csv(rows: list[dict], path: Path) -> str:
    """UTF-8 without BOM, LF line ends, fixed column order; returns the sha256 of the file bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    spec = load_spec()
    ap = argparse.ArgumentParser(description="Generate the synthetic price files (task 3.2).")
    ap.add_argument("--seed", type=int, default=spec["meta"]["seed"])
    ap.add_argument("--variant", choices=list(FILES), help="only this variant (default: both + wheat)")
    ap.add_argument("--out", type=Path, default=SPEC_PATH.parent)
    a = ap.parse_args(argv)
    for v in [a.variant] if a.variant else FILES:
        print(f"{FILES[v]} sha256 {write_csv(generate(spec, v, a.seed), a.out / FILES[v])}")
    if not a.variant:
        print(f"wheat_monthly.csv sha256 {write_csv(wheat_monthly(spec, a.seed), a.out / 'wheat_monthly.csv')}")


if __name__ == "__main__":
    main()
