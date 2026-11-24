# Decision register

Tags: **CONFIRMED** (verified or agreed, with evidence) · **REPORTED** (stated by a source, level noted) · **ASSUMPTION** (placeholder to be replaced).
Newest entries at the bottom. Each entry has an ID, a date (PKT), the owner, a tag and its evidence.

## D-001 · 2026-11-18 · Taha · CONFIRMED (verbal; written record pending)
Public AMIS price pages, read through the date picker, are approved by the supervisor as the project's only data source. No official export will be provided.
- Evidence: verbal approval, 17 Nov 2026. Written one-line confirmation requested (`docs/approvals/README.md`).
- Condition: no bulk request (Stage 1, lockbox, Stage 2) until `docs/approvals/supervisor_public_route.pdf` exists. Daily 4-page snapshots may continue.
- **Superseded for FYP-I by D-008** (synthetic data). AMIS stays the FYP-II backup source only.

## D-002 · 2026-11-18 · Taha · CONFIRMED
Fetch conduct rules adopted as `docs/fetch_policy.md` (copied from plan file 07 §1). Code constants are in `mandi/ingest/policy.py`.
- User-agent contact email: **not chosen yet**. `user_agent()` raises until it is set (rule 6).

## D-003 · 2026-11-18 · Taha · CONFIRMED
Disclosure: the 17 Nov 2026 exploratory probe (`plan/reference/amis_probe.py`) predates the fetch policy. It used the user-agent `Mozilla/5.0 (research-probe)` and a 2.5 s delay between requests, which breaks rules 3 and 6. Output: `plan/reference/amis_probe_output_2026-11-17.txt`. That script is no longer used. All fetching from now on uses `mandi/ingest/policy.py`.

## D-004 · 2026-11-23 · Taha · CONFIRMED
Meta setup moved to a second account (tasks 1.1–1.2). The first MandiSaathi portfolio returned 131031 "Business Account locked" on every outbound send, so it was abandoned. New setup: app AgriAgentOs (1768291760921475), business Agriagentos, test number +1 555 191 4461, system user "agrios" (Admin). All `.env` values were replaced; nothing from the old account is still in use.
- Token diary: system-user token, permissions `whatsapp_business_messaging` + `whatsapp_business_management`, expiry **never**. Re-check with `python scripts/check_token.py`. If it is ever revoked, regenerate it under System users → agrios.
- Evidence: `check_token.py` on 2026-11-23 printed `type=SYSTEM_USER expires=never` and confirmed the number in the WABA (quality GREEN).

