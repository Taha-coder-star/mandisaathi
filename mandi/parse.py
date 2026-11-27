"""Rule-based parser (task 7.1; file 05 §3, RFC C6 + §3 steps 4-6 + §9 "Deterministic"; DECISIONS.md D-031).

Pure library: no DB, no LLM, no new dependency. `parse(text)` returns exactly the benchmark gold shape
(SPEC §2.1/§2.5), so scoring is a field-by-field comparison. It reuses the 6.1 resolvers (`mandi.resolve`) and the
5.4 normalisers (`mandi.normalise`); the parser's own job is finding crop/place/quantity spans in a whole message
and choosing intent / outcome / tool. Wiring into handle_turn, the LLM fallback and reply text are later tasks.

Algorithm (file 05 §3.3): STOP -> span finding (exact alias longest-first, fuzzy only on long leftover tokens)
-> quantity -> horizon -> intent (first match wins) -> outcome/clarify (SPEC §2.5) -> tool (ANSWER only).
Where the handoff's suggested keywords disagree with SPEC/gold, SPEC and the gold win (recorded in D-031).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from mandi.gazetteer import norm
from mandi.normalise import horizon as _horizon
from mandi.normalise import number as _number
from mandi.normalise import quantity as _quantity
from mandi.normalise import unit as _unit
from mandi.resolve import resolve_crop, resolve_place

# whole message only; benchmark T-EN-05, T-RU-12. One source of truth: app.handlers imports this set (handoff §3.2).
STOP_WORDS = {"stop", "band karo", "بند کرو"}

PLACE_INTENTS = ("PRICE_NOW", "FORECAST", "WHERE_TO_SELL", "ALERT")  # intents that require a resolved place


def _kw(*words: str) -> list[str]:
    """Normalise keyword/phrase triggers so roman and Urdu-script forms fold the same way a span does (D-031 §1)."""
    return [norm(w) for w in words]


_STOP_NORM = {norm(w) for w in STOP_WORDS}
_PRICE = _kw("rate", "bhaao", "bhao", "price", "qeemat", "ریٹ", "بھاؤ")
_FORECAST_KW = _kw("forecast")
_OUTLOOK_KW = _kw("outlook")
_HELP = _kw("help", "madad", "kaise use", "kaise istemal")
# WHERE_TO_SELL: a sell-verb stem, or a "where to sell" phrase. Adds "kahan milega" (T-MX-03/V24) which the handoff
# keyword list misses (D-031 §2); the بیچ stem covers the Urdu-script T-UR-03.
_SELL_STEMS = ("bech", "sell", "bhej", norm("بیچ"))
_WHERE_PHRASES = _kw("best mandi", "kis mandi", "kaun si mandi", "kaunsi mandi", "kahan le jaun", "kahan milega", "kithay")
_FUTURE = {*_kw("hoga", "hogi", "hoge", "rahega", "rahegi", "will", "ہوگا", "ہوگی")}  # tense hint for "kal"/"parson"
_ABOVE = {*_kw("upar", "above", "اوپر")}
_BELOW = {*_kw("neeche", "niche", "below", "نیچے")}
# function words that precede "mandi" without being a place, so "kis mandi" is not read as an unknown place
_NOT_PLACE = {*_kw("kis", "kaun", "kaunsi", "konsi", "best", "is", "us", "ye", "yeh",
                   "wo", "woh", "koi", "har", "meri", "apni", "nearest")}
_EDGE = " \t\r\n،,.?!؟:;\"'()[]"


def _words(text: str) -> list[tuple[str, int, int]]:
    """Whitespace tokens as (text, start, end), so a matched span's raw is an exact substring of the input."""
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _raw(text: str, i: int, j: int, words: list[tuple[str, int, int]]) -> str:
    """Original substring spanning words[i..j] (inclusive), trimmed of edge punctuation."""
    return text[words[i][1]:words[j][2]].strip(_EDGE)


