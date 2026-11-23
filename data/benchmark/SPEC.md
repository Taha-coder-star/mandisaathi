# Bot benchmark spec v1 (task 1.6)

Source: plan3 file 05 §4 (design), §5 (thresholds), red-team R file 09 (8 Punjabi-accented + 8 outdoor notes;
synthetic benchmark, no phone numbers). Items are written in 4.4 (text) and 6.4 (voice) and frozen at 9.4
(sha256 of every file into DECISIONS.md). Scored in 15.3 and 17.2 against file 05 §5 / file 10 §6.

Rules
- Every item is written or recorded by me or a named volunteer; **never** taken from farmer chats (Meta §4.7).
- No phone numbers, real names or locations of people in any item or transcript.
- Coverage (file 10): crops ONION, TOMATO, POTATO (+ WHEAT for outlook); Punjab mandis incl. Lahore, Okara,
  Sahiwal; origins Okara, Sahiwal, Kasur, Lahore. Anything else is designed out-of-coverage.
- Gold says *what the bot must understand and do*, not the numbers it replies with. Reply numbers come from
  golden files (15.1); the benchmark checks intent, slots, tool call and outcome.

## 1. Files
```
data/benchmark/
  SPEC.md            this file
  text.jsonl         40 items  (4.4)
  voice.jsonl        30 items  (6.4)  -> audio in audio/, git-ignored
  controls.jsonl      5 items  (6.4)
  multiturn.jsonl    30 items  (multi-turn + commands)
  speakers.csv       speaker roster (no phone numbers)
  manifest.csv       file, sha256, bytes, duration_s  (every audio file; frozen at 9.4)
  audio/             V01.ogg … C-LONG-01.ogg   (NOT in git: volunteers' voices)
```
One JSON object per line, UTF-8, Urdu script as-is (no escaping needed).

## 2. Label schema
Canonical values (until the gazetteer in 6.1 exists, places use upper-snake canonical names; 6.1 maps them to
mandi IDs and this file's examples are updated, not the items' meaning):

| Field | Allowed values |
|---|---|
| `lang` | `EN`, `RU` (Roman Urdu), `MIX` (EN + RU), `UR` (Urdu script), `PA` (Punjabi-accented speech) |
| `intent` | `PRICE_NOW`, `FORECAST`, `WHERE_TO_SELL`, `OUTLOOK`, `ALERT`, `STOP`, `HELP`, `OTHER` |
| `alert_action` | `SUBSCRIBE`, `SET_THRESHOLD`, `LIST`, `UNSUBSCRIBE` (only when `intent = ALERT`) |
| `crop.id` | `ONION`, `TOMATO`, `POTATO`, `WHEAT`, `OUT_OF_COVERAGE`, `null` (not given) |
| `place.status` | `RESOLVED`, `AMBIGUOUS`, `UNKNOWN`, `OUT_OF_COVERAGE`, `null` (not given) |
| `place.role` | `MANDI` (price asked at) or `ORIGIN` (selling from, F2) |
| `quantity.unit` | `MANN` (40 kg), `KG`, `TON` (1000 kg), `BORI` (ask), `NONE` (number without unit: ask) |
| `horizon` | `{"kind": "TODAY"}`, `{"kind": "DAYS", "h": 1–7}`, `{"kind": "MONTH", "month": "2027-02"}`, `{"kind": "AMBIGUOUS"}` |
| `outcome` | `ANSWER`, `CLARIFY`, `OUT_OF_SCOPE`, `OUT_OF_COVERAGE`, `GRACEFUL_FAIL` |
| `clarify_slot` | `crop`, `place`, `quantity_unit`, `horizon`, `language` (only when `outcome = CLARIFY`) |

**Critical slots** (scored by exact match, file 05 §5 B): `crop.id`, `place.status` + `place.canonical`,
`quantity.value_kg` + `quantity.unit`. A slot the message does not contain must be `null` in gold and in
output; inventing it is a miss.

### 2.1 Text item (`text.jsonl`)
```json
{"id": "T-RU-03", "set": "text", "category": "RU", "lang": "RU",
 "input": "Okara se 50 mann pyaz kahan bechoon",
 "gold": {
   "intent": "WHERE_TO_SELL",
   "slots": {
     "crop":     {"raw": "pyaz", "id": "ONION"},
     "place":    {"raw": "Okara", "canonical": "OKARA", "status": "RESOLVED", "role": "ORIGIN"},
     "quantity": {"raw": "50 mann", "value": 50, "unit": "MANN", "value_kg": 2000},
     "horizon":  null},
   "tool": {"name": "best_mandis", "args": {"crop": "ONION", "origin": "OKARA", "quantity_kg": 2000}},
   "outcome": "ANSWER", "clarify_slot": null},
 "tags": ["quantity", "place_alias"], "notes": ""}
```
`tags` drive the coverage counts in §3.1: `quantity`, `number_word`, `place_alias`, `place_urdu`,
`crop_punjabi`, `horizon`, `spelling_variant`.

