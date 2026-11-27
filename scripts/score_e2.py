"""E2: F1 baselines B-N, B-SN, B-SR on the development folds (task 7.3; file 04 §1.1-1.4, file 11; DECISIONS.md D-033).

  python -m scripts.score_e2 [--out results]          (also the `make results` recipe)

Generates SYN and SYN-NULL in memory from spec.yaml + seed, keeps only the development period (the holdout year is
never generated into the scored rows: devdata cuts it first), scores each baseline per variant x crop (and ALL) x h with
the shared folds of params/ps_v1.yaml, and writes results/E2.csv + results/E2.md. Output is byte-identical on rerun
(fixed order, %.6g floats, LF). Exit code 1 if the pre-registered SYN-NULL sanity rule fails.
"""
import argparse
import sys
from pathlib import Path

from mandi.features import fs_s
from mandi.models import devdata, f1eval
from scripts.make_synthetic import generate, load_spec

LABEL = "Demo data (synthetic)"
VARIANTS = ("SYN", "SYN-NULL")
FIELDS = ["variant", "crop", "h", "baseline", *f1eval.METRICS, "sn_exact", "sn_older", "sn_last"]


def fmt(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return "nan" if v != v else f"{v:.6g}"


def to_csv(table: list[dict]) -> str:
    lines = [",".join(FIELDS)] + [",".join(fmt(r[f]) for f in FIELDS) for r in table]
    return "\n".join(lines) + "\n"


def score(spec: dict, cfg: dict, variants=VARIANTS, crops=devdata.DAILY_CROPS) -> list[dict]:
    end, events = devdata.dev_end(spec), fs_s.spec_events(spec)
    table = []
    for v in variants:
        rows = devdata.price_rows(generate(spec, v), end, crops)
        table += [{"variant": v, **r} for r in f1eval.score_rows(rows, end, events, cfg, crops)]
    return table


def md_table(head: list[str], body: list[list]) -> str:
    rows = ["| " + " | ".join(map(str, r)) + " |" for r in body]
    return "\n".join(["| " + " | ".join(head) + " |", "|" + " --- |" * len(head), *rows])


def readme(table: list[dict], cfg: dict, spec: dict, fails: list[dict]) -> str:
    hs = cfg["horizons"]
    f = cfg["folds"]
    out = [f"# E2: F1 baselines on development folds: {LABEL}", "",
           f"Task 7.3 (file 11). **{LABEL}.** Pre-freeze development-fold numbers (file 11 §8 risk 4): regenerated after the "
           "`ps_v1` tag (G2) with `make results` (= `python -m scripts.score_e2`). No claim about real-market accuracy.", "",
           f"Spec seed {spec['meta']['seed']}; SYN and SYN-NULL generated in memory; development period to {devdata.dev_end(spec)} "
           "(the holdout year is cut before QC, features and folds). "
           f"Folds (params/ps_v1.yaml `f1_eval`, D-033): {f['n_folds']} expanding-window folds from {f['first_test']}, test "
           f"{f['test_months']} months, step {f['step_months']}, embargo = h days. MASE = MAE of q50 / MAE of B-N on the same "
           "test rows (D-016), 95% circular block-bootstrap CI over days (block 10, 2000 resamples, seed 0).", "",
           "Baselines (file 04 §1.2): **B-N** q50 = M(t-1). **B-SN** q50 = M(t+h-8), the target's weekday one week earlier as "
           "known at t (newest earlier known quote if missing, else M(t-1)); **at h = 7 that day is t-1, so B-SN equals B-N by "
           "definition (MASE exactly 1), not a finding.** **B-SR** q50 = M(t-1) x exp(-spread_region/2), halfway in logs to "
           "the crop's median over all mandis, same for every h. Ranges: training-row quantiles of log(y/q50).", "",
           "Full table (variant x crop x h x baseline, all file 04 §1.4 metrics): `results/E2.csv`.", ""]
    for v in VARIANTS:
        rows = [r for r in table if r["variant"] == v]
        out += [f"## {v}: pooled MASE [95% CI] by crop x h", ""]
        body = []
        for crop in [*devdata.DAILY_CROPS, f1eval.ALL]:
            for b in ("B-SN", "B-SR"):
                cells = {r["h"]: r for r in rows if r["crop"] == crop and r["baseline"] == b}
                body.append([crop, b] + [f"{cells[h]['mase']:.4f} [{cells[h]['mase_lo']:.4f}, {cells[h]['mase_hi']:.4f}]" for h in hs])
        out += [md_table(["crop", "baseline", *[f"h={h}" for h in hs]], body), "",
                "B-N is 1 by construction in every cell. Coverage of the 80% range (ALL crops), B-N / B-SN / B-SR:", ""]
        cov = []
        for h in hs:
            c = {r["baseline"]: r for r in rows if r["crop"] == f1eval.ALL and r["h"] == h}
            cov.append([h] + [f"{c[b]['coverage']:.3f}" for b in ("B-N", "B-SN", "B-SR")] + [c["B-N"]["n"]])
        out += [md_table(["h", "B-N", "B-SN", "B-SR", "test rows"], cov), ""]
    null = [r for r in table if r["variant"] == "SYN-NULL"]
    out += ["## Reading the numbers", "",
            "- B-N is the bar: neither other baseline beats it on any crop or horizon, on SYN or SYN-NULL. E3 (11.1) must beat "
            "B-N, not these.",
            "- B-SN loses most at h = 1 (it uses a quote up to a week older than M(t-1)) and converges to B-N as h -> 7.",
            "- B-SR pulls every mandi halfway to the crop median, but the generator gives each mandi a fixed premium (spec "
            "`mandi_effect`), so the median is not where prices go back to. On SYN-NULL each mandi also has its own random "
            "walk (D-014), so spreads drift apart over the years and halving them costs most (MASE about 6-16).",
            "- B-SR ranges come from training residuals; on SYN-NULL the spreads keep growing after training, so coverage "
            "falls to about 64%.", ""]
    out += ["## Sanity rule (pre-registered, D-033)", "",
            f"Rule: on SYN-NULL {cfg['sanity']['rule']}. Checked {len(null)} rows: "
            + ("**PASS**." if not fails else f"**FAIL** in {len(fails)} rows; leakage/bug hunt before any number is used."), ""]
    sn = [[r["h"], f"{r['sn_exact']:.3f}", f"{r['sn_older']:.3f}", f"{r['sn_last']:.3f}"]
          for r in table if r["variant"] == "SYN" and r["crop"] == f1eval.ALL and r["baseline"] == "B-SN"]
    out += ["## B-SN input used (SYN, ALL crops, test rows)", "",
            md_table(["h", "exact day t+h-8", "older known quote", "fell back to M(t-1)"], sn), ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("results"))
    a = ap.parse_args(argv)
    spec, cfg = load_spec(), f1eval.load_config()
    table = score(spec, cfg)
    fails = f1eval.sanity_failures([r for r in table if r["variant"] == cfg["sanity"]["variant"]])
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "E2.csv").write_bytes(to_csv(table).encode("utf-8"))
    (a.out / "E2.md").write_bytes(readme(table, cfg, spec, fails).encode("utf-8"))
    print(f"wrote {a.out / 'E2.csv'} ({len(table)} rows) and E2.md; sanity {'PASS' if not fails else 'FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
