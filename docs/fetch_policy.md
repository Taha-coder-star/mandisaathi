# Fetch policy: public AMIS route

Source: plan pack file 07 §1 (v2, 17 Nov 2026). Constants used in code: `mandi/ingest/policy.py`.
The supervisor approved the public AMIS price pages as the only data source. No official export will be provided.

| # | Rule | Detail and reason |
|---|------|-------------------|
| 1 | Approval on file | The supervisor's approval email is saved in `docs/approvals/` before the first bulk request. If the approval was verbal, ask for a one-line email. |
| 2 | Public pages only | Only the public price-by-commodity page (`ViewPrices.aspx`) and its date picker, used as any visitor uses them. Nothing behind the login page, no data-entry pages, no guessing hidden URLs. |
| 3 | Slow and single-threaded | One request every 10 seconds, one at a time. That is slower than a person clicking through dates. Never run two fetchers at once, including from two laptops. |
| 4 | Each page once | A page already in the manifest is never fetched again. All later work uses the saved copy. |
| 5 | Stop on trouble | Stop after 3 consecutive errors, or if responses become slow (over 30 seconds), or if the site shows a block or warning page. Wait until the next day, then resume at the same rate. Never raise the rate to catch up. |
| 6 | Honest identity | User-agent text: `FAST-NUCES FYP research fetcher (non-commercial; contact: [contact email])`. The team chooses which email goes here. No disguise as a browser beyond that. **Pending: email not chosen yet. The fetcher refuses to run until it is set.** |
| 7 | Respect future signals | `robots.txt` returned 404 on 17 Nov 2026 and no terms page exists. Re-check both before each stage. If either later forbids automated access, stop and tell the supervisor. |
| 8 | Keep evidence | Every raw page is saved unchanged, with retrieval time, URL, HTTP status and SHA-256 in the manifest, so the dataset can be audited and rebuilt. |
| 9 | No redistribution | The site states "Copyright © 2006-2026 … All rights reserved." Raw pages and the clean dataset are not published or uploaded to any public repository or data site. They are shared only with the supervisor and examiners on request. The thesis and any paper report aggregates, code, the coverage report and hashes. |
| 10 | Acknowledge the source | Every report, slide and WhatsApp reply names "AMIS Punjab, Directorate of Agriculture (Economics & Marketing)" as the source, with retrieval dates. |
| 11 | Scope of collection | Stage 1: onion and tomato, non-Sunday days 2022-11-01 to 2025-10-31 (about 1,880 requests). Sealed lockbox: 2025-11-01 to 2026-10-31 (about 626). Daily snapshots: 4 per day. Stage 2: older years and potato, planned on Day 9 (about 10,000 requests for onion and tomato 2007–2022). Nothing else. |
| 12 | Two copies | Raw and sealed folders are kept on two laptops plus one private cloud folder, so a disk failure cannot cost the only copy of the source. |

## Pre-stage checklist (run before Stage 1, the lockbox and Stage 2)

- [ ] Approval email present in `docs/approvals/` (rule 1)
- [ ] Contact email set in `mandi/ingest/policy.py` (rule 6)
- [ ] `robots.txt` and terms re-checked, result logged in `DECISIONS.md` (rule 7)
- [ ] No other fetcher running on any laptop (rule 3)
