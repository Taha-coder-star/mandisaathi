"""Crop + place resolver for chat (task 6.1; file 03 §4.3, file 06 §5, RFC C6; DECISIONS.md D-027).

Raw span -> RESOLVED / AMBIGUOUS / UNKNOWN / OUT_OF_COVERAGE. Exact alias first, then fuzzy; a pin -> nearest place.
Finding spans in a whole message is the parser's job (7.1). The LLM picks only from `ids`, never invents one.
"""
import functools
import math
from difflib import SequenceMatcher
from typing import NamedTuple

from mandi.gazetteer import norm, read, rows
from mandi.ingest.loader import FUZZY_MARGIN, FUZZY_MIN  # same rule as ingest name matching (D-018)

PIN_MAX_KM = 150  # file 06 §5: a pin farther than this from every covered mandi is OUT_OF_COVERAGE


class Resolution(NamedTuple):
    status: str  # RESOLVED / AMBIGUOUS / UNKNOWN / OUT_OF_COVERAGE
    ids: tuple[str, ...]  # 1 id (RESOLVED, OUT_OF_COVERAGE), candidates best first (AMBIGUOUS), () (UNKNOWN)
    exact: bool  # False -> echo the canonical name before answering (file 05 §6)
    mandi_ids: tuple[str, ...] = ()  # place RESOLVED only: its candidate mandis


@functools.cache
def _tables() -> dict:
    r = rows(read())
    aliases: dict[str, dict[str, set[str]]] = {"crop": {}, "place": {}}
    for a, cid, _ in r["crop_alias"]:
        aliases["crop"].setdefault(a, set()).add(cid)
    for a, pid in r["place_alias"]:
        aliases["place"].setdefault(a, set()).add(pid)
    covered = {"crop": {c[0] for c in r["crop"] if c[6]}, "place": {p[0] for p in r["place"] if p[5] == "Punjab"}}
    places = {p[0]: p for p in r["place"]}  # place_id, name_en, name_ur, kind, district, province, lat, lon, candidates
    return {"aliases": aliases, "covered": covered, "places": places}


def place_index() -> tuple[dict[str, set[str]], dict[str, tuple]]:
    """(normalised exact alias -> place ids, place id -> place row) for the 9.1 renderer and validator."""
    t = _tables()
    return t["aliases"]["place"], t["places"]


def _one(kind: str, target: str, exact: bool) -> Resolution:
    t = _tables()
    if target not in t["covered"][kind]:
        return Resolution("OUT_OF_COVERAGE", (target,), exact)
    mandis = tuple(t["places"][target][8]) if kind == "place" else ()
    return Resolution("RESOLVED", (target,), exact, mandis)


def _resolve(kind: str, raw: str) -> Resolution:
    key, aliases = norm(raw), _tables()["aliases"][kind]
    if not key:
        return Resolution("UNKNOWN", (), True)
    if (found := aliases.get(key)) is not None:
        return _one(kind, *found, True) if len(found) == 1 else Resolution("AMBIGUOUS", tuple(sorted(found)), True)
    best: dict[str, float] = {}  # target -> score of its best alias
    for alias, targets in aliases.items():
        score = SequenceMatcher(None, key, alias).ratio()
        for t in targets:
            best[t] = max(best.get(t, 0.0), score)
    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < FUZZY_MIN:  # also the UNKNOWN floor: Jaranwala 0.84 ~ Gujranwala, ganna 0.80 ~ ganda (D-027)
        return Resolution("UNKNOWN", (), False)
    close = tuple(t for t, s in ranked if s > ranked[0][1] - FUZZY_MARGIN)
    return _one(kind, close[0], False) if len(close) == 1 else Resolution("AMBIGUOUS", close, False)


def resolve_crop(raw: str) -> Resolution:
    return _resolve("crop", raw)


def resolve_place(raw: str) -> Resolution:
    return _resolve("place", raw)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine, R = 6371 km)."""
    p1, p2, dp, dl = map(math.radians, (lat1, lat2, lat2 - lat1, lon2 - lon1))
    return 2 * 6371 * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def resolve_pin(lat: float, lon: float) -> Resolution:
    """Location pin -> nearest covered place; the pin itself stays the origin for distances (file 03 §4.3).
    shortcut: straight-line km and mandi city centres (no district centroids or province polygon); F2 uses road km."""
    t = _tables()
    km, pid = min((_km(lat, lon, float(t["places"][p][6]), float(t["places"][p][7])), p) for p in t["covered"]["place"])
    if km > PIN_MAX_KM:
        return Resolution("OUT_OF_COVERAGE", (pid,), True)  # names the nearest covered mandi (file 06 §5)
    return _one("place", pid, True)
