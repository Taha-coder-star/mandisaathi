# Lockbox procedure (task 2.5; risks R-13, R-14; rule T6)

The lockbox is the final held-out year. No model, feature, threshold or plot is looked at or tuned on it until it is
opened once for the final evaluation. A null result is only valid if this holds.

| | FYP-I (rehearsal) | FYP-II |
|---|---|---|
| Content | Synthetic holdout 2025-12-19 → 2026-12-18 and the SYN-NULL variant (task 9.3) | Last 12 months of the real data |
| Sealed | Task 9.3 (before G2, task 10.3) | The day the data arrives (S1), before anything beyond a format check |
| Opened | Rehearsal opening, logged | Once, S8 |

## Rules
1. Sealed data lives only in `data/lockbox/<name>/`. It is git-ignored, never loaded into the database, never
   copied elsewhere. Real data is never redistributed.
2. No code under `app/`, `mandi/` or `scripts/` may mention the lockbox. `tests/test_lockbox.py` fails CI if one does.
   The generator writes the holdout through `scripts/lockbox.py` only (add the one call site to `ALLOWED` in that test
   when task 9.3 needs it, and say so in the PR).
3. Do not open, plot or summarise the files before sealing beyond a format check (columns, row count).
4. A seal is never replaced. If a sealed folder was wrong, record a new decision and seal a new name.

## Seal
```
python scripts/lockbox.py seal <name>     # e.g. holdout, holdout_null
```
Hashes `data/lockbox/<name>/` (sorted paths + per-file sha256, so edits, additions, removals and renames all change
it) and appends a `D-NNN` entry with `- lockbox <name> sha256 <hex>` to `DECISIONS.md`. Commit that entry.

## Check
```
python scripts/lockbox.py verify [name]   # exit 1 if anything changed since sealing
```
Runs inside `pytest` (T6) for any sealed folder present on the machine. CI has no data folder, so there it only runs
the script's own tests and the read-guard.

## Open (witnessed, once)
1. A second person is present (FYP-II: supervisor or co-supervisor; FYP-I rehearsal: stated in the log).
2. `python scripts/lockbox.py verify` prints OK for every sealed name.
3. Record a `D-NNN` entry first: date, witness, the frozen model/commit tag, the pre-registered criteria
   (S1–S3), then run the evaluation once and log the result unedited, including a null.
4. After opening the folder is no longer a lockbox: results are never used to retune anything.
