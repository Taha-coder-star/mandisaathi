# Decision register

Tags: **CONFIRMED** (verified or agreed, with evidence) · **REPORTED** (stated by a source, level noted) · **ASSUMPTION** (placeholder to be replaced).
Newest entries at the bottom. Each entry has an ID, a date (PKT), the owner, a tag and its evidence.

## D-001 · 2026-11-18 · Taha · CONFIRMED (verbal; written record pending)
Public AMIS price pages, read through the date picker, are approved by the supervisor as the project's only data source. No official export will be provided.
- Evidence: verbal approval, 17 Nov 2026. Written one-line confirmation requested (`docs/approvals/README.md`).
- Condition: no bulk request (Stage 1, lockbox, Stage 2) until `docs/approvals/supervisor_public_route.pdf` exists. Daily 4-page snapshots may continue.

## D-002 · 2026-11-18 · Taha · CONFIRMED
Fetch conduct rules adopted as `docs/fetch_policy.md` (copied from plan file 07 §1). Code constants are in `mandi/ingest/policy.py`.
- User-agent contact email: **not chosen yet**. `user_agent()` raises until it is set (rule 6).

## D-003 · 2026-11-18 · Taha · CONFIRMED
Disclosure: the 17 Nov 2026 exploratory probe (`plan/reference/amis_probe.py`) predates the fetch policy. It used the user-agent `Mozilla/5.0 (research-probe)` and a 2.5 s delay between requests, which breaks rules 3 and 6. Output: `plan/reference/amis_probe_output_2026-11-17.txt`. That script is no longer used. All fetching from now on uses `mandi/ingest/policy.py`.

## D-004 · 2026-11-23 · Taha · CONFIRMED
Meta setup moved to a second account (tasks 1.1–1.2). The first MandiSaathi portfolio returned 131031 "Business Account locked" on every outbound send, so it was abandoned. New setup: app AgriAgentOs (1768291760921475), business Agriagentos, test number +1 555 191 4461, system user "agrios" (Admin). All `.env` values were replaced; nothing from the old account is still in use.
- Token diary: system-user token, permissions `whatsapp_business_messaging` + `whatsapp_business_management`, expiry **never**. Re-check with `python scripts/check_token.py`. If it is ever revoked, regenerate it under System users → agrios.
- Evidence: `check_token.py` on 2026-11-23 printed `type=SYSTEM_USER expires=never` and confirmed the number in the WABA (quality GREEN).