def _find(text: str, words: list[tuple[str, int, int]], resolver, used: list[bool], max_n: int) -> list[tuple]:
    """Exact-alias spans, longest n-gram first, each token used once (handoff §3.3). Returns (raw, Resolution, i)."""
    hits = []
    for n in range(max_n, 0, -1):
        for i in range(len(words) - n + 1):
            if any(used[i:i + n]):
                continue
            raw = _raw(text, i, i + n - 1, words)
            if not raw:
                continue
            r = resolver(raw)
            if r.exact and r.status != "UNKNOWN":
                for k in range(i, i + n):
                    used[k] = True
                hits.append((raw, r, i))
    hits.sort(key=lambda h: h[2])
    return hits


def _fuzzy(text: str, words: list[tuple[str, int, int]], resolver, used: list[bool]) -> tuple | None:
    """Fuzzy fill for a still-empty slot: a single leftover token >= 4 chars resolving to one target (not AMBIGUOUS).

    Guarded so a long function word ("kahan" ~ "khan") never invents an AMBIGUOUS place (D-019 short-alias risk).
    """
    for i in range(len(words)):
        if used[i]:
            continue
        raw = _raw(text, i, i, words)
        if len(norm(raw)) < 4:
            continue
        r = resolver(raw)
        if not r.exact and r.status in ("RESOLVED", "OUT_OF_COVERAGE"):
            used[i] = True
            return raw, r, i
    return None


def _mandi_marker(text: str, words: list[tuple[str, int, int]], used: list[bool]) -> str | None:
    """A "<word> mandi" whose <word> did not resolve -> that word is an UNKNOWN place (T-AMB-03 "Block mandi")."""
    for i, w in enumerate(words):
        if norm(w[0]) == "mandi" and i > 0 and not used[i - 1]:
            prev = _raw(text, i - 1, i - 1, words)
            if prev and norm(prev) not in _NOT_PLACE and resolve_place(prev).status == "UNKNOWN":
                return prev
    return None


def _num(d: Decimal | int | None):
    """Decimal -> int when whole (gold uses ints), else float; None stays None."""
    if d is None:
        return None
    d = d if isinstance(d, Decimal) else Decimal(d)
    return int(d) if d == d.to_integral_value() else float(d)


def _is_number(token: str) -> bool:
    return _number(token) is not None


def _quantity_slot(text: str, words: list[tuple[str, int, int]], crop_hits: list[tuple], used: list[bool]) -> dict | None:
    """A quantity is a number-phrase + unit, or a bare number directly before a crop (SPEC §2.5; handoff §3.3).

    Only a span that yields a number is accepted, so a bare unit or Punjabi "ton" (="from") is never a quantity.
    """
    def build(i: int, j: int) -> dict | None:
        raw = _raw(text, i, j, words)
        q = _quantity(raw)
        if q is None or q.value is None:
            return None
        return {"raw": raw, "value": _num(q.value), "unit": q.unit, "value_kg": _num(q.value_kg)}

    for i, w in enumerate(words):  # unit token with the number phrase right before it
        if used[i] or _unit(w[0]) is None:
            continue
        j = i
        while j - 1 >= 0 and _is_number(words[j - 1][0]):
            j -= 1
        if (slot := build(j, i)) is not None:
            return slot
    for _raw_c, _r, ci in crop_hits:  # a bare number directly before a crop (no unit) -> ask (T-AMB-05 "50 pyaz")
        if ci - 1 >= 0 and _is_number(words[ci - 1][0]):
            j = ci - 1
            while j - 1 >= 0 and _is_number(words[j - 1][0]):
                j -= 1
            if (slot := build(j, ci - 1)) is not None:
                return slot
    return None


def _direction(nt: list[str]) -> str | None:
    if any(t in _ABOVE for t in nt):
        return "ABOVE"
    if any(t in _BELOW for t in nt):
        return "BELOW"
    return None


