"""Renderer + grounding validator (task 9.1, RFC C11; file 06 §2, file 09 R-05/R-06, file 10 scenarios). Choices: D-037.

Every fact (rate, range, rupees, mandi name, date) is put in the reply by a template here, from the tool payload.
The LLM may add ONE framing sentence; `compose` validates it (no digits, no number words in Roman / Urdu script /
English, no mandi or place name the payload did not return, no promise/advice words), asks for it once more with
the reasons, and otherwise sends the template alone. Languages: ru = Roman Urdu, ur = Urdu script, en = English.
Every reply carries "Demo data (synthetic)" (A1). Prices arrive in canonical PKR/100 kg and are shown per mann (40 kg).
Choosing the language and sending buttons/lists is the caller's (10.1).
"""
import functools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from mandi.gazetteer import norm, read
from mandi.normalise import number
from mandi.resolve import place_index

LANGS = ("ru", "ur", "en")
SYNTH = "Demo data (synthetic)"
SOURCE = {"SYN": SYNTH, "AMIS": "AMIS Punjab"}
MAX_BODY, MAX_TEXT, MAX_FRAMING = 1024, 4096, 200  # WhatsApp interactive body / text body (file 06 §1); one short sentence
MONTHS = {"ur": "جنوری فروری مارچ اپریل مئی جون جولائی اگست ستمبر اکتوبر نومبر دسمبر".split()}


@dataclass(frozen=True)
class Reply:
    text: str
    buttons: list[dict] = field(default_factory=list)  # [{"id", "title"}], <= 3, title <= 20 (gateway.send_buttons)


# --- formatting ---------------------------------------------------------------------------------------------------------

def per_mann(pkr100kg) -> int:
    """Canonical PKR/100 kg -> whole rupees per mann (40 kg), half up. Golden answers (expected_answers.py) use this too."""
    return int((Decimal(str(pkr100kg)) * Decimal("0.4")).quantize(Decimal(1), ROUND_HALF_UP))


def rs(n: int) -> str:
    """Pakistani grouping: 147000 -> '1,47,000'; 2850 -> '2,850'."""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, s = s[:-3], s[-3:]
        while head:
            head, s = head[:-2], head[-2:] + "," + s
    return ("-" if n < 0 else "") + s


def day(d: date, lang: str) -> str:
    return f"{d.day} {MONTHS['ur'][d.month - 1]}" if lang == "ur" else d.strftime("%d %b").lstrip("0")


@functools.cache
def _crops() -> dict[str, dict]:
    return read()["crops"]


def crop_name(crop_id: str, lang: str) -> str:
    c = _crops()[crop_id]
    return c["name_ur"] if lang == "ur" else c["name_en"] if lang == "en" else c["aliases"]["COMMON"][0].capitalize()


def place_name(place_id: str, lang: str) -> str:
    row = place_index()[1][place_id]
    return row[2] if lang == "ur" else row[1]


def _covered(lang: str) -> str:
    names = [crop_name(c, lang).lower() if lang != "ur" else crop_name(c, lang) for c, v in _crops().items() if v["covered"]]
    joiner = {"ru": " aur ", "en": " and ", "ur": " اور "}[lang]
    return ", ".join(names[:-1]) + joiner + names[-1]


def _reply(text: str, buttons: list[dict] | None = None) -> Reply:
    return Reply(text if SYNTH in text else f"{text}\n{SYNTH}", buttons or [])


# --- templates ----------------------------------------------------------------------------------------------------------

BUTTONS = {
    "price": {"ru": ["Agle din ka andaza", "Kahan bechoon?", "Alert lagayein"],
              "en": ["Next-day forecast", "Where to sell?", "Set an alert"],
              "ur": ["اگلے دن کا اندازہ", "کہاں بیچوں؟", "الرٹ لگائیں"]},
    "f1": {"ru": ["Kahan bechoon?", "Alert lagayein", "Doosri mandi"],
           "en": ["Where to sell?", "Set an alert", "Another mandi"],
           "ur": ["کہاں بیچوں؟", "الرٹ لگائیں", "دوسری منڈی"]},
    "f2": {"ru": ["1 ki tafseel", "Transport badlein", "Alert lagayein"],
           "en": ["Details of 1", "Change transport", "Set an alert"],
           "ur": ["1 کی تفصیل", "ٹرانسپورٹ بدلیں", "الرٹ لگائیں"]},
    "bori": {"ru": ["50 kg", "100 kg", "Doosra"], "en": ["50 kg", "100 kg", "Other"], "ur": ["50 کلو", "100 کلو", "دوسرا"]},
}
BUTTON_IDS = {"price": ["F1", "F2", "ALERT"], "f1": ["F2", "ALERT", "OTHER_MANDI"], "f2": ["DETAIL_1", "TRANSPORT", "ALERT"],
              "bori": ["BAG_50", "BAG_100", "BAG_OTHER"]}


