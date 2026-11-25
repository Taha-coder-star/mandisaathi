"""Load a price file into price_obs (task 3.2; file 03 §3, DECISIONS.md D-014).

  python -m mandi.ingest.loader <file.csv> --source SYN|SYN-NULL [--unmatched out.csv]   (needs DATABASE_URL)

A reader turns one file format into RawObs rows; everything after it (units, reported_at, upsert) is shared.
read_export_csv is the real-data contract (task 3.3, D-015): FYP-II fits it to the real sample and adds the
real unit spellings to TO_PER_100KG; nothing after the reader changes. Mandi names: make_matcher (task 4.2, D-018).
"""
import argparse
import csv
import functools
import hashlib
import os
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

import psycopg
import yaml

SPEC = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "spec.yaml"
PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan has no DST, so a fixed offset equals Asia/Karachi
PUBLISH_TIME = time(18, 0)  # file 03 §3 ASSUMPTION: knowable from 18:00 PKT on the market day (leakage test L2)
# anything else is rejected, never guessed; "per 40 kg"/"per 100 kg" are the request's wording (ASSUMPTION, D-015)
TO_PER_100KG = {"PKR/100kg": Decimal(1), "PKR/40kg": Decimal("2.5"), "per 100 kg": Decimal(1), "per 40 kg": Decimal("2.5")}
PERISHABILITY = {"TOMATO": "HIGH", "ONION": "MED", "POTATO": "MED", "WHEAT": "LOW"}  # ASSUMPTION (D-014); 4.3 owns crops
# old/short names no spelling rule can reach (D-018). shortcut: hard-coded until 4.3's gazetteer owns aliases
MANDI_ALIASES: dict[str, tuple[str, ...]] = {"FAISALABAD": ("Lyallpur",), "SAHIWAL": ("Montgomery",), "RYKHAN": ("RYK",)}
FUZZY_MIN, FUZZY_MARGIN = 0.85, 0.15  # file 03 §4.3: one candidate >= 0.85 and >= 0.15 ahead of the next

COLS = ["source", "mandi_id", "crop_id", "grade", "market_date", "reported_at", "min_pkr100kg", "max_pkr100kg", "avg_pkr100kg",
        "unit_raw", "value_raw", "arrivals_qty", "arrivals_unit", "raw_ref", "raw_sha256"]