def _threshold(words: list[tuple[str, int, int]], nt_dir: set[str]) -> int | None:
    """The number nearest a direction word (alert items carry exactly one number and no quantity)."""
    dirs = [i for i, w in enumerate(words) if norm(w[0]) in nt_dir]
    nums = [(i, _number(w[0])) for i, w in enumerate(words) if _number(w[0]) is not None]
    if not dirs or not nums:
        return None
    i, v = min(nums, key=lambda p: min(abs(p[0] - d) for d in dirs))
    return _num(v)


def _intent(n: str, nt: list[str], horizon: dict | None, direction: str | None, has_number: bool) -> str:
    """First match wins (file 05 §3.3): STOP (handled earlier) -> ALERT -> WHERE_TO_SELL -> OUTLOOK -> FORECAST
    -> PRICE_NOW -> HELP -> OTHER. FORECAST needs a *future* DAYS horizon, so an AMBIGUOUS "kal" stays PRICE_NOW."""
    if direction and has_number:
        return "ALERT"
    if any(t.startswith(_SELL_STEMS) for t in nt) or any(p in n for p in _WHERE_PHRASES):
        return "WHERE_TO_SELL"
    if (horizon and horizon["kind"] == "MONTH") or any(k in n for k in _OUTLOOK_KW):
        return "OUTLOOK"
    if (horizon and horizon["kind"] == "DAYS") or any(k in n for k in _FORECAST_KW):
        return "FORECAST"
    if any(k in n for k in _PRICE):
        return "PRICE_NOW"
    if any(k in n for k in _HELP):
        return "HELP"
    return "OTHER"


def _crop_id(r, intent: str) -> str:
    """Map a resolver result to a gold crop id: WHEAT only answers under OUTLOOK; other uncovered crops -> OUT_OF_COVERAGE."""
    if r.status == "OUT_OF_COVERAGE":
        if r.ids[0] == "WHEAT":
            return "WHEAT" if intent == "OUTLOOK" else "OUT_OF_COVERAGE"
        return "OUT_OF_COVERAGE"
    return r.ids[0]


def _place_slot(place_hit: tuple | None, marker: str | None, intent: str) -> dict | None:
    role = "ORIGIN" if intent == "WHERE_TO_SELL" else "MANDI"
    if place_hit is not None:
        raw, r, _ = place_hit
        canonical = r.ids[0] if r.status != "UNKNOWN" and r.ids else None
        return {"raw": raw, "canonical": canonical, "status": r.status, "role": role}
    if marker is not None:
        return {"raw": marker, "canonical": None, "status": "UNKNOWN", "role": role}
    return None


def _clarify(intent: str, crop_ids: list[str], place: dict | None, quantity: dict | None, horizon: dict | None) -> str | None:
    """First missing required slot, in the order crop, place, quantity_unit, horizon (SPEC §2.5)."""
    place_ok = place is not None and place["status"] == "RESOLVED"
    if not crop_ids:
        return "crop"
    if intent in PLACE_INTENTS and not place_ok:
        return "place"
    if intent == "WHERE_TO_SELL" and (quantity is None or quantity["value_kg"] is None):
        return "quantity_unit"
    if intent in ("PRICE_NOW", "FORECAST") and horizon is not None and horizon["kind"] == "AMBIGUOUS":
        return "horizon"
    if intent == "FORECAST" and (horizon is None or horizon["kind"] != "DAYS"):
        return "horizon"
    if intent == "OUTLOOK" and (horizon is None or horizon["kind"] != "MONTH"):
        return "horizon"
    return None