def _buttons(kind: str, lang: str) -> list[dict]:
    return [{"id": i, "title": t} for i, t in zip(BUTTON_IDS[kind], BUTTONS[kind][lang], strict=True)]


def _range(lo, hi, lang: str, kg: bool = False) -> str:
    """'Rs 2,850–3,000 fi mann' (+ ' (40 kg)' on the price line, file 06 §2.1); one value when only one is known."""
    vals = [per_mann(v) for v in (lo, hi) if v is not None]
    r = "–".join(rs(v) for v in dict.fromkeys(vals))
    out = {"ru": f"Rs {r} fi mann", "en": f"Rs {r} per mann", "ur": f"{r} روپے فی من"}[lang]
    return out + {"ru": " (40 kg)", "en": " (40 kg)", "ur": " (40 کلو)"}[lang] if kg else out


def _price_block(p, lang: str) -> str:
    """p: mandi.price.Price. Scenario 1 line: crop · mandi · range · date · source; stale line per file 06 §2.1."""
    if p.min_pkr100kg is not None and p.max_pkr100kg is not None:
        lo, hi = p.min_pkr100kg, p.max_pkr100kg
    else:  # price_obs keeps at least one of the three
        lo, hi = next(v for v in (p.avg_pkr100kg, p.min_pkr100kg, p.max_pkr100kg) if v is not None), None
    text = (f"{crop_name(p.crop_id, lang)} · {place_name(p.mandi_id, lang)} · {_range(lo, hi, lang, kg=True)}"
            f" · {day(p.market_date, lang)} · {SOURCE.get(p.source, p.source)}")
    if p.stale:
        d = day(p.market_date, lang)
        text += {"ru": f"\nTaaza rate nahi mila; aakhri rate {d} ka hai.", "en": f"\nNo fresh rate; the last rate is from {d}.",
                 "ur": f"\nتازہ ریٹ نہیں ملا؛ آخری ریٹ {d} کا ہے۔"}[lang]
    return text


def price(p, lang: str, crop_id: str | None = None, mandi_id: str | None = None) -> Reply:
    """PRICE_NOW. p = mandi.price.price_now(...); None -> the 'no rate' line (crop_id/mandi_id name it)."""
    if p is None:
        c, m = crop_name(crop_id, lang), place_name(mandi_id, lang)
        return _reply({"ru": f"{c} · {m}: is mandi ka taaza rate abhi maujood nahi.", "en": f"{c} · {m}: no rate for this mandi yet.",
                       "ur": f"{c} · {m}: اس منڈی کا تازہ ریٹ ابھی موجود نہیں۔"}[lang])
    return _reply(_price_block(p, lang), _buttons("price", lang))


REASONS = {  # shortcut: provisional codes until C9 (11.2) fixes the list; an unknown code is left out, never guessed
    "ARRIVALS_HIGH": {"ru": "mandi mein aamad zyada hai", "en": "arrivals are high", "ur": "منڈی میں آمد زیادہ ہے"},
    "ARRIVALS_LOW": {"ru": "mandi mein aamad kam hai", "en": "arrivals are low", "ur": "منڈی میں آمد کم ہے"},
    "SEASON_LOW": {"ru": "fasal ki aamad ka mausam hai", "en": "harvest season", "ur": "فصل کی آمد کا موسم ہے"},
    "RECENT_RISE": {"ru": "pichle dinon rate barha hai", "en": "prices rose recently", "ur": "پچھلے دنوں ریٹ بڑھا ہے"},
    "RECENT_FALL": {"ru": "pichle dinon rate gira hai", "en": "prices fell recently", "ur": "پچھلے دنوں ریٹ گرا ہے"},
}


