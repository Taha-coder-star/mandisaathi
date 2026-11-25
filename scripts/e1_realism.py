"""Realism check E1 (task 5.3; file 03 §6 + §9, file 11; DECISIONS.md D-024).

  python -m scripts.e1_realism [--out results/E1]      (needs the `report` extra for charts: pip install -e .[report])

Generates SYN and SYN-NULL in memory from spec.yaml, keeps only the development period (before the holdout year:
nobody looks at that year), and writes results/E1/README.md (tables) + 4 charts. Exit code 1 if QC misses any
injected typo, min>max swap or per-40 kg unit row (the 5.3 DONE condition).
"""
import argparse
import math
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from mandi.ingest import qc
from mandi.ingest.loader import TO_PER_100KG
from scripts.make_synthetic import calendar, dip_sum, generate, load_spec, month_pos

LABEL = "Demo data (synthetic)"
MANN = 2.5  # per-100 kg value / 2.5 = per-mann (40 kg) value
FLOORS = [0.02, 0.03, 0.04, 0.05]


def canon(rows: list[dict], ignore_units: bool = False) -> list[dict]:
    """The loader's unit conversion (to_price_row) on generator rows; ignore_units = a silent unit error."""
    out = []
    for r in rows:
        f = 1.0 if ignore_units else float(TO_PER_100KG[r["unit_raw"]])
        out.append({"crop_id": r["crop_id"], "mandi_id": r["truth_mandi_id"], "market_date": date.fromisoformat(r["market_date"]),
                    **{f"{k}_pkr100kg": float(r[f"{k}_raw"]) * f for k in ("min", "max", "avg")}})
    return out


def table(head: list[str], body: list[list]) -> str:
    lines = [head, ["---"] * len(head)] + [list(map(str, r)) for r in body]
    return "\n".join("| " + " | ".join(r) + " |" for r in lines)


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.2f}%" if b else "n/a"