def _tool(intent, crop_ids, place, quantity, horizon, direction, threshold):
    """The §2.5 tool call(s); a list of two when the message named two crops (T-AMB-06)."""
    mandi = place["canonical"] if place else None
    if intent == "PRICE_NOW":
        calls = [{"name": "price_now", "args": {"crop": c, "mandi": mandi}} for c in crop_ids]
    elif intent == "FORECAST":
        calls = [{"name": "get_forecast", "args": {"crop": c, "mandi": mandi, "h": horizon["h"]}} for c in crop_ids]
    elif intent == "WHERE_TO_SELL":
        calls = [{"name": "best_mandis", "args": {"crop": c, "origin": mandi, "quantity_kg": quantity["value_kg"]}} for c in crop_ids]
    elif intent == "OUTLOOK":
        args = {"crop": crop_ids[0], "month": horizon["month"]}
        if place is not None:
            args["mandi"] = mandi
        calls = [{"name": "get_outlook", "args": args}]
    elif intent == "ALERT":
        calls = [{"name": "set_alert", "args": {"crop": crop_ids[0], "mandi": mandi, "direction": direction, "threshold": threshold}}]
    else:  # HELP
        return None
    return calls[0] if len(calls) == 1 else calls


def parse(text: str, now: date | None = None) -> dict:
    """Parse a whole farmer message into the benchmark gold shape (SPEC §2.1/§2.5). Pure; no DB/LLM/network."""
    words = _words(text)
    n = norm(text)
    nt = n.split()

    if n in _STOP_NORM:  # whole normalised message is a stop keyword
        return {"intent": "STOP", "slots": {"crop": None, "place": None, "quantity": None, "horizon": None},
                "tool": {"name": "stop", "args": {}}, "outcome": "ANSWER", "clarify_slot": None}

    used = [False] * len(words)
    place_hits = _find(text, words, resolve_place, used, 4)
    crop_hits = _find(text, words, resolve_crop, used, 1)
    if not crop_hits and (fz := _fuzzy(text, words, resolve_crop, used)):
        crop_hits = [fz]
    place_hit = place_hits[0] if place_hits else _fuzzy(text, words, resolve_place, used)
    marker = None if place_hit else _mandi_marker(text, words, used)

    quantity = _quantity_slot(text, words, crop_hits, used)
    direction = _direction(nt)
    has_number = any(_is_number(w[0]) for w in words)
    horizon = _horizon(text, now, future=any(t in _FUTURE for t in nt))

    intent = _intent(n, nt, horizon, direction, has_number)
    threshold = _threshold(words, _ABOVE | _BELOW) if intent == "ALERT" else None

    if intent in ("HELP", "OTHER"):  # these carry no slots in gold
        outcome = "OUT_OF_SCOPE" if intent == "OTHER" else "ANSWER"
        return {"intent": intent, "slots": {"crop": None, "place": None, "quantity": None, "horizon": None},
                "tool": None, "outcome": outcome, "clarify_slot": None}

    crop_ids = [_crop_id(r, intent) for _raw_c, r, _i in crop_hits]
    if not crop_hits:
        crop_slot = None
    elif len(crop_hits) == 1:
        crop_slot = {"raw": crop_hits[0][0], "id": crop_ids[0]}
    else:
        crop_slot = [{"raw": h[0], "id": cid} for h, cid in zip(crop_hits, crop_ids, strict=True)]
    place = _place_slot(place_hit, marker, intent)

    if any(c == "OUT_OF_COVERAGE" for c in crop_ids) or (place is not None and place["status"] == "OUT_OF_COVERAGE"):
        outcome, tool, clarify = "OUT_OF_COVERAGE", None, None
    elif (clarify := _clarify(intent, crop_ids, place, quantity, horizon)) is not None:
        outcome, tool = "CLARIFY", None
    else:
        outcome, tool = "ANSWER", _tool(intent, crop_ids, place, quantity, horizon, direction, threshold)

    result = {"intent": intent, "slots": {"crop": crop_slot, "place": place, "quantity": quantity, "horizon": horizon},
              "tool": tool, "outcome": outcome, "clarify_slot": clarify}
    if intent == "ALERT":
        result["alert_action"] = "SUBSCRIBE"
    return result
