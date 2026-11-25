"""Input normalisers (task 5.4, file 03 §5 "D5", benchmark SPEC §2.5). Pure functions, no DB, no network.

The parser (7.1) and resolver (6.1) hand raw spans here and get back structured values that line up with the benchmark
gold contract: a quantity's `unit`/`value_kg`, a number's Decimal value, and a `horizon` in one of the SPEC shapes. The
renderer's validator (9.1) reuses the number-word vocabulary to catch an LLM that wrote a number in words.

Rules (file 03 §5): mann/maund/man/من = 40 kg (farmer default), kg/kilo/کلو = 1, ton/tonne = 1000; bori/bag/بوری
"always ask" unless the crop records a standard bag; number words sau=100, hazaar=1,000, lakh=100,000, dedh=1.5,
dhai=2.5, sawa X=X+0.25, saade X=X+0.5, paune X=X−0.25; dates in PKT, "kal" ambiguous unless a future verb marks it.
Anything outside the grammar returns None (the caller asks) — a normaliser never guesses a number. Choices: D-025.
"""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import NamedTuple

from mandi.gazetteer import norm  # NFKC + casefold + Urdu letter folding; reused so aliases and spans fold the same way

PKT = timezone(timedelta(hours=5))  # Pakistan is +05:00 year-round (no DST), so a fixed offset avoids tzdata (D-014)

# Arabic-Indic (U+0660–0669) and Extended Arabic-Indic / Urdu (U+06F0–06F9) digits -> ASCII. NFKC does not do this.
_DIGITS = {c: str(i) for i in range(10) for c in (chr(0x0660 + i), chr(0x06F0 + i))}


def _fold_digits(s: str) -> str:
    return s.translate(str.maketrans(_DIGITS))


def _tidy(d: Decimal) -> Decimal:
    """Drop a trailing '.0' so whole numbers serialise as 150, not 150.0 (gold JSON uses ints). 3.25 stays 3.25."""
    return d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize()


# --- number words (roman; Urdu-script numbers come in as digits) ------------------------------------------------------
_INT = {"ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "panch": 5, "paanch": 5,
        "che": 6, "chhe": 6, "cheh": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "dus": 10,
        "bees": 20, "pachas": 50, "pachaas": 50}
_HALF = {"dedh": Decimal("1.5"), "derh": Decimal("1.5"), "dhai": Decimal("2.5"), "adha": Decimal("0.5")}
_MOD = {"sawa": Decimal("0.25"), "saade": Decimal("0.5"), "sadhe": Decimal("0.5"), "saadhe": Decimal("0.5"), "paune": Decimal("-0.25")}
_SCALE = {"sau": 100, "so": 100, "hazaar": 1000, "hazar": 1000, "hazzar": 1000, "lakh": 100_000, "lac": 100_000}
# exported for the 9.1 validator (to reject an LLM reply that wrote a number in words)
NUMBER_WORDS = set(_INT) | set(_HALF) | set(_MOD) | set(_SCALE)


def _words_to_number(tokens: list[str]) -> Decimal | None:
    """[<sawa|saade|paune>] [<int|dedh|dhai>] [<sau|hazaar|lakh>]. Leftover or unknown tokens -> None (never a wrong number)."""
    toks = list(tokens)
    if not toks:
        return None
    mod = _MOD.get(toks[0])
    if mod is not None:
        toks.pop(0)
    head: Decimal | None = None
    if toks and toks[0] in _HALF:
        head = _HALF[toks.pop(0)]
    elif toks and toks[0] in _INT:
        head = Decimal(_INT[toks.pop(0)])
    if mod is not None:
        head = (Decimal(1) if head is None else head) + mod  # "sawa teen"=3.25; "sawa sau" -> head 1.25 then ×100
    scale = _SCALE.get(toks[0]) if toks else None
    if scale is not None:
        toks.pop(0)
    if toks:  # anything left is unknown -> refuse
        return None
    if head is None:
        return Decimal(scale) if scale is not None else None  # bare "sau" = 100
    return head * scale if scale is not None else head


def number(text: str) -> Decimal | None:
    """A span like '3000', '3,000', '۳۰۰۰', '1.5', 'das', 'dedh sau' -> its value, or None if there is no number."""
    s = _fold_digits(text).strip()
    s = re.sub(r"(?<=\d),(?=\d)", "", s)  # drop thousands separators
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return _tidy(Decimal(s))
    words = _words_to_number(norm(s).split())  # norm() drops '.', so only the word path reaches here
    return _tidy(words) if words is not None else None