## D-005 · 2026-11-23 · Taha · REPORTED (Meta review pending)
Task 1.3: templates submitted to the test WABA with `python scripts/submit_templates.py` (re-run it to see current status).
| name | lang | requested | status 23 Nov | category after review |
|---|---|---|---|---|
| price_alert | en | UTILITY | PENDING | UTILITY (at submission) |
| price_alert | ur | UTILITY | PENDING | UTILITY (at submission) |
| daily_rates | en | UTILITY | PENDING | UTILITY (at submission) |
| daily_rates | ur | UTILITY | PENDING | UTILITY (at submission) |
- `ur` versions are **Roman Urdu** filed under the `ur` code (user's choice). If Meta rejects them for language mismatch, resubmit in Urdu script.
- Source and date are variables, so FYP-I fills source with "Demo data (synthetic)" and FYP-II needs no resubmission. Prices per 100 kg.
- Open: file 02 R9 (is a requested alert UTILITY, is a digest MARKETING?) is answered only once review ends. Update this table then; Meta may recategorise after approval.

## D-006 · 2026-11-23 · Taha · CONFIRMED
Task 1.4 stack choices (the plan names none of these):
- **Python 3.12** in the image and CI (`python:3.12-slim`). My machine defaults to 3.14, but ML wheels (LightGBM, statsforecast) lag new Pythons. Local dev: `py -3.12 -m venv .venv`.
- **FastAPI + uvicorn** for the web role; **ruff** (rule set pinned in `pyproject.toml`) + **pytest**.
- Roles are picked by the container command, with no dispatcher: web = default CMD (`uvicorn app.web:app`), worker = `python -m app.worker`, batch = `python -m mandi.batch` (runs once and exits; cron/APScheduler triggers it, file 07). `docker-compose.yml` has all three; batch sits under a profile (`docker compose run --rm batch`).
- `.env` never enters the image: the Dockerfile copies only `pyproject.toml`, `app/` and `mandi/`, and `.dockerignore` also excludes it. Runtime secrets will come from compose `env_file` (task 2.1).
- DONE check is `scripts/smoke_roles.sh`, the same script locally and in CI (job `image`).

## D-007 · 2026-11-18 · Taha · CONFIRMED (verbal)
Outcome of the 18 Nov meeting (task 1.5): the project direction changes to MandiSaathi as in plan pack 3.
- Scope: today's mandi price, short-term price forecast (F1), where to sell after costs (F2), harvest-month outlook (F3), price alerts. Delivered on WhatsApp only (text + Urdu voice notes), no farmer app.
- Data route: the co-supervisor is linked to Zarai Mandi and may provide its data. Still unknown: format, history length, written data-use permission. Asked in the D-008 format request.
- Zarai Mandi is never scraped; its data comes only through the co-supervisor (fetch policy rules 2, 11).

## D-008 · 2026-11-22 · Taha · CONFIRMED (team decision; supervisor agreed, reported 23 Nov)
Amendment A1 (file 03 §9): synthetic data in FYP-I, real data in FYP-II.
- FYP-I: one synthetic source (`source = SYN`) generated by us into the canonical schema; SYN and SYN-NULL variants; fixed seed; spec + seed frozen at G2. Every reply, chart and table says "Demo data (synthetic)".
- FYP-II S1: the real data (co-supervisor export; AMIS public pages as the backup under `docs/fetch_policy.md`) through its own loader. The final 12 months are sealed as the lockbox the day the data arrives, before anyone looks beyond a format check.
- The file 03 D3 fallback triggers (Day 3 / Day 10) are removed. FYP-I results are pipeline verification only; no claim about real-market accuracy.
- Supersedes D-001's "AMIS only" for FYP-I.
- Real-data format request: draft `docs/requests/2026-11-23_real_data_request.md`. **Sent: 2026-11-23 on WhatsApp** (by Taha). G1 (task 10.2, Fri 4 Dec) needs it acknowledged or chased.

## D-009 · 2026-11-23 · Taha · CONFIRMED
Task 2.1 hosting (resolves file 07 R11 for FYP-I):
- **AWS EC2 t3.micro** (free tier eligible, 1 GiB RAM + 2 GiB swap file), **us-east-2 (Ohio)**, Ubuntu 24.04, 20 GiB gp3. Ohio instead of Mumbai: Meta webhooks and the LLM/STT APIs are US-side; farmers only talk to WhatsApp, never to the VM. t3.micro instead of t3.small: enough for caddy + web + worker + postgres with swap, and free-tier covered.
- Account: the AWS account is registered to Ashna; I (Taha) operate it. It must stay accessible through May 2027.
- Elastic IP **3.13.120.80** → hostname **3-13-120-80.sslip.io**; Caddy gets the Let's Encrypt certificate (HTTP → 308 → HTTPS).
- Security group: 22 only from EC2 Instance Connect (`3.16.146.0/29`, the us-east-2 range in ip-ranges.json); 80/443 open. Postgres has no published port; web binds 127.0.0.1:8000, reachable only through Caddy.
- Deploy: read-only GitHub deploy key on the VM, `git pull` + `sudo docker compose up -d --build`. `.env` copied by hand, `chmod 600`. No registry, no deploy pipeline (one operator).
- Free-tier / credit end date: **TBD** (check Billing → Credits). If it ends before the final evaluation (week of 24 May 2027), move to Oracle Always-Free per file 07 §4 (plain Docker, config change only).
- Not yet: nightly `pg_dump` backups (file 07 §2); added once real rows exist (task 3.2).
- DONE evidence: `curl -i https://3-13-120-80.sslip.io/health` → `200 {"status":"ok","db":"ok"}`, 2026-11-23 18:09 UTC.

## D-010 · 2026-11-24 · Taha · CONFIRMED
Task 2.3 schema v1 (`app/migrations/001_schema_v1.sql`, runner `app/migrate.py`). Where RFC §8 / file 03 §3 do not say, I chose:
- **17 tables, not 18:** `usage_event` deferred to the first task that writes usage (LLM turn 11.2 or the alert budget). No plan file defines its columns; guessing them now would be design without a user.
- **Conversation tables** (`wa_user`, `query_state`, …) go in with task 6.2; **alert tables** (`subscription`, `alert_event`) with the alerts task. Each as a new numbered migration.
- **CHECK instead of Postgres ENUM** for `source`, `outlier_flag`, `crop_alias.kind`, `crop.perishability_class`, job/outbound status: adding a value later is a one-line migration.
- **`price_obs.source` allows `SYN`, `SYN-NULL`, `AMIS`, `ZM`.** A1 calls SYN-NULL a variant of SYN; storing it as its own source value lets both variants sit in one table and be told apart.
- `price_obs.grade` stays nullable (file 03); the observation key is `UNIQUE NULLS NOT DISTINCT (source, mandi_id, crop_id, grade, market_date)` (Postgres 15+). `min > max` is **not** rejected by the DB: the generator injects it and QC must flag it.
- `series_coverage.window` → **`window_days`** (`WINDOW` is a reserved word in Postgres).
- `place.candidate_mandi_ids text[]` for place → candidate mandis (no join table; no FK on array elements, so the gazetteer load must check them).
- Alias keys are `(alias_norm, crop_id)` / `(alias_norm, place_id)`: designed-ambiguous aliases (task 4.3) need one alias → several targets.
- `data_health.status` is plain text; task 12.1 defines its values. No p10 ≤ p50 ≤ p90 CHECK on forecasts (separately fitted quantile models can cross; the model code must sort them).
- **Infra column sets are ASSUMPTION** (RFC §8 only names the tables): `inbound_event` (unique `dedup_key` = WAMID or status key; `user_key` text for BSUID "US.…"; `payload` jsonb, **task 3.1 must strip/hash phone numbers before insert**, file 07 §3), `job` (claim index `(priority, run_at) WHERE status = 'queued'`, lower priority runs first; lease via `locked_until`), `outbound_message` (`UNIQUE (job_id, seq)`).
- **Migrations run automatically on deploy:** compose service `migrate` (one-shot, `python -m app.migrate`); web/worker/batch wait for `service_completed_successfully`. Runner: one transaction per file, `schema_migrations(version, checksum, applied_at)`, advisory lock, sha256 checksum (CRLF normalised) so an edited applied migration fails loudly.
- DONE evidence: `tests/test_migrate.py` (empty DB → 17 tables; rerun → history unchanged; rollback; checksum; 3 concurrent migrators apply once) against Postgres 16 locally and in CI.

## D-011 · 2026-11-24 · Taha · CONFIRMED (supervisor reviewed, no changes requested)
Task 2.4 synthetic spec `data/synthetic/spec.yaml` (file 03 §9.1, A1). Choices where the plan is silent:
- **Reviewer:** the supervisor (I work alone; D-010's "second member" is the supervisor). **Reviewed 2026-11-24: supervisor said the spec is fine, no change requests** (reported by me, verbal; exact review date not recorded). Task 2.4 DONE.
- **Holdout** is a separate file for 2025-12-19 → 2026-12-18 generated from the same seed and spec, sealed in task 9.3. The normal load and the S-DEMO daily feed never read it, so the 11 Dec 2026 demo load is unaffected.
- **Mandis:** 15 Punjab cities, centroids from the Wikipedia coordinates API (fetched 2026-11-24), not market gates. Thin (<60% coverage): Jhang, Dera Ghazi Khan, Rahim Yar Khan. Lahore, Okara, Sahiwal, Kasur are forced non-thin; a test enforces ≥5 non-thin mandis per crop and ≥3 within 150 km of Okara.
- **All price parameters are ASSUMPTION** (base level, trend, AR(1), jumps, distance slope). Seasonal dips: potato autumn crop Jan–Mar (PBS crop calendar, Dawn), tomato local season from April (Punjab Price Control Dept). **Onion harvest months have no confirmed source**; the Apr–Jun dip is an assumption.
- **Plausibility** is anchored on one sourced level: Lahore *retail* per-kg prices, Pakistan Today, 1 Sep 2025 (×40 kg → per mann), used as an upper-side envelope. No sourced 2016 level found (UNVERIFIED): earlier years are deflated with `annual_trend`. E1 (task 5.3) compares against this; replace with a cited 2016 level if one turns up before G2.
- Moving holidays (Eid, Ashura) are synthetic: 2016 anchor dates drifting −11 days/year, not an official calendar.
- New dependency: `pyyaml` (the generator reads the spec).
- Frozen at G2 (task 10.3): spec hash and seed recorded there.

## D-012 · 2026-11-24 · Taha · CONFIRMED
Task 2.5 lockbox procedure (`docs/lockbox_procedure.md`, `scripts/lockbox.py`, `tests/test_lockbox.py`). Choices where the plan is silent:
- **Folder:** `data/lockbox/<name>/`, git-ignored; only the hash is committed (as a `- lockbox <name> sha256 <hex>` line in a decision entry written by `lockbox.py seal`).
- **Hash:** sha256 over sorted relative paths + per-file sha256, so edits, additions, removals and renames all break `verify`. A seal is never replaced.
- **CI read-guard:** static scan, fails if any `.py` under `app/`, `mandi/` or `scripts/` (except `scripts/lockbox.py`) mentions "lockbox". Not proof against dynamic paths; adequate for a solo repo. Task 9.3 adds its single generator call site to the allowlist.
- **Witness:** FYP-I rehearsal opening is witnessed by whoever I name in the log; FYP-II by the (co-)supervisor.

## D-013 · 2026-11-24 · Taha · CONFIRMED
Task 3.1 idempotent ingest (`app/ingest.py`, `app/web.py`, `tests/test_ingest.py`). Choices where RFC §3/§13 and file 07 §3 do not say:
- **No migration:** 001 already has `inbound_event.dedup_key UNIQUE` and `job`.
- **One transaction per webhook POST:** per item, `INSERT inbound_event … ON CONFLICT (dedup_key) DO NOTHING RETURNING` chained into the `job` insert. Duplicate → neither row, still 200. Any DB error → whole POST rolled back → 503, so Meta redelivers.
- **Dedup key:** message = WAMID; status = `<wamid>:<status>` (RFC §13 "(wamid, status)").
- **One event + one job per new item** (job kind `turn` for messages, `status` for statuses), job payload `{"event_id": …}`. Per-farmer coalescing comes in 6.2, debounce in 14.1.
- **`user_key`** = the user ID (`from_user_id` / `recipient_user_id`) if present, else the phone hash. Matching the two for one farmer is deferred to `wa_user` (6.2).
- **Phone numbers** (`from`, `wa_id`, `new_wa_id`, `recipient_id`, `phone`, at any depth) are replaced by HMAC-SHA256(`PHONE_HASH_KEY`, digits only) before insert. This is file 07 §3's "salted hash", deterministic so rows join. Key only in `.env`, must never change; missing key → 503 (fail closed). The encrypted number for sending is deferred to 5.1. `metadata.display_phone_number` (our business number) and the profile name are kept (90-day retention).
- **Responses:** bad signature 401; signed but malformed 400; key missing, DB down or DB error 503; otherwise 200. Non-`messages` fields and `value.errors` are logged (field name only, never the body) and acked, not stored.
- **ASSUMPTION:** statuses carry `recipient_user_id` (falls back to hashed `recipient_id`). Confirm against the dashboard "Username scenario" sample.
- DONE evidence: `tests/test_ingest.py::test_same_payload_twice_one_event_one_job` (PR #11 CI run 45347758172 green: secrets, test, image).

## D-014 · 2026-11-24 · Taha · CONFIRMED
Task 3.2 generator + loader (`scripts/make_synthetic.py`, `mandi/ingest/loader.py`, `tests/test_make_synthetic.py`, `tests/test_loader.py`). Choices where spec.yaml and file 03 §3/§9.1 do not say:
- **Period:** `syn.csv` / `syn_null.csv` run to 2026-12-18, so they contain the holdout year (2025-12-19 → 2026-12-18). Development folds must end 2025-12-18. The separate holdout file and its sealing are task 9.3, not here.
- **Task 9.3 "seal the SYN-NULL variant"** is read as sealing the SYN-NULL holdout year, the same way as the SYN one.
- **Wheat** goes to its own `wheat_monthly.csv` (month, crop_id, region PUNJAB, avg_pkr100kg; no defects): `price_obs.mandi_id` is NOT NULL with an FK to `mandi`, and wheat has no mandi dimension. F3 (task 10.4) reads that file.
- **Random streams:** one PCG64 stream per named key, `SeedSequence([seed, crc32(name)…])`, instead of `spawn()` order (spec `meta.rng` asks that adding a mandi or crop never shifts another stream; position-based `spawn()` cannot promise that). Price streams are keyed by (variant, crop[, mandi]); mandi effects, daily range, arrivals noise, defects and timing leave out the variant, so SYN and SYN-NULL have identical rows, defects, name variants and `reported_at`.
- **SYN-NULL** log price = ln(base) + mandi effect + a crop-wide random walk (σ = `ar1_common.sigma`) + a per-mandi random walk (σ = `ar1_mandi.sigma`). Each series is a pure random walk with σ = √(σc² + σm²), and mandis stay correlated as in SYN. No trend, dips, AR(1) persistence or jumps; arrivals have no seasonal term.
- **Spec readings:** dip `width` is the Gaussian σ in months over a circular month distance (1.0 = 1 Jan); AR(1) and jumps run on calendar days and start from the stationary distribution (jumps from 0 + the first shock); `mandi_effect` noise is drawn once per (crop, mandi); the 10× typo changes `avg` only (min/max keep the true range), 50/50 ×10 or ÷10; a per-40 kg row is each price rounded to 2 dp then × 0.4 as a Decimal (≤ 3 dp), so × 2.5 recovers it exactly; thin-mandi coverage p ~ U(0.40, 0.55) is drawn once per (crop, mandi); missing-day, thin and every defect mask are independent.
- **reported_at:** the generator writes `market_date 18:00+05:00`, late rows (5%) the next calendar day 18:00. The loader keeps a source time; with no time it uses market_date 18:00 PKT (file 03 §3); a time without a zone is read as PKT. PKT is a fixed +05:00 (Pakistan has no DST; avoids tzdata on Windows).
- **File format:** UTF-8 without BOM, LF, columns `market_date,crop_id,mandi_raw,unit_raw,min_raw,max_raw,avg_raw,arrivals_qty,arrivals_unit,reported_at` then the answer key `truth_mandi_id,truth_typo10x,truth_swap,truth_per40,truth_variant,truth_late` in the same file. The loader never reads `truth_*`. Generated CSVs and `data/synthetic/holdout/` are git-ignored (rebuilt from spec + seed).
- **Hash portability:** prices go through float `exp` before 2 dp rounding, so a different CPU/numpy build could change a rare last digit. The test checks same-machine determinism; the hash frozen at G2 (task 10.3) is the one printed on the CI runner/VM, recorded together with the numpy version.
- **Loader:** units `PKR/100kg` × 1 and `PKR/40kg` × 2.5 as Decimal from the CSV text (never float); any other unit is rejected, not guessed. `value_raw` = avg, else max, else min; `unit_raw` kept as given; `raw_ref` = `file#L<line>`; `raw_sha256` = whole-file hash. One transaction, upsert on the 001 key `(source, mandi_id, crop_id, grade, market_date)`, so a reload changes nothing and keeps `obs_id`. Names resolve only exactly (mandi_id or name_en, case-insensitive); everything else is returned as unmatched and not loaded until task 4.2. `outlier_flag` stays OK (QC is 5.3). SYN-NULL loads as `source = SYN-NULL` (D-010).
- **Reference rows (ASSUMPTION, overlaps task 4.3):** the loader inserts the spec's 15 mandis (city = name_en, province Punjab, `covered` left false) and 4 crops (perishability TOMATO HIGH, ONION/POTATO MED, WHEAT LOW; default unit `mann`; no bag size) with ON CONFLICT DO NOTHING. Task 4.3 owns and may correct them.
- New dependency: `numpy>=2`.
- DONE evidence: `tests/test_make_synthetic.py::test_same_seed_same_file_hash`, `tests/test_loader.py::test_per_40kg_row_converts_times_2_5_exactly` and the DB loader tests (CI run 45353917516 green; local run 75 passed with Postgres; syn.csv sha256 a8bdf852a5d1d65a326e15ebbf05dff1718e927f13db60397d6d33ed40ec1e53 on Windows, re-record from CI/VM at G2).
