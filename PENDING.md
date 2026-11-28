# What is missing (open items)

Last updated: Sat 28 Nov 2026. Plan: `plan3/pdf/11_Execution_Plan.pdf` (Day 1 = Mon 23 Nov, Mon–Fri).
Decisions: `DECISIONS.md` (next free ID: D-050; D-046 is reserved for the 9.4 freeze hash, D-047 is 10.1 on PR #54). Remove a line here when it is done, in the same PR.

## Done so far
Days 1–5 complete; gate M1 passed (D-026). Day 6: 6.1 resolver, 6.2 orchestrator, 6.3 features merged. Day 7: 7.1 rule parser (D-031), 7.2 query state manager (D-032), 7.3 baselines E2 (D-033) merged. Day 8: 8.1 speech service DONE live 2026-11-28 (D-035); 8.2 price service + coverage refresh DONE (D-036); 8.3 ps_v1 DONE (D-041, supervisor approved 2026-11-28). Day 10: 10.2 gate G1 passed (D-048, supervisor approved 2026-11-28; crop list frozen). Day 9: 9.1 renderer + validator DONE (D-037); 9.2 E1 final + crop list proposal DONE (D-043, realism PASSED); 9.3 lockbox rehearsal sealed (D-038–D-040; folders in `D:/fyp/data/lockbox/`, back them up outside the repo, never open before the witnessed rehearsal).
6.4 voice benchmark: items, gold and tooling merged (PR #33, D-030); **recordings missing** (below).

## 0. Task 9.4 benchmark freeze: what is left (checklist, in order)
**DONE condition (file 11):** 40 text + 30 voice + 5 controls + 30 multi-turn/commands, files + gold committed, **hash
in `DECISIONS.md`**. Deadline **Day 10, Fri 4 Dec**; gate G2 (10.3) needs it the same day. Tick a box in the PR that does it.

**Already done (2026-11-28):** all item files written: `text.jsonl` 40, `voice.jsonl` 30 lines + gold,
`controls.jsonl` 5, `multiturn.jsonl` 30 (PR #52, D-044). Second-person proofread of all three gold files by Ashna,
with fixes (PR #53, D-045). Full suite 643 passed with Postgres 16.

**A. Merge what is written** (partner, today/tomorrow)
- [ ] Review and merge **PR #52** (multi-turn set, D-044), then **PR #53** (proofread, D-045; it retargets to `main` by itself).
- [ ] On merge, set D-044 and D-045 from PROPOSED to CONFIRMED (or write what to change).

**B. Speakers ready** (by Mon 30 Nov, so there are 3 days left to record)
- [ ] **S2 = Ashna**: row is committed on her local branch `task-6.4-recordings-s2`
  (`S2,Ashna,18-25,F,urdu,P2,2026-11-28`); it goes into the same PR as her notes. **Check the phone class:** Realme
  RMX5303 is maybe a budget phone (= P1, not P2). If so: swap phone with another speaker, or record a new decision.
- [ ] **S3**: find an Urdu-accent speaker (5 notes on P3 iPhone). Decided 2026-11-28: the supervisor is **not** asked to record.
- [ ] **S4**: find an Urdu-accent speaker (5 notes on P1).
- [ ] **S6**: find a Punjabi-accent speaker (5 notes on P3).
- [ ] **S5 (Ammi)**: write her `consent_date` into `speakers.csv`.
- [ ] **Pashto or Sindhi speaker for `C-LANG-01`.** `controls.jsonl` lists all 5 controls under S1, but S1 cannot
  record this one: give it a new speaker ID (S7) with a row in `speakers.csv`, or record a decision.
- [ ] **Decide where each speaker records:** on the team phone of their slot (P1/P2/P3), or on their own phone. Own
  phone = its number may need adding to Meta's test-recipient list (max 5, unverified, see §1) and its class must
  match the slot.

**C. Record and store all 35 notes** (by **Thu 3 Dec**; how-to and rules in §1)
- [ ] Try **one** note end to end first (send → "Echo" reply → media ID on the VM → `voice_pull.py` → test passes).
- [ ] 30 voice notes: S1 V01–V04, V23 · S2 V05–V08, V24 · S3 V09–V12, V25 · S4 V13–V14, V26–V28 · S5 V15–V18, V29 · S6 V19–V22, V30.
- [ ] 5 controls: C-SIL-01 (5 s silence), C-SIL-02 (20 s silence), C-MUS-01 (~15 s music), C-LANG-01 (Pashto/Sindhi), C-LONG-01 (> 120 s).
- [ ] **Listen to every note** and compare it with `gold_transcript`: if the speaker said something else, edit the
  transcript (and gold) to what was said (SPEC §2.2). Check a note is 3–45 s (controls exempt).
- [ ] **Silence check (D-035):** for the 2 silent + 1 music control, look at the `message_log` row: silent →
  `precheck` SILENT with 0 STT attempts; music → OK. Adjust `ACTIVE_DBFS`/`MIN_ACTIVE` in `app/speech.py` only if one
  lands on the wrong side.
- [ ] `pytest tests/test_benchmark_voice.py` passes (every recorded note has a named speaker with a consent date).
- [ ] **Back up** `data/benchmark/audio/` outside the repo (audio is not in git; Meta deletes media after 30 days).
- [ ] Commit `voice.jsonl`, `controls.jsonl` (duration_s filled), `manifest.csv` (sha256 per audio file) and
  `speakers.csv`; PR; CI green; merge.
- [ ] **Nobody sends STOP** from a recording phone until its notes are pulled.

**D. Freeze** (Fri 4 Dec, after C is merged)
- [ ] Write the benchmark hash command (e.g. `python -m scripts.bench_hash`): one sha256 over `SPEC.md`,
  `text.jsonl`, `voice.jsonl`, `controls.jsonl`, `multiturn.jsonl`, `speakers.csv` and `manifest.csv` (the manifest
  already holds each audio file's sha256, so the audio is covered without putting it in git). Add a test that fails
  when the files no longer match the recorded hash.
- [ ] Run it on `main` after the last merge; record **D-046** (hash, file list, commit, date). From then on, any
  benchmark change needs a new decision and a new hash.
- [ ] Tick 9.4 DONE here; it feeds 10.3 (G2).

**Handed to later tasks (not part of 9.4, so they are not forgotten):**
- 10.1: pass `unknown_place=True` to `render.clarify` when the parsed place is `UNKNOWN` (D-045).
- 12.x / renderer: `best_mandis` takes an optional `mandi` arg for the "tafseel" detail card (D-045).
- 14.x: the alert service must expose `list_alerts` (D-044).
- 15.3: first parser/LLM run on `multiturn.jsonl`; do **not** run the parser on it before (held out, D-044).

## 1. Voice recordings (task 6.4): NOT done
DONE condition (file 11): 10 notes stored with gold; all 30 notes + 5 controls by **Day 9 (Thu 3 Dec)**, before the
benchmark freeze 9.4 (Day 10).

| Speaker | Who | Phone | Notes | Status |
|---|---|---|---|---|
| S1 | project owner | P1 (cheap Android) | V01–V04, V23 | not recorded |
| S2 | Ashna (Urdu accent), consent 2026-11-28 | P2 (mid Android); phone class to confirm (§0 B) | V05–V08, V24 | not recorded |
| S3 | **missing: name needed** (Urdu accent; not the supervisor, decided 2026-11-28) | P3 (iPhone) | V09–V12, V25 | not recorded |
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
| AWS credit end date (D-009) | — | Check Billing → Credits; fallback Oracle Always-Free. |
| D-002 user-agent contact email | FYP-II only | Choose before any AMIS fetching. |

## 3. Next plan tasks (critical path)
Day 8 onward per file 11.
7.3 left for its consumers (D-033): 11.1 (E3) and 12.2 (E5) import `f1eval.folds_for`/`score_rows`, `devdata.price_rows`, `baselines.BASELINES` and `harness.predict_folds` (embargo = h, not D-016's h−1), and add their scripts to the `Makefile` `results` target (G3, 13.4). 8.3 wrote `params/ps_v1.yaml` (D-041; `f1_eval` unchanged); rerun `make results` after the `ps_v1` tag (E2 is pre-freeze). G3 canonical bytes: record the E2.csv sha256 from the CI runner/VM (D-014). SYN-NULL is for F1 false-skill checks only (D-034): 12.2 (E5) runs on SYN; 11.1 also runs a deliberately leaky model on SYN-NULL, which must beat naive (proves the check still has power). 8.2 left for its consumers (D-036): 12.1 calls `price.refresh_coverage` in the batch, writes `outlier_flag` and flips a SUSPECT row back to OK when the next quote confirms it; 9.1/10.1 use `price.price_now` (stale line when `stale`, `None` → maloomat nahi); 14.3/18.2 pin `as_of` to the S-DEMO day. 9.1 left for 10.1 (D-037): pick the reply language, send `Reply.buttons` with `gateway.send_buttons`, add `message_log.validator_result` and store `compose`'s result, pass the payload's place ids (incl. F2 origin) as `allowed`. 7.2 left for its consumers: parser output → state patches and `record_answer` after a ranked send (9.1/10.x/14.2), see D-032.

## 5. Task 10.3 gate G2 freeze (Fri 4 Dec): checklist (D-049)
DONE = git tag `ps_v1` exists and every artefact below is present. **Tag last.**
| Artefact | State | Left |
|---|---|---|
| `ps_v1` final + S1–S5 | done (D-041 CONFIRMED, on `main` via PR #55) | — |
| Lockbox rehearsed | done (D-038–D-040) | — |
| L1–L6 | pass in CI | — |
| T6 lockbox hash | CI no-op | owner runs `pytest tests/test_lockbox.py` + `python scripts/lockbox.py verify` where `D:/fyp/data/lockbox/` is; paste output in the freeze PR |
| T7 (F3 timing) | no test yet | write it in 10.4 (before Fri) |
| T8 (CPI) | decision: not wired in FYP-I | — |
| Spec + seed hash | `python -m scripts.freeze_hash` ready | record `- freeze spec sha256 …` on freeze day |
| Benchmark hash (D-046) | command ready; 10 of 35 notes sent, 0 pulled | all 35 pulled + merged by Thu 3 Dec; then record `- freeze benchmark sha256 …` |
| Guard test | — | add on freeze day: `freeze_hash.verify()` returns no problems |
| `git tag -a ps_v1` | — | on the freeze PR's merge commit, then `git push origin ps_v1` |

**Decide by Wed 2 Dec** whether the voice set needs the cut list (file 11 §10) if the recordings will not be pulled by Thu.
