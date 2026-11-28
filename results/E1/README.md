# E1 realism check (final): Demo data (synthetic)

Task 5.3 (v0), final at task 9.2 (file 11). Spec v1, seed 20261124, SYN and SYN-NULL generated in memory by `scripts/make_synthetic.py`. Development period 2016-01-01 to the day before 2025-12-19; the holdout year is not read. Regenerate: `python -m scripts.e1_realism`.
No claim about real-market accuracy: this compares the generator with its own spec and the spec's plausibility envelopes. Every number below is Demo data (synthetic).

## 1. QC recall on injected defects (DONE condition: 100%)

Rules (file 03 §6, D-024): min > max; more than 4 robust SD (floor 0.05 log) from the trailing 28-day median; at least 5x or at most 1/5 of the median of the same crop's other mandis that day.

| variant | defect | injected | caught | recall |
| --- | --- | --- | --- | --- |
| SYN | 10x typo | 343 | 343 | 100.00% |
| SYN | min > max swap | 222 | 222 | 100.00% |
| SYN | per-40 kg unit (converted by loader) | 6007 | 6007 | 100.00% |
| SYN | per-40 kg read as per-100 kg (stress, not injected) | 6007 | 5984 | 99.62% |
| SYN | clean rows flagged (false positives) | 117737 | 547 | 0.46% |
| SYN-NULL | 10x typo | 343 | 343 | 100.00% |
| SYN-NULL | min > max swap | 222 | 222 | 100.00% |
| SYN-NULL | per-40 kg unit (converted by loader) | 6007 | 6007 | 100.00% |
| SYN-NULL | per-40 kg read as per-100 kg (stress, not injected) | 6007 | 5990 | 99.72% |
| SYN-NULL | clean rows flagged (false positives) | 117737 | 1314 | 1.12% |

Result: **PASS**. False positives are mostly real supply jumps (spec `jumps`); a SUSPECT row is held back only until the next day confirms it (file 03 §6).

Robust-SD floor sweep on SYN (the floor is the only threshold E1 tunes; recall does not depend on it):

| SD floor | caught | injected | FP ONION | FP TOMATO | FP POTATO |  |
| --- | --- | --- | --- | --- | --- | --- |
| 0.02 | 563 | 563 | 2.07% | 3.14% | 2.18% |  |
| 0.03 | 563 | 563 | 0.92% | 1.91% | 1.32% |  |
| 0.04 | 563 | 563 | 0.56% | 1.01% | 0.91% |  |
| 0.05 | 563 | 563 | 0.28% | 0.72% | 0.40% | **chosen** |

## 2. Price levels vs plausibility envelope (PKR per mann, QC-clean rows, all mandis)

Envelope = spec `plausibility` anchor (Lahore 2025 retail, an upper-side reference) moved by the crop's trend. Wholesale should sit at or below `env high`. Early-year envelopes are deflated, not sourced (spec: UNVERIFIED).

| crop | year | median | p10 | p90 | env low | env high | median inside | months inside |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ONION | 2016 | 1,399 | 1,223 | 1,616 | 1,197 | 1,842 | yes | 12/12 |
| ONION | 2017 | 1,499 | 1,246 | 1,663 | 1,305 | 2,007 | yes | 9/12 |
| ONION | 2018 | 1,674 | 1,382 | 1,907 | 1,422 | 2,188 | yes | 9/12 |
| ONION | 2019 | 1,816 | 1,576 | 2,088 | 1,550 | 2,385 | yes | 12/12 |
| ONION | 2020 | 2,004 | 1,710 | 2,216 | 1,690 | 2,600 | yes | 11/12 |
| ONION | 2021 | 2,112 | 1,748 | 2,415 | 1,842 | 2,834 | yes | 9/12 |
| ONION | 2022 | 2,319 | 2,030 | 2,671 | 2,008 | 3,089 | yes | 12/12 |
| ONION | 2023 | 2,544 | 2,165 | 2,801 | 2,188 | 3,367 | yes | 11/12 |
| ONION | 2024 | 2,819 | 2,401 | 3,097 | 2,385 | 3,670 | yes | 11/12 |
| ONION | 2025 | 2,946 | 2,547 | 3,273 | 2,600 | 4,000 | yes | 10/12 |
| TOMATO | 2016 | 1,997 | 1,660 | 2,309 | 2,026 | 3,683 | below | 6/12 |
| TOMATO | 2017 | 2,217 | 1,896 | 2,549 | 2,208 | 4,015 | yes | 7/12 |
| TOMATO | 2018 | 2,346 | 2,038 | 2,677 | 2,407 | 4,376 | below | 5/12 |
| TOMATO | 2019 | 2,672 | 2,266 | 3,019 | 2,624 | 4,770 | yes | 8/12 |
| TOMATO | 2020 | 2,822 | 2,348 | 3,126 | 2,860 | 5,199 | below | 5/12 |
| TOMATO | 2021 | 3,070 | 2,667 | 3,470 | 3,117 | 5,667 | below | 6/12 |
| TOMATO | 2022 | 3,294 | 2,753 | 3,612 | 3,398 | 6,177 | below | 4/12 |
| TOMATO | 2023 | 3,517 | 3,048 | 3,968 | 3,703 | 6,733 | below | 3/12 |
| TOMATO | 2024 | 4,205 | 3,566 | 4,758 | 4,037 | 7,339 | yes | 9/12 |
| TOMATO | 2025 | 4,349 | 3,695 | 4,924 | 4,400 | 8,000 | below | 6/12 |
| POTATO | 2016 | 1,387 | 1,118 | 1,556 | 1,329 | 2,346 | yes | 8/12 |
| POTATO | 2017 | 1,540 | 1,232 | 1,804 | 1,475 | 2,604 | yes | 7/12 |
| POTATO | 2018 | 1,722 | 1,299 | 1,967 | 1,638 | 2,890 | yes | 7/12 |
| POTATO | 2019 | 1,968 | 1,474 | 2,198 | 1,818 | 3,208 | yes | 8/12 |
| POTATO | 2020 | 2,051 | 1,717 | 2,417 | 2,018 | 3,561 | yes | 7/12 |
| POTATO | 2021 | 2,302 | 1,960 | 2,577 | 2,240 | 3,952 | yes | 7/12 |
| POTATO | 2022 | 2,654 | 2,028 | 3,080 | 2,486 | 4,387 | yes | 8/12 |
| POTATO | 2023 | 2,963 | 2,365 | 3,315 | 2,760 | 4,870 | yes | 8/12 |
| POTATO | 2024 | 3,358 | 2,549 | 3,815 | 3,063 | 5,405 | yes | 8/12 |
| POTATO | 2025 | 3,602 | 2,695 | 4,079 | 3,400 | 6,000 | yes | 8/12 |

