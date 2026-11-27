"""Score the rule-based parser (task 7.1) on the committed benchmark -> the D9 baseline (file 11 DONE condition).

    python scripts/score_parser.py

Runs mandi.parse.parse() on every text item (40) and every voice item (30, using gold_transcript.roman as input);
together these are "the benchmark texts committed so far". Writes:
  results/D9/parser_items.csv   one row per item (id, each field ok/miss, parsed vs gold)
  results/D9/README.md          the file 05 §5 metrics, each reported against its threshold (baseline: no pass required)

Pure: no DB, no network. now is pinned to the S-DEMO reference 2026-12-11 so MONTH horizons match gold (D-025).
"""
import csv
import json
from datetime import date
from pathlib import Path

from mandi.parse import parse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "D9"
NOW = date(2026, 12, 11)  # S-DEMO reference; April -> 2027-04, February -> 2027-02 (SPEC §2.5, D-025)

FIELDS = ["intent", "crop", "place", "quantity", "horizon", "tool", "outcome", "clarify_slot"]


def _items():
    for name, key in (("text.jsonl", "input"), ("voice.jsonl", "gold_transcript")):
        for line in (ROOT / "data/benchmark" / name).read_text(encoding="utf-8").splitlines():
            it = json.loads(line)
            text = it["input"] if key == "input" else it["gold_transcript"]["roman"]
            yield it["id"], it["set"], text, it["gold"]


def _crop_cmp(got, gold):
    """Critical crop slot = crop.id (a list of ids when two crops)."""
    def ids(c):
        return [x["id"] for x in c] if isinstance(c, list) else ([c["id"]] if c else [])
    return ids(got) == ids(gold)


def _place_cmp(got, gold):
    """Critical place slot = status + canonical."""
    def sc(p):
        return (p["status"], p["canonical"]) if p else (None, None)
    return sc(got) == sc(gold)


def _quantity_cmp(got, gold):
    """Critical quantity slot = value_kg + unit."""
    def vu(q):
        return (q["value_kg"], q["unit"]) if q else (None, None)
    return vu(got) == vu(gold)


def _field_ok(field, parsed, gold):
    if field == "crop":
        return _crop_cmp(parsed["slots"]["crop"], gold["slots"]["crop"])
    if field == "place":
        return _place_cmp(parsed["slots"]["place"], gold["slots"]["place"])
    if field == "quantity":
        return _quantity_cmp(parsed["slots"]["quantity"], gold["slots"]["quantity"])
    if field == "horizon":
        return parsed["slots"]["horizon"] == gold["slots"]["horizon"]
    return parsed.get(field) == gold.get(field)


def score():
    rows, parsed_by_id = [], {}
    for item_id, item_set, text, gold in _items():
        parsed = parse(text, NOW)
        parsed_by_id[item_id] = (item_set, text, parsed, gold)
        row = {"id": item_id, "set": item_set, "input": text}
        row |= {f: ("ok" if _field_ok(f, parsed, gold) else "MISS") for f in FIELDS}
        row["crit_ok"] = "ok" if all(row[f] == "ok" for f in ("crop", "place", "quantity")) else "MISS"
        row["parsed"] = json.dumps(parsed, ensure_ascii=False)
        row["gold"] = json.dumps(gold, ensure_ascii=False)
        rows.append(row)
    return rows, parsed_by_id


def _pct(num, den):
    return 100.0 * num / den if den else float("nan")


def metrics(rows, parsed_by_id):
    text = [r for r in rows if r["set"] == "text"]
    voice = [r for r in rows if r["set"] == "voice"]

    def crit(rs):
        return _pct(sum(r["crit_ok"] == "ok" for r in rs), len(rs))

    amb = [r for r in rows if r["id"].startswith(("T-AMB", "V28", "V29", "V30")) and parsed_by_id[r["id"]][3]["outcome"] == "CLARIFY"]
    amb_ok = sum(parsed_by_id[r["id"]][2]["outcome"] == "CLARIFY"
                 and parsed_by_id[r["id"]][2]["clarify_slot"] == parsed_by_id[r["id"]][3]["clarify_slot"] for r in amb)
    clear = [r for r in rows if parsed_by_id[r["id"]][3]["outcome"] != "CLARIFY"]
    unneeded = sum(parsed_by_id[r["id"]][2]["outcome"] == "CLARIFY" for r in clear)
    oos = [r for r in rows if r["id"].startswith("T-OOS")]
    oos_ok = sum(r["outcome"] == "ok" for r in oos)
    answer = [r for r in rows if parsed_by_id[r["id"]][3]["outcome"] == "ANSWER"]
    tool_ok = sum(r["tool"] == "ok" for r in answer)

    return {
        "intent accuracy (text)": (_pct(sum(r["intent"] == "ok" for r in text), len(text)), ">= 95%"),
        "intent accuracy (all)": (_pct(sum(r["intent"] == "ok" for r in rows), len(rows)), "-"),
        "critical-slot exact match (text)": (crit(text), ">= 95%"),
        "critical-slot exact match (voice)": (crit(voice), ">= 90%"),
        "clarification asked on AMB": (_pct(amb_ok, len(amb)), ">= 90%"),
        "unnecessary clarifications on clear items": (_pct(unneeded, len(clear)), "<= 10%"),
        "out-of-scope requests redirected": (_pct(oos_ok, len(oos)), "100%"),
        "correct tool": (_pct(tool_ok, len(answer)), ">= 95%"),
    }


def write(rows, mx):
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["id", "set", *FIELDS, "crit_ok", "input", "parsed", "gold"]
    with (OUT / "parser_items.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")  # LF, so a Linux CI re-run matches
        w.writeheader()
        w.writerows(rows)

    misses = [r["id"] for r in rows if any(r[f] == "MISS" for f in FIELDS)]
    lines = [
        "# D9 baseline: rule-based parser (task 7.1)",
        "",
        "Scored by `scripts/score_parser.py` on the committed benchmark (40 text + 30 voice, voice input = "
        "`gold_transcript.roman`), `now` = 2026-12-11. This is the D9 baseline (file 11): no threshold must pass; "
        "the file 05 §5 thresholds are shown for reference. Per-item results in `parser_items.csv`. Choices: D-031.",
        "",
        "| Metric (file 05 §5) | Value | Threshold |",
        "|---|---|---|",
    ]
    lines += [f"| {k} | {v:.1f}% | {thr} |" for k, (v, thr) in mx.items()]
    lines += [
        "",
        f"Items with at least one field miss ({len(misses)}): " + (", ".join(misses) if misses else "none") + ".",
        "See D-031 for the known misses and the rules chosen where SPEC does not fix them.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    rows, parsed_by_id = score()
    mx = metrics(rows, parsed_by_id)
    write(rows, mx)
    for k, (v, thr) in mx.items():
        print(f"{k:45s} {v:6.1f}%   ({thr})")
    misses = [r["id"] for r in rows if any(r[f] == "MISS" for f in FIELDS)]
    print(f"\nitems with a field miss ({len(misses)}): {', '.join(misses) if misses else 'none'}")


if __name__ == "__main__":
    main()