### 2.2 Voice item (`voice.jsonl`)
Text-item fields **plus**:
```json
{"id": "V05", "set": "voice", "category": "RU", "lang": "RU",
 "audio": "audio/V05.ogg", "speaker": "S2", "phone": "P2", "condition": "INDOOR", "duration_s": 6.4,
 "gold_transcript": {"roman": "Lahore mein tamatar ka rate kya hai", "urdu": "لاہور میں ٹماٹر کا ریٹ کیا ہے"},
 "paired_text_id": "T-RU-05",
 "input": null, "gold": { "...same as text...": "" }}
```
`condition`: `QUIET`, `INDOOR` (fan/TV), `OUTDOOR` (street/tractor/market). `paired_text_id` is set on the 12
paired notes (§3.2) and the `gold` block must then equal that text item's gold.

### 2.3 Control (`controls.jsonl`)
```json
{"id": "C-SIL-01", "set": "control", "kind": "SILENCE", "audio": "audio/C-SIL-01.ogg",
 "speaker": "S1", "phone": "P1", "duration_s": 5.0,
 "gold": {"outcome": "GRACEFUL_FAIL", "max_tool_calls": 0, "stt_called": false}}
```
`kind`: `SILENCE` (stt_called false: silence pre-check), `MUSIC`, `OTHER_LANGUAGE` (outcome CLARIFY,
clarify_slot `language`), `TOO_LONG` (> 120 s: first 120 s transcribed, bot says so). Pass = 0 invented
requests.

### 2.4 Multi-turn / command (`multiturn.jsonl`)
```json
{"id": "M-FU-02", "set": "multiturn", "category": "CROP_SWITCH",
 "context": [
   {"user": "Okara se 50 mann pyaz kahan bechoon", "state_after": {"intent": "WHERE_TO_SELL", "crop": "ONION",
     "place": {"canonical": "OKARA", "role": "ORIGIN"}, "quantity_kg": 2000, "horizon": null}}],
 "input": "aur tamatar?",
 "gold": {
   "patch": [{"slot": "crop", "op": "set", "raw": "tamatar", "id": "TOMATO"}],
   "state_after": {"intent": "WHERE_TO_SELL", "crop": "TOMATO",
     "place": {"canonical": "OKARA", "role": "ORIGIN"}, "quantity_kg": 2000, "horizon": null},
   "tool": {"name": "best_mandis", "args": {"crop": "TOMATO", "origin": "OKARA", "quantity_kg": 2000}},
   "outcome": "ANSWER", "clarify_slot": null}}
```
`op`: `set`, `add` ("Lahore ka bhi"), `ref` (list position, `"position": 2`), `correct`. For `REFERENCE` items the
context's last turn lists the mandis in order, so position N is checkable. Commands use the same shape with
`intent = ALERT|STOP` and `alert_action`.

## 3. Item matrix

### 3.1 Text: 40 (file 05 §4.1)
| IDs | Category | n | Must include |
|---|---|---|---|
| T-EN-01…06 | English | 6 | one per intent PRICE_NOW / FORECAST / WHERE_TO_SELL at least |
| T-RU-01…12 | Roman Urdu | 12 | spellings "piaz", "timatar", "kro"; "aloo"; number words "sau", "dedh sau" |
| T-MX-01…08 | Mixed EN/RU | 8 | "next week", "best mandi … se" |
| T-UR-01…04 | Urdu script | 4 | place in Urdu script (لاہور, اوکاڑہ) |
| T-AMB-01…06 | Ambiguous | 6 | no crop ("rate batao"); bori ("10 bori pyaz"); unknown place ("Block mandi"); "kal ka rate"; unit missing ("50 pyaz"); two crops in one message |
| T-OOS-01…04 | Out of scope / coverage | 4 | uncovered crop ("kapas"); non-Punjab mandi ("Hyderabad"); agronomy ("fertilizer kab dalun"); general chat ("write a poem") |

Coverage counts over all 40 (checked by a script at 4.4): `quantity` ≥ 12 (mann, kg, ton, bori, number words);
places ≥ 15 incl. aliases and Urdu script; crops ≥ 4 names incl. a Punjabi name; `horizon` ≥ 8
("aaj", "kal", "agle hafte", "February mein"). Intent spread: every intent appears at least twice.

