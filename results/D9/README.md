# D9 baseline: rule-based parser (task 7.1)

Scored by `scripts/score_parser.py` on the committed benchmark (40 text + 30 voice, voice input = `gold_transcript.roman`), `now` = 2026-12-11. This is the D9 baseline (file 11): no threshold must pass; the file 05 §5 thresholds are shown for reference. Per-item results in `parser_items.csv`. Choices: D-031.

| Metric (file 05 §5) | Value | Threshold |
|---|---|---|
| intent accuracy (text) | 100.0% | >= 95% |
| intent accuracy (all) | 100.0% | - |
| critical-slot exact match (text) | 100.0% | >= 95% |
| critical-slot exact match (voice) | 96.7% | >= 90% |
| clarification asked on AMB | 100.0% | >= 90% |
| unnecessary clarifications on clear items | 0.0% | <= 10% |
| out-of-scope requests redirected | 100.0% | 100% |
| correct tool | 100.0% | >= 95% |

Items with at least one field miss (1): V30.
See D-031 for the known misses and the rules chosen where SPEC does not fix them.