def forecast(f: dict, lang: str) -> Reply:
    """F1. f: one forecast-table row + h: {crop_id, mandi_id, h, p10, p50, p90, reasons[]} (PKR/100 kg)."""
    c, m, h = crop_name(f["crop_id"], lang), place_name(f["mandi_id"], lang), f["h"]
    span = {"ru": "agle din ka andaza" if h == 1 else f"agle {h} din ka andaza",
            "en": "forecast for tomorrow" if h == 1 else f"forecast for the next {h} days",
            "ur": "اگلے دن کا اندازہ" if h == 1 else f"اگلے {h} دن کا اندازہ"}[lang]
    mid = per_mann(f["p50"])
    line = {"ru": f"{_range(f['p10'], f['p90'], lang)} (80% andaza) · beech ka andaza Rs {rs(mid)}",
            "en": f"{_range(f['p10'], f['p90'], lang)} (80% range) · middle estimate Rs {rs(mid)}",
            "ur": f"{_range(f['p10'], f['p90'], lang)} (80% اندازہ) · درمیانی اندازہ {rs(mid)} روپے"}[lang]
    why = [REASONS[r][lang] for r in f.get("reasons", []) if r in REASONS]
    text = f"{c} · {m} · {span}\n{line}"
    if why:
        text += "\n" + {"ru": "Wajah: ", "en": "Why: ", "ur": "وجہ: "}[lang] + " · ".join(why)
    text += "\n" + {"ru": "Ye andaza hai, waada nahi.", "en": "This is an estimate, not a promise.",
                     "ur": "یہ اندازہ ہے، وعدہ نہیں۔"}[lang]
    return _reply(f"{text} · {SYNTH}", _buttons("f1", lang))


def no_forecast(p, lang: str, crop_id: str, mandi_id: str) -> Reply:
    """Coverage gate closed (scenario 5e): 'data kaafi nahi' + the latest rate with its date (or the no-rate line)."""
    head = {"ru": "Is mandi ka andaza dene ke liye data kaafi nahi; taaza rate ye hai:",
            "en": "Not enough data to forecast this mandi; here is the latest rate:",
            "ur": "اس منڈی کا اندازہ دینے کے لیے ڈیٹا کافی نہیں؛ تازہ ریٹ یہ ہے:"}[lang]
    rest = price(p, lang, crop_id, mandi_id)
    return _reply(f"{head}\n{rest.text}", rest.buttons)


def where_to_sell(w: dict, lang: str) -> Reply:
    """F2 (RFC §6, file 06 §2.3). w: {crop_id, origin_id, quantity_mann, nearest_id, transport_per_mann, km, commission_pct,
    rows: [{mandi_id, p10, p90 (PKR/100 kg), net (rupees), gain_vs_nearest (rupees)}] best first, run_id}."""
    c, o = crop_name(w["crop_id"], lang), place_name(w["origin_id"], lang)
    q = rs(w["quantity_mann"])
    lines = [{"ru": f"{c} · {q} mann · {o} se", "en": f"{c} · {q} mann · from {o}", "ur": f"{c} · {q} من · {o} سے"}[lang]]
    for i, r in enumerate(w["rows"][:3], 1):
        after = {"ru": f"kharche ke baad ≈ Rs {rs(r['net'])}", "en": f"after costs ≈ Rs {rs(r['net'])}",
                 "ur": f"خرچے کے بعد ≈ {rs(r['net'])} روپے"}[lang]
        lines.append(f"{i}. {place_name(r['mandi_id'], lang)}: {_range(r['p10'], r['p90'], lang)} · {after}")
    best, near = w["rows"][0], place_name(w["nearest_id"], lang)
    if best["mandi_id"] == w["nearest_id"]:  # the P10 risk rule kept the nearest mandi on top
        lines.append({"ru": f"Nazdeeki mandi ({near}) theek hai: door jaane ka faida yaqeeni nahi.",
                      "en": f"The nearest mandi ({near}) is fine: going further has no sure gain.",
                      "ur": f"نزدیکی منڈی ({near}) ٹھیک ہے: دور جانے کا فائدہ یقینی نہیں۔"}[lang])
    else:
        b, g = place_name(best["mandi_id"], lang), rs(best["gain_vs_nearest"])
        lines.append({"ru": f"{b} nazdeeki mandi se ≈ Rs {g} zyada deti hai, transport ke baad bhi.",
                      "en": f"{b} pays ≈ Rs {g} more than the nearest mandi, even after transport.",
                      "ur": f"{b} نزدیکی منڈی سے ≈ {g} روپے زیادہ دیتی ہے، ٹرانسپورٹ کے بعد بھی۔"}[lang])
    t, km, cm = rs(w["transport_per_mann"]), rs(w["km"]), w["commission_pct"]
    lines.append({"ru": f"Kharche: transport Rs {t}/mann ({km} km), commission {cm}%",
                  "en": f"Costs: transport Rs {t}/mann ({km} km), commission {cm}%",
                  "ur": f"خرچے: ٹرانسپورٹ {t} روپے فی من ({km} کلومیٹر)، کمیشن {cm}%"}[lang])
    return _reply("\n".join(lines) + f" · {SYNTH}", _buttons("f2", lang))