### 3.2 Voice: 30 notes (file 05 §4.2), 6 speakers × 5 notes
Phones: P1 low-end Android, P2 mid Android, P3 iPhone. Conditions per speaker: S1–S4 = 2 QUIET, 2 INDOOR,
1 OUTDOOR; S5–S6 = 2 QUIET, 1 INDOOR, 2 OUTDOOR. Totals: QUIET 12, INDOOR 10, OUTDOOR 8; P1/P2/P3 10 each;
Punjabi-accented 8 (S5, S6). Length 3–45 s. Record **inside WhatsApp** to the test number so the note passes
through the real webhook and media path (needs 5.2), then save as `audio/<id>.ogg`.

| Speaker | Phone | Notes | Category |
|---|---|---|---|
| S1 | P1 | V01–V04, V23 | RU ×4, MIX |
| S2 | P2 | V05–V08, V24 | RU ×4, MIX |
| S3 | P3 | V09–V12, V25 | RU ×4, MIX |
| S4 | P1 | V13–V14, V26–V27, V28 | RU ×2, MIX ×2, AMB |
| S5 (Punjabi accent) | P2 | V15–V18, V29 | PA ×4, AMB |
| S6 (Punjabi accent) | P3 | V19–V22, V30 | PA ×4, AMB |

Category totals: RU 14, PA 8, MIX 5, AMB 3. Each speaker picks which of their 5 notes is OUTDOOR/INDOOR/QUIET
per the counts above; the label records it.

**Paired subset (12):** V01, V02, V05, V06, V09, V10, V13, V15, V19, V23, V24, V28: each speaks an existing
text item (set `paired_text_id`), so the voice-vs-text gap (≤ 7 points) is measured on identical content.

### 3.3 Controls: 5 (not scored in the 30)
C-SIL-01, C-SIL-02 (silent notes, 5 s and 20 s); C-MUS-01 (music clip); C-LANG-01 (Pashto or Sindhi);
C-LONG-01 (> 120 s).

### 3.4 Multi-turn and commands: 30 (file 05 §4.3)
| IDs | Category | n | Example |
|---|---|---|---|
| M-FU-01…04 | CROP_SWITCH | 4 | "aur tamatar?": keep place + quantity |
| M-FU-05…08 | PLACE_SWITCH / ADD | 4 | "Lahore ka?", "Lahore ka bhi batao" |
| M-FU-09…12 | REFERENCE | 4 | "2 number wali ki tafseel" |
| M-FU-13…16 | HORIZON | 4 | "agle hafte?" |
| M-FU-17…20 | CORRECTION | 4 | "nahi, 80 mann"; "nahi, 100 bori" → CLARIFY quantity_unit |
| M-CMD-01…03 | ALERT SUBSCRIBE | 3 | "pyaz Okara 3000 se upar ho to batana" |
| M-CMD-04…06 | ALERT SET_THRESHOLD | 3 | threshold up / down |
| M-CMD-07…08 | ALERT LIST | 2 | "meri alerts dikhao" |
| M-CMD-09…10 | STOP | 2 | "STOP", "band karo" |

## 4. Scoring map (file 05 §5)
| Threshold | Computed from |
|---|---|
| A: critical slots transcribed (≥ 85%, ≥ 90% quiet) | voice: STT output vs `gold_transcript`, critical slot spans only |
| A: invented content on controls = 0 | controls: `max_tool_calls`, `stt_called` |
| B: intent ≥ 95%, critical-slot text ≥ 95% / voice ≥ 90% | `gold.intent`, critical slots in `gold.slots` |
| B: clarify ≥ 90% on AMB / ≤ 10% unneeded | `outcome = CLARIFY` + `clarify_slot` vs all other items |
| B: out-of-scope redirect 100% | T-OOS items: `outcome` |
| C: correct tool ≥ 95%; 0 untooled numbers; 0 forecasts on uncovered | `gold.tool.name`; validator log |
| D: follow-ups ≥ 90% | M-FU: `state_after` exact match |
| E/F: latency, cost | run logs (not in gold) |

## 5. Speakers (≥ 6, named by me; full roster in `speakers.csv`)
Columns: `speaker_id, first_name, age_band, gender, accent, phone, consent_date`. No phone numbers. Consent =
volunteer agrees the recordings are used only for this FYP's benchmark and kept by me; they can ask for deletion.
At least 2 speakers with a Punjabi accent (S5, S6); mixed age bands and genders where possible.
