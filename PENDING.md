# What is missing (open items)

Last updated: Sat 28 Nov 2026. Plan: `plan3/pdf/11_Execution_Plan.pdf` (Day 1 = Mon 23 Nov, Mon–Fri).
Decisions: `DECISIONS.md` (next free ID: D-046). Remove a line here when it is done, in the same PR.

## Done so far
Days 1–5 complete; gate M1 passed (D-026). Day 6: 6.1 resolver, 6.2 orchestrator, 6.3 features merged. Day 7: 7.1 rule parser (D-031), 7.2 query state manager (D-032), 7.3 baselines E2 (D-033) merged. Day 8: 8.1 speech service DONE live 2026-11-28 (D-035); 8.2 price service + coverage refresh DONE (D-036); 8.3 ps_v1 draft written (D-041), **awaiting supervisor review** (= DONE). Day 9: 9.1 renderer + validator DONE (D-037); 9.2 E1 final + crop list proposal DONE (D-043, realism PASSED); 9.3 lockbox rehearsal sealed (D-038–D-040; folders in `D:/fyp/data/lockbox/`, back them up outside the repo, never open before the witnessed rehearsal).
6.4 voice benchmark: items, gold and tooling merged (PR #33, D-030); **recordings missing** (below).

## 1. Voice recordings (task 6.4): NOT done
DONE condition (file 11): 10 notes stored with gold; all 30 notes + 5 controls by **Day 9 (Thu 3 Dec)**, before the
benchmark freeze 9.4 (Day 10).

| Speaker | Who | Phone | Notes | Status |
|---|---|---|---|---|
| S1 | project owner | P1 (cheap Android) | V01–V04, V23 | not recorded |
| S2 | **missing: name needed** (Urdu accent) | P2 (mid Android) | V05–V08, V24 | not recorded |
| S3 | supervisor (**not asked yet**) | P3 (iPhone) | V09–V12, V25 | not recorded |
| S4 | **missing: name needed** (Urdu accent) | P1 | V13–V14, V26–V28 | not recorded |
| S5 | Ammi (Punjabi accent) | P2 | V15–V18, V29 | not recorded; consent agreed, date not yet in `speakers.csv` |
| S6 | **missing: name needed** (Punjabi accent) | P3 | V19–V22, V30 | not recorded |
| controls | S1 | P1 | 2 silent (5 s, 20 s), 1 music, 1 Pashto/Sindhi (**speaker needed**), 1 over 120 s | not recorded |

Volunteers agreed on WhatsApp to send notes when asked. Each needs: name, speaker ID, consent date and phone type
in `data/benchmark/speakers.csv` (no phone numbers). If phones don't match P1/P2/P3, record it as a new decision.

**How to record and store one note**
1. Lines to read: `python scripts/voice_pull.py sheet S2` (prints each line in Roman + Urdu, with the condition:
   QUIET = quiet room, INDOOR = fan/TV on, OUTDOOR = outside with street sound).
2. The speaker holds the mic **inside WhatsApp** and sends the note **directly** to the bot test number
   +1 555-165-0384 (not forwarded through someone else). One second of silence before and after: notes must be 3–45 s.
   The bot replies "Echo: voice note received".
3. VM (browser terminal, `~/mandisaathi`): get the media ID with the SELECT in `scripts/voice_pull.py`'s docstring
   (newest first; the `sender` column tells phones apart).
4. Laptop, from `D:/fyp` only (needs `.env`; audio is git-ignored, never pull into a worktree):
   `python scripts/voice_pull.py V05 <media_id>`. Writes `audio/V05.ogg`, `duration_s`, `manifest.csv`.
5. `pytest tests/test_benchmark_voice.py` must pass (a recorded note needs a named speaker with a consent date).
6. Back up `data/benchmark/audio/` outside the repo (Meta keeps media 30 days; the audio is not in git).
7. Commit `voice.jsonl`, `manifest.csv`, `speakers.csv` on a branch made in `D:/fyp`; PR; CI green; merge.

**Rules:** never send STOP from a recording phone before its notes are pulled (STOP deletes the media IDs).
If the speaker said something different from the line, edit `gold_transcript` (and gold) to what was said.

**Verified 2026-11-27:** Meta serves a voice note a second time after the bot downloaded it (4 live notes re-downloaded by
media ID on the laptop, D-035). Whether a volunteer number not on Meta's test-recipient list (max 5) still reaches the bot.

## 2. Other open items
| Item | Needed by | What to do |
|---|---|---|
| Silence levels vs the real 6.4 controls (D-035) | before G2 (Day 10) | 8.1 is DONE. When the 6.4 silent (5 s, 20 s) and music controls go through the bot, check each `message_log` row: silent → `precheck` SILENT with 0 attempts, music → OK. `stt_meta` holds `active_ratio` and `p10/p50/p95/max_dbfs`; adjust `ACTIVE_DBFS`/`MIN_ACTIVE` in `app/speech.py` only if a control lands on the wrong side. **Quota:** every note to the bot spends Scribe free minutes (~12/month). |
| 6.2 live check on the VM | soon | Deploy main (`git pull`, `sudo docker compose up -d --build`; migrate applies 003, 004 and 005). Text from a phone: consent + echo once; "STOP": confirmation, then `SELECT count(*) FROM wa_user` drops. |
| Benchmark hash + freeze (9.4, D-046) | Day 10 | Proofread DONE (Ashna, 2026-11-28, D-045: text, voice, multi-turn). Left: the 6.4 recordings, then a benchmark hash command, freeze, and record the hash as D-046. |
| 8.4 lit review: check ≥ 15 rows myself (D-042) | 8.4 DONE; before 18.1 | Open `docs/lit_review.md`; for each row read the abstract (link in `Cite check`), fix the annotation if needed, set `Read` to `abstract`/`full`. Check row 14's "10–16%" figure first. |
| G1 record (task 10.2) | Fri 4 Dec | All three G1 inputs are in D-043 (realism PASSED, crop list proposed, real-data request acknowledged). At 10.2: freeze the crop list, ask the supervisor to confirm the E1 pass rule (below the retail low edge is not a failure), write the G1 entry. |
| AWS credit end date (D-009) | — | Check Billing → Credits; fallback Oracle Always-Free. |
| D-002 user-agent contact email | FYP-II only | Choose before any AMIS fetching. |

## 3. Next plan tasks (critical path)
Day 8 onward per file 11.
7.3 left for its consumers (D-033): 11.1 (E3) and 12.2 (E5) import `f1eval.folds_for`/`score_rows`, `devdata.price_rows`, `baselines.BASELINES` and `harness.predict_folds` (embargo = h, not D-016's h−1), and add their scripts to the `Makefile` `results` target (G3, 13.4). 8.3 wrote `params/ps_v1.yaml` (D-041; `f1_eval` unchanged); rerun `make results` after the `ps_v1` tag (E2 is pre-freeze). G3 canonical bytes: record the E2.csv sha256 from the CI runner/VM (D-014). SYN-NULL is for F1 false-skill checks only (D-034): 12.2 (E5) runs on SYN; 11.1 also runs a deliberately leaky model on SYN-NULL, which must beat naive (proves the check still has power). 8.2 left for its consumers (D-036): 12.1 calls `price.refresh_coverage` in the batch, writes `outlier_flag` and flips a SUSPECT row back to OK when the next quote confirms it; 9.1/10.1 use `price.price_now` (stale line when `stale`, `None` → maloomat nahi); 14.3/18.2 pin `as_of` to the S-DEMO day. 9.1 left for 10.1 (D-037): pick the reply language, send `Reply.buttons` with `gateway.send_buttons`, add `message_log.validator_result` and store `compose`'s result, pass the payload's place ids (incl. F2 origin) as `allowed`. 7.2 left for its consumers: parser output → state patches and `record_answer` after a ranked send (9.1/10.x/14.2), see D-032.