def qc_section(variant: str, rows: list[dict]) -> tuple[list[list], bool, list[set[str]]]:
    flags = qc.flag(canon(rows))
    out, ok = [], True
    for name, key in [("10x typo", "truth_typo10x"), ("min > max swap", "truth_swap")]:
        idx = [i for i, r in enumerate(rows) if r[key] == "1"]
        hit = sum(1 for i in idx if flags[i])
        ok &= hit == len(idx)
        out.append([variant, name, len(idx), hit, pct(hit, len(idx))])
    # per-40 kg rows count as caught when the loader recognises the unit and converts it (value then lands in range)
    p40 = [i for i, r in enumerate(rows) if r["truth_per40"] == "1"]
    conv = sum(1 for i in p40 if TO_PER_100KG[rows[i]["unit_raw"]] != 1)
    ok &= conv == len(p40)
    out.append([variant, "per-40 kg unit (converted by loader)", len(p40), conv, pct(conv, len(p40))])
    silent = qc.flag(canon(rows, ignore_units=True))
    hit = sum(1 for i in p40 if silent[i])
    out.append([variant, "per-40 kg read as per-100 kg (stress, not injected)", len(p40), hit, pct(hit, len(p40))])
    clean = [i for i, r in enumerate(rows) if r["truth_typo10x"] == r["truth_swap"] == "0"]
    fp = sum(1 for i in clean if flags[i])
    out.append([variant, "clean rows flagged (false positives)", len(clean), fp, pct(fp, len(clean))])
    return out, ok, flags


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("results/E1"))
    a = ap.parse_args(argv)
    spec = load_spec()
    dev_end = spec["period"]["holdout"]["start"]  # first holdout day; everything here is strictly before it
    crops = {k: c for k, c in spec["crops"].items() if c.get("frequency") != "monthly"}
    mandis = {m["id"]: m for m in spec["mandis"]}
    syn = [r for r in generate(spec, "SYN") if r["market_date"] < dev_end.isoformat()]
    null = [r for r in generate(spec, "SYN-NULL") if r["market_date"] < dev_end.isoformat()]

    # 1. QC recall
    qc_rows, ok_syn, flags = qc_section("SYN", syn)
    qc_null, ok_null, _ = qc_section("SYN-NULL", null)
    ok = ok_syn and ok_null
    rows = canon(syn)
    inj = [r["truth_typo10x"] == "1" or r["truth_swap"] == "1" for r in syn]
    sweep, keep_floor = [], qc.SD_FLOOR
    for fl in FLOORS:
        qc.SD_FLOOR = fl
        f = qc.flag(rows)
        fp = Counter(r["crop_id"] for r, x, i in zip(rows, f, inj, strict=True) if x and not i)
        n = Counter(r["crop_id"] for r, i in zip(rows, inj, strict=True) if not i)
        miss = sum(1 for x, i in zip(f, inj, strict=True) if i and not x)
        sweep.append([fl, sum(inj) - miss, sum(inj)] + [pct(fp[c], n[c]) for c in crops] + ["**chosen**" if fl == keep_floor else ""])
    qc.SD_FLOOR = keep_floor

    clean = [r for r, x in zip(rows, flags, strict=True) if not x]  # what the price service would serve

    # 2. Levels vs plausibility (per mann)
    pl = spec["plausibility"]
    by_year, by_month = defaultdict(list), defaultdict(list)
    for r in clean:
        by_year[(r["crop_id"], r["market_date"].year)].append(r["avg_pkr100kg"] / MANN)
        by_month[(r["crop_id"], r["market_date"].year, r["market_date"].month)].append(r["avg_pkr100kg"] / MANN)
    years = sorted({y for _, y in by_year})
    level_rows, level_plot = [], defaultdict(list)
    for c in crops:
        an, g = pl["anchors"][c], 1 + spec["crops"][c]["annual_trend"]
        for y in years:
            v = np.array(by_year[(c, y)])
            lo, hi = an["low"] * g ** (y - pl["anchor_year"]), an["high"] * g ** (y - pl["anchor_year"])
            med, p10, p90 = np.median(v), np.percentile(v, 10), np.percentile(v, 90)
            months = [np.median(by_month[(c, y, m)]) for m in range(1, 13) if by_month[(c, y, m)]]
            inside = sum(lo <= x <= hi for x in months)
            level_rows.append([c, y, f"{med:,.0f}", f"{p10:,.0f}", f"{p90:,.0f}", f"{lo:,.0f}", f"{hi:,.0f}",
                               "yes" if lo <= med <= hi else ("below" if med < lo else "ABOVE"), f"{inside}/{len(months)}"])
            level_plot[c].append((y, med, p10, p90, lo, hi))

    # 3. Seasonal shape: detrended log price, de-meaned per (mandi, year), averaged by month; spec curve the same way
    start = spec["period"]["start"]
    season_rows, season_plot = [], {}
    for c in crops:
        tr = math.log1p(spec["crops"][c]["annual_trend"])
        res = defaultdict(list)
        for r in clean:
            if r["crop_id"] == c:
                d = r["market_date"]
                res[(r["mandi_id"], d.year)].append((d.month, math.log(r["avg_pkr100kg"]) - tr * (d - start).days / 365.25))
        acc = defaultdict(list)
        for pts in res.values():
            m0 = np.mean([v for _, v in pts])
            for mo, v in pts:
                acc[mo].append(v - m0)
        obs = np.array([np.mean(acc[m]) for m in range(1, 13)])
        sp = -dip_sum(spec["crops"][c]["dips"], np.array([month_pos(date(2021, m, 15)) for m in range(1, 13)]))
        sp = sp - sp.mean()
        obs = obs - obs.mean()
        season_plot[c] = (obs, sp)
        season_rows.append([c, int(np.argmin(obs)) + 1, int(np.argmin(sp)) + 1,
                            f"{100 * (math.exp(obs.max() - obs.min()) - 1):.0f}%", f"{100 * (math.exp(sp.max() - sp.min()) - 1):.0f}%",
                            f"{np.corrcoef(obs, sp)[0, 1]:.2f}"])

    # 4. Gaps and thin series: eligibility window = last 12 months of the development period (file 03 §6)
    days, trading = calendar(spec)
    tdays = [d for d, t in zip(days, trading, strict=True) if t and d < dev_end]
    win = [d for d in tdays if d >= dev_end - timedelta(365)]
    have = defaultdict(set)
    for r in syn:
        have[(r["crop_id"], r["truth_mandi_id"])].add(date.fromisoformat(r["market_date"]))
    cov_rows, eligible = [], Counter()
    for mid, m in mandis.items():
        row = [m["name_en"], "yes" if m["thin"] else ""]
        for c in crops:
            got = have[(c, mid)]
            cv = sum(d in got for d in win) / len(win)
            gap = run = 0
            for d in tdays:
                run = 0 if d in got else run + 1
                gap = max(gap, run)
            eligible[c] += cv >= 0.6
            row += [f"{100 * cv:.0f}%" + ("" if cv >= 0.6 else " (gate)"), gap]
        cov_rows.append(row)
    yrs = sorted({d.year for d in tdays})
    per_year = {y: [d for d in tdays if d.year == y] for y in yrs}
    heat = np.array([[np.mean([sum(d in have[(c, mid)] for d in per_year[y]) / len(per_year[y]) for c in crops]) for y in yrs]
                     for mid in mandis])

    charts(a.out, crops, mandis, level_plot, season_plot, heat, yrs, syn, flags)

    first_holdout = dev_end.isoformat()
    above = [f"{r[0]} {r[1]}" for r in level_rows if r[7] == "ABOVE"]
    below = Counter(r[0] for r in level_rows if r[7] == "below")
    md = [f"# E1 realism check v0: {LABEL}", "",
          f"Task 5.3 (file 11). Spec v{spec['meta']['spec_version']}, seed {spec['meta']['seed']}, "
          "SYN and SYN-NULL generated in memory by `scripts/make_synthetic.py`. "
          f"Development period {spec['period']['start']} to the day before {first_holdout}; "
          "the holdout year is not read. Regenerate: `python -m scripts.e1_realism`.",
          f"No claim about real-market accuracy: this compares the generator with its own spec and the spec's plausibility "
          f"envelopes. Every number below is {LABEL}.", "",
          "## 1. QC recall on injected defects (DONE condition: 100%)", "",
          f"Rules (file 03 §6, D-024): min > max; more than {qc.K_ROBUST_SD:g} robust SD (floor {qc.SD_FLOOR} log) from the "
          f"trailing {qc.WINDOW_DAYS}-day median; at least {qc.NEIGHBOUR_RATIO:g}x or at most 1/{qc.NEIGHBOUR_RATIO:g} of the "
          "median of the same crop's other mandis that day.", "",
          table(["variant", "defect", "injected", "caught", "recall"], qc_rows + qc_null), "",
          f"Result: **{'PASS' if ok else 'FAIL'}**. False positives are mostly real supply jumps (spec `jumps`); a SUSPECT row is "
          "held back only until the next day confirms it (file 03 §6).", "",
          "Robust-SD floor sweep on SYN (the floor is the only threshold E1 tunes; recall does not depend on it):", "",
          table(["SD floor", "caught", "injected"] + [f"FP {c}" for c in crops] + [""], sweep), "",
          "## 2. Price levels vs plausibility envelope (PKR per mann, QC-clean rows, all mandis)", "",
          "Envelope = spec `plausibility` anchor (Lahore 2025 retail, an upper-side reference) moved by the crop's trend. "
          "Wholesale should sit at or below `env high`. Early-year envelopes are deflated, not sourced (spec: UNVERIFIED).", "",
          table(["crop", "year", "median", "p10", "p90", "env low", "env high", "median inside", "months inside"], level_rows), "",
          f"Finding: yearly medians above `env high`: {', '.join(above) or 'none'}. Below `env low`: "
          f"{', '.join(f'{c} {n}/{len(years)} years' for c, n in below.items()) or 'none'}; expected for wholesale against a "
          "retail anchor, but the low edge (or the crop base level) is for the 9.2 review before the G2 freeze.", "",
          "Chart: `e1_levels.png`.", "",
          "## 3. Seasonal shape per crop", "",
          "Observed = mean of detrended log price by calendar month (each mandi-year de-meaned); spec = the spec `dips` curve.",
          "", table(["crop", "trough month (obs)", "trough month (spec)", "peak-to-trough (obs)", "peak-to-trough (spec)", "corr"],
                    season_rows), "", "Chart: `e1_seasonal.png`.", "",
          f"## 4. Gaps and thin series (coverage of trading days {win[0]} to {win[-1]})", "",
          "`(gate)` = below the 60% coverage gate, so not eligible for F1/F2. Max gap = longest run of missing trading days "
          "over the whole development period. The recent-quote rule (last 3 trading days) is checked by the price service (8.2).", "",
          table(["mandi", "thin in spec"] + [h for c in crops for h in (f"{c} cov", f"{c} max gap")], cov_rows), "",
          "Eligible mandis per crop: " + ", ".join(f"{c} {eligible[c]}" for c in crops) + " (demo needs >= 5, file 10 §4).", "",
          "Chart: `e1_coverage.png` (mean coverage of the 3 crops per mandi and year).", "",
          "## 5. QC example", "",
          "Chart: `e1_qc.png`: the series with the most injected typos, one year, injected defects vs flags.", ""]
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "README.md").write_text("\n".join(md), encoding="utf-8", newline="\n")
    print(f"E1 written to {a.out}; QC recall {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def charts(out: Path, crops, mandis, level_plot, season_plot, heat, yrs, syn, flags) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out.mkdir(parents=True, exist_ok=True)

    fig, axs = plt.subplots(1, len(crops), figsize=(15, 4.2))
    for ax, c in zip(axs, crops, strict=True):
        y, med, p10, p90, lo, hi = map(np.array, zip(*level_plot[c], strict=True))
        ax.fill_between(y, lo, hi, color="tab:green", alpha=0.15, label="plausibility envelope")
        ax.fill_between(y, p10, p90, color="tab:blue", alpha=0.25, label="p10-p90")
        ax.plot(y, med, "o-", color="tab:blue", label="median")
        ax.set_title(c.title())
        ax.set_xlabel("year")
        ax.set_ylabel("PKR per mann (40 kg)")
    axs[0].legend(fontsize=8)
    fig.suptitle(f"E1 price levels vs plausibility envelope: {LABEL}")
    fig.tight_layout()
    fig.savefig(out / "e1_levels.png", dpi=110)
    plt.close(fig)

    fig, axs = plt.subplots(1, len(crops), figsize=(15, 4.2), sharey=True)
    for ax, c in zip(axs, crops, strict=True):
        obs, sp = season_plot[c]
        ax.plot(range(1, 13), 100 * obs, "o-", label="observed")
        ax.plot(range(1, 13), 100 * sp, "--", color="k", label="spec dips")
        ax.set_title(c.title())
        ax.set_xticks(range(1, 13))
        ax.set_xlabel("month")
    axs[0].set_ylabel("log price vs annual mean (x100)")
    axs[0].legend(fontsize=8)
    fig.suptitle(f"E1 seasonal shape per crop: {LABEL}")
    fig.tight_layout()
    fig.savefig(out / "e1_seasonal.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(100 * heat, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(yrs)), yrs)
    ax.set_yticks(range(len(mandis)), [m["name_en"] + (" (thin)" if m["thin"] else "") for m in mandis.values()])
    for i in range(heat.shape[0]):
        for j in range(heat.shape[1]):
            ax.text(j, i, f"{100 * heat[i, j]:.0f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, label="% of trading days with a quote (mean of 3 crops); gate = 60%")
    ax.set_title(f"E1 coverage per mandi and year: {LABEL}")
    fig.tight_layout()
    fig.savefig(out / "e1_coverage.png", dpi=110)
    plt.close(fig)

    typos = Counter((r["crop_id"], r["truth_mandi_id"], r["market_date"][:4]) for r in syn if r["truth_typo10x"] == "1")
    (c, mid, yr), _ = max(typos.items(), key=lambda kv: (kv[1], kv[0]))
    idx = [i for i, r in enumerate(syn) if (r["crop_id"], r["truth_mandi_id"], r["market_date"][:4]) == (c, mid, yr)]
    d = [date.fromisoformat(syn[i]["market_date"]) for i in idx]
    v = [float(syn[i]["avg_raw"]) * float(TO_PER_100KG[syn[i]["unit_raw"]]) / MANN for i in idx]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(d, v, ".-", color="tab:gray", lw=0.6, ms=3, label="avg as loaded (per mann)")
    marks = [("truth_typo10x", "x", "tab:red", "injected 10x typo"), ("truth_swap", "+", "tab:purple", "injected min>max"),
             ("truth_per40", "^", "tab:orange", "per-40 kg row (converted)")]
    for key, mk, col, label in marks:
        pts = [(d[n], v[n]) for n, i in enumerate(idx) if syn[i][key] == "1"]
        if pts:
            ax.scatter(*zip(*pts, strict=True), marker=mk, s=60, color=col, zorder=3, label=label)
    fl = [(d[n], v[n]) for n, i in enumerate(idx) if flags[i]]
    if fl:
        ax.scatter(*zip(*fl, strict=True), s=140, facecolors="none", edgecolors="k", zorder=4, label="QC SUSPECT")
    ax.set_yscale("log")
    ax.set_ylabel("PKR per mann (log scale)")
    ax.set_title(f"E1 QC example: {c.title()}, {mandis[mid]['name_en']}, {yr}: {LABEL}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "e1_qc.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