def clarify(slot: str, lang: str, candidates: list[str] | None = None) -> Reply:
    """One question for the first missing slot (parser clarify_slot): crop, place (candidates = AMBIGUOUS place ids),
    quantity, quantity_unit ('bori' without weight), horizon."""
    if slot == "place" and candidates:
        q = {"ru": "Kaunsi jagah?", "en": "Which place?", "ur": "کون سی جگہ؟"}[lang]
        return _reply(q, [{"id": f"PLACE:{p}", "title": place_name(p, lang)} for p in candidates[:3]])
    if slot == "crop":
        crops = [c for c, v in _crops().items() if v["covered"]]
        q = {"ru": "Kaunsi fasal?", "en": "Which crop?", "ur": "کون سی فصل؟"}[lang]
        return _reply(q, [{"id": f"CROP:{c}", "title": crop_name(c, lang)} for c in crops[:3]])
    if slot == "quantity_unit":
        q = {"ru": "Ek bori kitne kg ki hai?", "en": "How many kg is one bag?", "ur": "ایک بوری کتنے کلو کی ہے؟"}[lang]
        return _reply(q, _buttons("bori", lang))
    text = {
        "place": {"ru": "Kis shehar ya mandi ka? Shehar ka naam likhein ya location bhejein.",
                  "en": "Which city or mandi? Type the city name or send your location.",
                  "ur": "کس شہر یا منڈی کا؟ شہر کا نام لکھیں یا لوکیشن بھیجیں۔"},
        "quantity": {"ru": "Kitna maal hai? Maslan 50 mann.", "en": "How much do you have? For example 50 mann.",
                     "ur": "کتنا مال ہے؟ مثلاً 50 من۔"},
        "horizon": {"ru": "Kitne din aage ka andaza chahiye? Kal, 3 din ya agle hafte?",
                    "en": "How many days ahead? Tomorrow, 3 days or next week?",
                    "ur": "کتنے دن آگے کا اندازہ چاہیے؟ کل، 3 دن یا اگلے ہفتے؟"},
    }[slot]
    return _reply(text[lang])


def out_of_coverage(lang: str) -> Reply:
    """Crop or place outside coverage (scenarios 5a, 5b): no number."""
    cov = _covered(lang)
    return _reply({"ru": f"Abhi sirf Punjab ki mandiyan aur {cov}.", "en": f"For now only Punjab mandis and {cov}.",
                   "ur": f"ابھی صرف پنجاب کی منڈیاں اور {cov}۔"}[lang])


SCOPE = {"ru": "Main sirf mandi ke rate, andaza aur kahan bechna hai, in ke baare mein bata sakta hoon.",
         "en": "I can only help with mandi rates, forecasts and where to sell.",
         "ur": "میں صرف منڈی کے ریٹ، اندازے اور کہاں بیچنا ہے، ان کے بارے میں بتا سکتا ہوں۔"}


def out_of_scope(lang: str) -> Reply:
    """Advice, chat or anything outside the closed intent set (scenario 5d; R-05)."""
    return _reply(SCOPE[lang])


def unknown(lang: str) -> Reply:
    """The fixed 'maloomat nahi' path: a question no tool can answer."""
    head = {"ru": "Ye maloomat mere paas nahi.", "en": "I don't have this information.", "ur": "یہ معلومات میرے پاس نہیں۔"}[lang]
    return _reply(f"{head} {SCOPE[lang]}")