KEY = ["source", "mandi_id", "crop_id", "grade", "market_date"]  # price_obs UNIQUE NULLS NOT DISTINCT (001_schema_v1)
UPSERT = (f"INSERT INTO price_obs ({', '.join(COLS)}) VALUES ({', '.join(f'%({c})s' for c in COLS)})"
          f" ON CONFLICT ({', '.join(KEY)}) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLS if c not in KEY))


@dataclass(frozen=True)
class RawObs:
    market_date: date
    crop_id: str
    mandi_raw: str
    unit_raw: str
    min_raw: Decimal | None
    max_raw: Decimal | None
    avg_raw: Decimal | None
    arrivals_qty: Decimal | None
    arrivals_unit: str | None
    reported_at: datetime | None  # None: the source gives no publish time
    raw_ref: str
    grade: str | None = None  # as reported; the generator has no grades


@dataclass
class LoadResult:
    upserted: int = 0
    unmatched: list[tuple[str, str]] = field(default_factory=list)  # (raw_ref, mandi_raw): no confident match, not loaded
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (raw_ref, reason)


def _dec(s: str) -> Decimal | None:
    return Decimal(s) if s else None  # from the CSV text, never via float


def read_syn_csv(path: Path) -> Iterator[RawObs]:
    """Generator CSV (scripts/make_synthetic.py). The truth_* answer-key columns are never read."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            yield RawObs(
                market_date=date.fromisoformat(r["market_date"]),
                crop_id=r["crop_id"],
                mandi_raw=r["mandi_raw"],
                unit_raw=r["unit_raw"],
                min_raw=_dec(r["min_raw"]),
                max_raw=_dec(r["max_raw"]),
                avg_raw=_dec(r["avg_raw"]),
                arrivals_qty=_dec(r["arrivals_qty"]),
                arrivals_unit=r["arrivals_unit"] or None,
                reported_at=datetime.fromisoformat(r["reported_at"]) if r["reported_at"] else None,
                raw_ref=f"{path.name}#L{reader.line_num}",
            )


def read_export_csv(path: Path) -> Iterator[RawObs]:
    """Real-data export as requested (docs/requests/2026-11-23_real_data_request.md item 4); D-015.
    shortcut: headers, ISO dates and English crop names are our guess; refit to the co-supervisor sample in FYP-II."""
    with open(path, encoding="utf-8-sig", newline="") as f:  # -sig: Excel writes a BOM
        reader = csv.DictReader(f)
        for r in reader:
            yield RawObs(
                market_date=date.fromisoformat(r["market_date"]),
                crop_id=r["crop"].strip().upper(),
                mandi_raw=r["mandi"],
                unit_raw=r["unit"],
                min_raw=_dec(r["min_price"]),
                max_raw=_dec(r["max_price"]),
                avg_raw=_dec(r["avg_price"]),
                arrivals_qty=_dec(r["arrivals_qty"]),
                arrivals_unit=r["arrivals_unit"] or None,
                reported_at=None,  # no publish-time column (request item 5 asks); the 18:00 PKT rule applies
                raw_ref=f"{path.name}#L{reader.line_num}",
                grade=r["grade"].strip() or None,
            )


def to_price_row(obs: RawObs, mandi_id: str) -> dict:
    """Canonical price_obs values (PKR per 100 kg). Raises ValueError for an unknown unit or a row with no price."""
    factor = TO_PER_100KG.get(obs.unit_raw)
    if factor is None:
        raise ValueError(f"unknown unit {obs.unit_raw!r}")
    value_raw = next((v for v in (obs.avg_raw, obs.max_raw, obs.min_raw) if v is not None), None)
    if value_raw is None:
        raise ValueError("no price")
    lo, hi, avg = (None if v is None else v * factor for v in (obs.min_raw, obs.max_raw, obs.avg_raw))
    reported_at = obs.reported_at or datetime.combine(obs.market_date, PUBLISH_TIME)
    if reported_at.tzinfo is None:
        reported_at = reported_at.replace(tzinfo=PKT)  # a source time without zone is local market time
    return {
        "mandi_id": mandi_id, "crop_id": obs.crop_id, "grade": obs.grade, "market_date": obs.market_date, "reported_at": reported_at,
        "min_pkr100kg": lo, "max_pkr100kg": hi, "avg_pkr100kg": avg, "unit_raw": obs.unit_raw, "value_raw": value_raw,
        "arrivals_qty": obs.arrivals_qty, "arrivals_unit": obs.arrivals_unit, "raw_ref": obs.raw_ref,
    }


def name_key(raw: str) -> str:
    """'Lahore (Badami Bagh) Mandi' -> 'lahore': NFKC, casefold, no (...) groups, no spaces/punctuation, no word 'mandi'."""
    s = re.sub(r"\([^)]*\)", " ", unicodedata.normalize("NFKC", raw).casefold())
    return "".join(t for t in re.split(r"\W+", s) if t != "mandi")


def _skeleton(key: str) -> str:
    """Consonant skeleton: q=k, w=v, vowels and y dropped, repeated letters collapsed ('multaan' -> 'mltn')."""
    return re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiouy]", "", key.replace("q", "k").replace("w", "v")))


def make_matcher(mandis: Iterable[tuple[str, str]],
                 aliases: dict[str, tuple[str, ...]] = MANDI_ALIASES) -> Callable[[str], str | None]:
    """(mandi_id, name_en) pairs -> raw name -> mandi_id or None. Tiers: exact key (id, name, alias); a consonant
    skeleton of >= 3 letters that only one mandi has; difflib ratio >= FUZZY_MIN and FUZZY_MARGIN ahead of every
    other mandi. Anything else is unmatched, never guessed. Raises ValueError if one key names two mandis."""
    exact: dict[str, str] = {}
    for mandi_id, name_en in mandis:
        for k in (name_key(n) for n in (mandi_id, name_en, *aliases.get(mandi_id, ()))):
            if exact.setdefault(k, mandi_id) != mandi_id:
                raise ValueError(f"name key {k!r} points to both {exact[k]} and {mandi_id}")
    skeletons: dict[str, set[str]] = {}
    for k, mandi_id in exact.items():
        skeletons.setdefault(_skeleton(k), set()).add(mandi_id)

    @functools.cache
    def match(raw: str) -> str | None:
        key = name_key(raw)
        if not key:
            return None
        if key in exact:
            return exact[key]
        sk = _skeleton(key)
        if len(sk) >= 3 and len(skeletons.get(sk, ())) == 1:
            return next(iter(skeletons[sk]))
        best: dict[str, float] = {}
        for k, mandi_id in exact.items():
            best[mandi_id] = max(best.get(mandi_id, 0.0), SequenceMatcher(None, key, k).ratio())
        top, second = (sorted(best.values(), reverse=True) + [0.0, 0.0])[:2]
        return max(best, key=best.get) if top >= FUZZY_MIN and top - second >= FUZZY_MARGIN else None  # tie: margin 0, refused

    return match


def name_resolver(conn: psycopg.Connection) -> Callable[[str], str | None]:
    """make_matcher over the mandi table."""
    return make_matcher(conn.execute("SELECT mandi_id, name_en FROM mandi").fetchall())


def seed_reference(conn: psycopg.Connection, spec: dict) -> None:
    """The spec's mandis and crops; existing rows are left alone. city = name_en, province Punjab, default unit mann."""
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO mandi (mandi_id, name_en, name_ur, city, district, province, lat, lon)"
            " VALUES (%s, %s, %s, %s, %s, 'Punjab', %s, %s) ON CONFLICT DO NOTHING",
            [(m["id"], m["name_en"], m["name_ur"], m["name_en"], m["district"], m["lat"], m["lon"]) for m in spec["mandis"]],
        )
        cur.executemany(
            "INSERT INTO crop (crop_id, name_en, name_ur, perishability_class, default_unit)"
            " VALUES (%s, %s, %s, %s, 'mann') ON CONFLICT DO NOTHING",
            [(cid, c["name_en"], c["name_ur"], PERISHABILITY[cid]) for cid, c in spec["crops"].items()],
        )