# --- units ------------------------------------------------------------------------------------------------------------
_UNIT_ALIASES = {
    "MANN": ["mann", "maund", "man", "mn", "manns", "maunds", "من"],
    "KG": ["kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "کلو", "کلوگرام"],
    "TON": ["ton", "tons", "tonne", "tonnes", "ٹن"],
    "BORI": ["bori", "boori", "bora", "boray", "borian", "bag", "bags", "بوری", "بوریاں"],
}
_UNIT_LOOKUP = {norm(a): u for u, aliases in _UNIT_ALIASES.items() for a in aliases}
_UNIT_FACTOR_KG = {"MANN": Decimal(40), "KG": Decimal(1), "TON": Decimal(1000)}  # BORI/NONE have no fixed factor


def unit(text: str) -> str | None:
    """A unit word -> MANN / KG / TON / BORI, or None if unknown. Matches the whole span after normalisation."""
    return _UNIT_LOOKUP.get(norm(text))


class Quantity(NamedTuple):
    value: Decimal | None   # the number said (50, 1.5, 150 …), or None if only a unit was given
    unit: str               # MANN / KG / TON / BORI / NONE  (NONE = a number with no unit)
    value_kg: Decimal | None  # SPEC: value×40 / ×1 / ×1000; None for BORI and NONE
    ask: bool               # True when the caller must clarify before using it
    reason: str | None      # "NO_UNIT" or "BAG_WEIGHT" when ask, else None


def quantity(text: str, default_bag_kg: int | None = None) -> Quantity | None:
    """Parse '<number> <unit>' from a raw span. None if neither a number nor a unit is present.

    'bori' (and a bare number with no unit) sets ask=True unless a crop bag weight resolves it (file 03 §5).
    """
    s = re.sub(r"(?<=\d),(?=\d)", "", _fold_digits(text))
    m = re.search(r"\d+(?:\.\d+)?", s)
    value: Decimal | None
    if m:  # a digit literal: keep its decimals (norm() would drop the '.'), take the unit from the rest
        value = Decimal(m.group())
        found = next((_UNIT_LOOKUP[t] for t in norm(s[: m.start()] + " " + s[m.end():]).split() if t in _UNIT_LOOKUP), None)
    else:  # words only: split a unit token out, parse the rest as a number phrase
        toks = norm(s).split()
        idx = next((i for i, t in enumerate(toks) if t in _UNIT_LOOKUP), None)
        found = _UNIT_LOOKUP[toks[idx]] if idx is not None else None
        value = _words_to_number(toks[:idx] + toks[idx + 1:] if idx is not None else toks)

    value = _tidy(value) if value is not None else None
    if found is None:
        if value is None:
            return None  # nothing quantity-like here
        return Quantity(value, "NONE", None, True, "NO_UNIT")
    if found == "BORI":
        if default_bag_kg and value is not None:
            return Quantity(value, "BORI", _tidy(value * default_bag_kg), False, None)
        return Quantity(value, "BORI", None, True, "BAG_WEIGHT")
    kg = _tidy(value * _UNIT_FACTOR_KG[found]) if value is not None else None
    return Quantity(value, found, kg, False, None)


# --- dates / horizons (PKT) -------------------------------------------------------------------------------------------
_TODAY = {norm(w) for w in ("aaj", "aj", "today", "آج")}
_KAL = {norm(w) for w in ("kal", "کل")}
_PARSON = {norm(w) for w in ("parson", "پرسوں")}
_NEXT_WEEK = [norm(p) for p in ("agle hafte", "aglay hafte", "agle haftay", "next week", "اگلے ہفتے")]
_MONTHS = {
    1: ("january", "jan", "جنوری"), 2: ("february", "feb", "فروری"), 3: ("march", "mar", "مارچ"),
    4: ("april", "apr", "اپریل"), 5: ("may", "مئی"), 6: ("june", "jun", "جون"), 7: ("july", "jul", "جولائی"),
    8: ("august", "aug", "اگست"), 9: ("september", "sep", "sept", "ستمبر"), 10: ("october", "oct", "اکتوبر"),
    11: ("november", "nov", "نومبر"), 12: ("december", "dec", "دسمبر"),
}
_MONTH_LOOKUP = {norm(a): m for m, aliases in _MONTHS.items() for a in aliases}


def _now_pkt(now: datetime | date | None) -> date:
    if now is None:
        return datetime.now(PKT).date()
    if isinstance(now, datetime):
        return (now if now.tzinfo else now.replace(tzinfo=PKT)).astimezone(PKT).date()
    return now


def horizon(text: str, now: datetime | date | None = None, future: bool | None = None) -> dict | None:
    """Date phrase -> a benchmark horizon dict, or None if there is no date token.

    SPEC: aaj -> TODAY; agle hafte/next week -> DAYS h=7; a month name -> the next such month after `now`;
    "kal"/"parson" need tense (`future=True` -> DAYS h=1/2) and are AMBIGUOUS on their own ("kal ka rate").
    """
    n = norm(text)
    tokens = set(n.split())
    if tokens & _TODAY:
        return {"kind": "TODAY"}
    if any(p and p in n for p in _NEXT_WEEK):
        return {"kind": "DAYS", "h": 7}
    if tokens & _KAL:
        return {"kind": "DAYS", "h": 1} if future else {"kind": "AMBIGUOUS"}
    if tokens & _PARSON:
        return {"kind": "DAYS", "h": 2} if future else {"kind": "AMBIGUOUS"}
    for tok in tokens:
        if tok in _MONTH_LOOKUP:
            ref = _now_pkt(now)
            month = _MONTH_LOOKUP[tok]
            year = ref.year if month >= ref.month else ref.year + 1  # the next such month on/after the reference month
            return {"kind": "MONTH", "month": f"{year:04d}-{month:02d}"}
    return None