# First contact, before the farmer's language is known, so all three languages (file 07 §3). Kept word for word with the
# live Roman Urdu / English text; the Urdu-script paragraph says the same.
CONSENT_TEXT = (
    "MandiSaathi: FAST-NUCES ka student project. Yeh AI assistant hai; rates sirf andaza hain. "
    "Hum aap ka number (encrypted) aur paighamaat 90 din tak rakhte hain. Band karne ke liye \"STOP\" likhein. "
    "Demo data (synthetic).\n"
    "منڈی ساتھی: FAST-NUCES کا اسٹوڈنٹ پراجیکٹ۔ یہ اے آئی اسسٹنٹ ہے؛ ریٹ صرف اندازہ ہیں۔ "
    "ہم آپ کا نمبر (خفیہ) اور پیغامات 90 دن تک رکھتے ہیں۔ بند کرنے کے لیے \"STOP\" لکھیں۔\n"
    "MandiSaathi is an AI assistant from a FAST-NUCES student project. Prices are estimates. "
    "We keep your number (encrypted) and messages for 90 days. Send STOP to opt out. Demo data (synthetic)."
)
STOP_TEXT = (
    "Aap ka data mita diya gaya hai; ab koi paigham nahi aaye ga. Dobara shuru karne ke liye koi bhi paigham bhejein.\n"
    "Your data has been deleted and you will get no more messages. Send any message to start again."
)


# --- grounding validator (LLM framing text only; never the template facts) ----------------------------------------------

_NUM_WORDS = {*"one two three four five six seven eight nine ten eleven twelve fifteen twenty thirty forty fifty sixty seventy "
              "eighty ninety hundred thousand lakh lac million crore dozen half".split(),
              *(norm(w) for w in "ایک دو تین چار پانچ چھ سات آٹھ نو دس بیس پچاس سو ہزار لاکھ کروڑ".split()),
              *(norm(w) for w in "آدھا ڈیڑھ ڈھائی سوا ساڑھے پونے".split())}
_PROMISE = [norm(p).split() for p in (
    "zaroor", "zarur", "pakka", "pakki", "pakke", "guarantee", "guaranteed", "garanti", "munafa hoga", "yaqeenan",
    "definitely", "promise", "certainly", "sure profit",
    "ضرور", "پکا", "پکی", "گارنٹی", "منافع ہوگا", "یقیناً")]


def validate(text: str, allowed: set[str] = frozenset()) -> list[str]:
    """Reasons to reject one LLM framing sentence (empty list = OK). allowed = place/mandi ids the tool payload returned."""
    reasons = set()
    if re.search(r"\d", text):  # str regex: \d also matches Urdu (۰-۹) and Arabic-Indic digits
        reasons.add("DIGIT")
    toks = norm(text).split()
    # R-06: the parser's own number-word normaliser, so "teen hazaar" / "do sau" fail here exactly as they parse
    for t in toks:
        if not re.search(r"\d", t) and (t in _NUM_WORDS or number(t) is not None):  # digits: DIGIT above
            reasons.add(f"NUMBER_WORD:{t}")
    aliases = place_index()[0]
    for n in range(1, 5):
        for i in range(len(toks) - n + 1):
            span = toks[i:i + n]
            if span in _PROMISE:
                reasons.add(f"PROMISE:{' '.join(span)}")
            ids = aliases.get(" ".join(span))
            if ids and not ids & allowed:
                reasons.add(f"UNKNOWN_PLACE:{' '.join(span)}")
    if "\n" in text.strip() or len(text) > MAX_FRAMING:
        reasons.add("NOT_ONE_SENTENCE")
    return sorted(reasons)


Framing = Callable[[list[str] | None], str | None]


def compose(facts: Reply, framing: Framing | None, allowed: set[str] = frozenset()) -> tuple[Reply, dict]:
    """Framing sentence + facts. framing(reasons) returns one sentence (reasons = None first, then the rejection reasons);
    one regeneration at most, then the template alone. Never raises. Returns (reply, validator_result as JSON)."""
    attempts, reasons = [], None
    for _ in range(2):
        if framing is None:
            break
        try:
            s = framing(reasons)
        except Exception as e:  # an LLM error or timeout must not lose the reply
            attempts.append({"error": type(e).__name__})
            break
        if not s or not s.strip():
            break
        s = s.strip()
        reasons = validate(s, allowed)
        if not reasons and len(s) + 1 + len(facts.text) > (MAX_BODY if facts.buttons else MAX_TEXT):
            reasons = ["TOO_LONG_WITH_FACTS"]
        attempts.append({"text": s[:MAX_FRAMING], "reasons": reasons})
        if not reasons:
            return Reply(f"{s}\n{facts.text}", facts.buttons), {"used": "llm", "attempts": attempts}
    return facts, {"used": "template_only", "attempts": attempts}
