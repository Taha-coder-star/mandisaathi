"""Price service (task 8.2, RFC C8) + series_coverage refresh (file 03 §6, file 09 R-07/R-08). Choices: DECISIONS.md D-036.

price_now: the latest observed rate of one crop × mandi that is OK (SUSPECT and REJECTED rows skipped), already
published at `as_of`, with its market date, source and a staleness flag (older than 2 trading days). None = no rate
("maloomat nahi" path). Prices stay canonical PKR/100 kg; the renderer converts to per mann.
refresh_coverage: pct of trading days with an OK quote in the last 12 months and the coverage gate
eligible_f1 = pct >= 60% and an OK quote within 3 trading days, upserted for every series price_obs has ever had.

Trading days = Mon-Sat minus the holidays of data/synthetic/spec.yaml, the same calendar the generator trades on
(tests/test_price.py checks every day of the spec period against it).
shortcut: FYP-I calendar is the synthetic world's (approximate lunar holidays); FYP-II swaps in the real market calendar.
"""
import functools
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import yaml

PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan has no DST (same as the loader)
SPEC_PATH = Path(__file__).resolve().parent.parent / "data/synthetic/spec.yaml"
STALE_AFTER = 2  # file 09 R-08: older than 2 trading days -> stale line
RECENT_WITHIN = 3  # file 03 §6: a quote within 3 trading days
MIN_PCT = 0.60  # file 03 §6: >= 60% of trading days in the last 12 months
WINDOW_DAYS = 365
NOT_LIVE = "SYN-NULL"  # false-skill variant, never farmer-facing (D-034)


@functools.cache
def _holidays(year: int) -> frozenset[date]:
    h = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))["period"]["holidays"]
    mv = h["moving"]
    off = {date(year, int(md[:2]), int(md[3:])) for md in h["fixed_mmdd"]}
    for b in mv["blocks"]:
        first = date(year, b["anchor"].month, b["anchor"].day) + timedelta(mv["drift_days_per_year"] * (year - mv["anchor_year"]))
        off |= {first + timedelta(i) for i in range(b["days"])}
    return frozenset(off)


def is_trading_day(d: date) -> bool:
    # a moving block anchored in one year can spill into the next (or previous) one
    return d.weekday() != 6 and not any(d in _holidays(y) for y in (d.year - 1, d.year, d.year + 1))


def trading_age(market_date: date, today: date) -> int:
    """Trading days after market_date up to and including today (yesterday's rate on a normal weekday = 1)."""
    return sum(is_trading_day(market_date + timedelta(i)) for i in range(1, (today - market_date).days + 1))


@dataclass(frozen=True)
class Price:
    obs_id: int
    crop_id: str
    mandi_id: str
    source: str
    grade: str | None
    market_date: date
    min_pkr100kg: Decimal | None
    max_pkr100kg: Decimal | None
    avg_pkr100kg: Decimal | None
    age: int  # trading days, see trading_age
    stale: bool


def price_now(conn, crop_id: str, mandi_id: str, as_of: datetime) -> Price | None:
    """Latest OK rate published by as_of (aware datetime; pass a fixed one for S-DEMO / golden answers)."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    row = conn.execute(
        "SELECT obs_id, crop_id, mandi_id, source, grade, market_date, min_pkr100kg, max_pkr100kg, avg_pkr100kg"
        " FROM price_obs WHERE crop_id = %s AND mandi_id = %s AND outlier_flag = 'OK' AND source <> %s"
        " AND reported_at <= %s ORDER BY market_date DESC, reported_at DESC, obs_id DESC LIMIT 1",
        (crop_id, mandi_id, NOT_LIVE, as_of)).fetchone()
    if row is None:
        return None
    age = trading_age(row[5], as_of.astimezone(PKT).date())
    return Price(*row, age=age, stale=age > STALE_AFTER)


def refresh_coverage(conn, as_of: date) -> int:
    """Coverage gate for issue day as_of: rows known before as_of 00:00 PKT, window [as_of - 365 d, as_of).
    Every series ever in price_obs gets a row, so one that went quiet is switched off. Returns rows written.
    A crop × mandi with no price_obs row at all has no series_coverage row: the gate treats it as not eligible."""
    start, cut = as_of - timedelta(WINDOW_DAYS), datetime.combine(as_of, time(0), PKT)
    n_days = sum(is_trading_day(start + timedelta(i)) for i in range(WINDOW_DAYS))
    ok = "outlier_flag = 'OK' AND reported_at < %(cut)s"
    series = conn.execute(
        f"SELECT crop_id, mandi_id, count(DISTINCT market_date) FILTER (WHERE {ok} AND market_date >= %(start)s"
        f" AND market_date < %(as_of)s), max(market_date) FILTER (WHERE {ok})"
        " FROM price_obs WHERE source <> %(not_live)s GROUP BY crop_id, mandi_id",
        {"cut": cut, "start": start, "as_of": as_of, "not_live": NOT_LIVE}).fetchall()
    rows = []
    for crop_id, mandi_id, days, last in series:
        pct = days / n_days
        recent = last is not None and trading_age(last, as_of) <= RECENT_WITHIN
        rows.append((crop_id, mandi_id, WINDOW_DAYS, round(pct, 4), pct >= MIN_PCT and recent))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO series_coverage (crop_id, mandi_id, window_days, pct_days, eligible_f1) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (crop_id, mandi_id, window_days) DO UPDATE SET pct_days = EXCLUDED.pct_days,"
            " eligible_f1 = EXCLUDED.eligible_f1", rows)
    return len(rows)