def load(conn: psycopg.Connection, source: str, rows: Iterable[RawObs], raw_sha256: str,
         resolve: Callable[[str], str | None]) -> LoadResult:
    """Upsert every resolvable, valid row in one transaction; reloading the same file changes nothing."""
    res, params = LoadResult(), []
    for obs in rows:
        mandi_id = resolve(obs.mandi_raw)
        if mandi_id is None:
            res.unmatched.append((obs.raw_ref, obs.mandi_raw))
            continue
        try:
            params.append(to_price_row(obs, mandi_id) | {"source": source, "raw_sha256": raw_sha256})
        except ValueError as e:
            res.rejected.append((obs.raw_ref, str(e)))
    if params:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(UPSERT, params)
    res.upserted = len(params)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load a generator CSV into price_obs (task 3.2).")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--source", required=True, choices=["SYN", "SYN-NULL"])
    ap.add_argument("--unmatched", type=Path, help="write unmatched names for review: CSV mandi_raw,rows,first_ref")
    a = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("loader: DATABASE_URL is not set", file=sys.stderr)
        return 1
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    with psycopg.connect(url, autocommit=True) as conn:  # autocommit: each conn.transaction() is a real commit
        seed_reference(conn, spec)
        res = load(conn, a.source, read_syn_csv(a.csv), hashlib.sha256(a.csv.read_bytes()).hexdigest(), name_resolver(conn))
    names = Counter(raw for _, raw in res.unmatched)
    print(f"loader: upserted {res.upserted}, unmatched {len(res.unmatched)} ({len(names)} names), rejected {len(res.rejected)}")
    if a.unmatched:
        first = {raw: ref for ref, raw in reversed(res.unmatched)}  # reversed: the earliest ref wins
        with open(a.unmatched, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["mandi_raw", "rows", "first_ref"])
            w.writerows((raw, n, first[raw]) for raw, n in names.most_common())
    return 0


if __name__ == "__main__":
    sys.exit(main())
