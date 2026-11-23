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
- Real-data format request: draft `docs/requests/2026-11-23_real_data_request.md`. **Sent: pending** (date + channel go here). G1 (task 10.2, Fri 4 Dec) needs it acknowledged or chased.