Finding: yearly medians above `env high`: none. Below `env low`: TOMATO 7/10 years (at most 5.0% below). Not a failure: the anchor is Lahore official retail, so wholesale may sit under its low edge (9.2 review, D-043).

Chart: `e1_levels.png`.

## 3. Seasonal shape per crop

Observed = mean of detrended log price by calendar month (each mandi-year de-meaned); spec = the spec `dips` curve.

| crop | trough month (obs) | trough month (spec) | peak-to-trough (obs) | peak-to-trough (spec) | corr |
| --- | --- | --- | --- | --- | --- |
| ONION | 5 | 5 | 25% | 25% | 0.98 |
| TOMATO | 5 | 5 | 28% | 29% | 0.99 |
| POTATO | 2 | 2 | 31% | 29% | 1.00 |

Chart: `e1_seasonal.png`.

## 4. Gaps and thin series (coverage of trading days 2024-12-19 to 2025-12-18)

`(gate)` = below the 60% coverage gate, so not eligible for F1/F2. Max gap = longest run of missing trading days over the whole development period. The recent-quote rule (last 3 trading days) is checked by the price service (8.2).

| mandi | thin in spec | ONION cov | ONION max gap | TOMATO cov | TOMATO max gap | POTATO cov | POTATO max gap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Lahore |  | 98% | 1 | 98% | 1 | 97% | 3 |
| Okara |  | 98% | 2 | 98% | 1 | 97% | 1 |
| Sahiwal |  | 97% | 2 | 98% | 1 | 98% | 2 |
| Kasur |  | 98% | 1 | 98% | 2 | 99% | 1 |
| Faisalabad |  | 97% | 2 | 98% | 2 | 98% | 2 |
| Multan |  | 99% | 1 | 96% | 2 | 98% | 2 |
| Gujranwala |  | 97% | 2 | 99% | 1 | 100% | 2 |
| Sargodha |  | 99% | 1 | 97% | 2 | 99% | 1 |
| Bahawalpur |  | 98% | 2 | 98% | 2 | 96% | 2 |
| Sheikhupura |  | 97% | 1 | 98% | 2 | 99% | 2 |
| Pakpattan |  | 96% | 1 | 97% | 2 | 97% | 1 |
| Vehari |  | 99% | 2 | 99% | 2 | 98% | 1 |
| Jhang | yes | 49% (gate) | 12 | 44% (gate) | 14 | 36% (gate) | 16 |
| Dera Ghazi Khan | yes | 37% (gate) | 12 | 45% (gate) | 14 | 49% (gate) | 10 |
| Rahim Yar Khan | yes | 47% (gate) | 13 | 48% (gate) | 10 | 48% (gate) | 12 |

Eligible mandis per crop: ONION 12, TOMATO 12, POTATO 12 (demo needs >= 5, file 10 §4).

Chart: `e1_coverage.png` (mean coverage of the 3 crops per mandi and year).

## 5. QC example

Chart: `e1_qc.png`: the series with the most injected typos, one year, injected defects vs flags.

## 6. G1 realism verdict and crop list proposal (task 9.2, D-043)

| criterion | result | pass |
| --- | --- | --- |
| QC recall on injected defects = 100% (5.3) | 100% | PASS |
| No yearly median above `env high` | none above | PASS |
| Seasonal trough month = spec, every crop | all match | PASS |
| >= 5 eligible mandis per crop (file 10 §4) | ONION 12, TOMATO 12, POTATO 12 | PASS |

Realism check: **PASSED**.

Crop list proposal for G1: Onion (12 eligible mandis), Tomato (12 eligible mandis), Potato (12 eligible mandis) for price now, F1 and F2; Wheat (monthly) for F3 only. Thin mandis below the coverage gate, so not used for F1/F2: Jhang, Dera Ghazi Khan, Rahim Yar Khan. E1 does not check Wheat: monthly, no plausibility anchor; its panel is checked in task 10.4.
