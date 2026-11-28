"""Task 8.2: price service + coverage refresh. DONE check: SUSPECT row excluded; stale flag after 2 trading days;
eligibility per file 03 §6 (>= 60% of trading days in 12 months + a quote within 3 trading days)."""
import importlib.util
import math
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg
import pytest

from app.migrate import migrate
from mandi.gazetteer import load_gazetteer
from mandi.models.devdata import dev_end, price_rows
from mandi.price import PKT, is_trading_day, price_now, refresh_coverage, trading_age

ROOT = Path(__file__).resolve().parent.parent
_mod = importlib.util.spec_from_file_location("make_synthetic", ROOT / "scripts" / "make_synthetic.py")
ms = importlib.util.module_from_spec(_mod)
_mod.loader.exec_module(ms)
SPEC = ms.load_spec()

SAT, MON = date(2026, 11, 28), date(2026, 11, 30)


def at(d: date, hh=10) -> datetime:
    return datetime.combine(d, time(hh), PKT)


def test_calendar_is_the_generators_day_for_day():
    days, trading = ms.calendar(SPEC)
    assert [is_trading_day(d) for d in days] == trading.tolist()


@pytest.mark.parametrize("market, today, age", [
    (SAT, MON, 1),                              # Sunday is not counted
    (date(2026, 11, 27), MON, 2),               # Fri -> Sat, Mon
    (date(2026, 11, 26), MON, 3),
    (date(2026, 11, 7), date(2026, 11, 10), 1),  # Sat -> Tue over Sunday + Iqbal Day (Mon 9 Nov)
    (MON, MON, 0),
])
def test_trading_age(market, today, age):
    assert trading_age(market, today) == age


# --- with a database -------------------------------------------------------

def put(c, rows):
    """rows: (crop, mandi, market_date, avg[, flag[, source[, reported_at]]]); reported_at defaults to 18:00 PKT."""
    with c.cursor() as cur:
        cur.executemany(
            "INSERT INTO price_obs (source, mandi_id, crop_id, market_date, reported_at, min_pkr100kg, max_pkr100kg,"
            " avg_pkr100kg, unit_raw, value_raw, outlier_flag, raw_ref, raw_sha256)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PKR/100kg', %s, %s, 't', 'h')",
            [(r[5] if len(r) > 5 else "SYN", r[1], r[0], r[2], r[6] if len(r) > 6 else at(r[2], 18),
              r[3] - 100, r[3] + 100, r[3], r[3], r[4] if len(r) > 4 else "OK") for r in rows])


@pytest.fixture
def conn(db):
    migrate(db)
    with psycopg.connect(db, autocommit=True) as c:
        load_gazetteer(c)
        yield c


def test_done_suspect_and_rejected_rows_are_skipped(conn):
    put(conn, [("ONION", "LAHORE", date(2026, 11, 25), 3000), ("ONION", "LAHORE", date(2026, 11, 26), 30000, "SUSPECT"),
               ("ONION", "LAHORE", date(2026, 11, 27), 300, "REJECTED")])
    p = price_now(conn, "ONION", "LAHORE", at(SAT))
    assert (p.market_date, p.avg_pkr100kg, p.source) == (date(2026, 11, 25), 3000, "SYN")
    assert p.age == 3 and p.stale


@pytest.mark.parametrize("market, today, stale", [
    (date(2026, 11, 26), SAT, False),  # 2 trading days old
    (date(2026, 11, 25), SAT, True),   # 3
    (SAT, MON, False),                 # over a Sunday: 1
    (date(2026, 11, 26), MON, True),   # Thu -> Mon: 3
])
def test_done_stale_after_two_trading_days(conn, market, today, stale):
    put(conn, [("TOMATO", "OKARA", market, 5000)])
    assert price_now(conn, "TOMATO", "OKARA", at(today)).stale is stale


def test_unpublished_and_syn_null_rows_are_not_shown(conn):
    put(conn, [("POTATO", "SAHIWAL", date(2026, 11, 26), 2000),
               ("POTATO", "SAHIWAL", date(2026, 11, 27), 2100),                      # published 18:00 Fri
               ("POTATO", "SAHIWAL", SAT, 9999, "OK", "SYN-NULL")])
    assert price_now(conn, "POTATO", "SAHIWAL", at(date(2026, 11, 27), 12)).market_date == date(2026, 11, 26)
    p = price_now(conn, "POTATO", "SAHIWAL", at(date(2026, 11, 27), 18))
    assert p.market_date == date(2026, 11, 27) and p.age == 0 and not p.stale
    assert price_now(conn, "POTATO", "SAHIWAL", at(MON)).avg_pkr100kg == 2100
    assert price_now(conn, "POTATO", "LAHORE", at(MON)) is None
    with pytest.raises(ValueError):
        price_now(conn, "POTATO", "SAHIWAL", datetime(2026, 11, 30, 10))


def coverage(conn):
    return {(r[0], r[1]): (float(r[2]), r[3]) for r in conn.execute(
        "SELECT crop_id, mandi_id, pct_days, eligible_f1 FROM series_coverage WHERE window_days = 365")}


def test_done_eligibility_sixty_percent_and_recent_quote(conn):
    window = [d for d in (MON - timedelta(i) for i in range(1, 366)) if is_trading_day(d)]  # newest first
    need = math.ceil(0.6 * len(window))
    put(conn, [("ONION", "LAHORE", d, 3000) for d in window[:need]]                 # exactly >= 60%
              + [("ONION", "OKARA", d, 3000) for d in window[:need - 1]]            # one day short
              + [("ONION", "SAHIWAL", d, 3000) for d in window[3:]]                 # full but last quote 4 trading days old
              + [("ONION", "KASUR", d, 3000) for d in window[2:]]                   # last quote 3 trading days old
              + [("TOMATO", "LAHORE", d, 5000, "SUSPECT") for d in window])         # SUSPECT rows do not count
    assert trading_age(window[3], MON) == 4 and trading_age(window[2], MON) == 3
    assert refresh_coverage(conn, MON) == 5
    cov = coverage(conn)
    assert cov[("ONION", "LAHORE")] == (round(need / len(window), 4), True)
    assert cov[("ONION", "OKARA")][1] is False and cov[("ONION", "OKARA")][0] < 0.6
    assert cov[("ONION", "SAHIWAL")][1] is False and cov[("ONION", "SAHIWAL")][0] > 0.98
    assert cov[("ONION", "KASUR")][1] is True
    assert cov[("TOMATO", "LAHORE")] == (0.0, False)

    # a series that goes quiet is switched off on a later refresh (upsert, not insert-only)
    assert refresh_coverage(conn, MON + timedelta(14)) == 5
    assert coverage(conn)[("ONION", "LAHORE")][1] is False


def test_refresh_on_synthetic_data_matches_e1(conn):
    """E1 (results/E1, D-024) found 12 eligible mandis per crop, the 3 thin ones below the gate. Same window here."""
    end = dev_end(SPEC)
    rows = [r for r in price_rows(ms.generate(SPEC, "SYN", SPEC["meta"]["seed"]), end) if r["market_date"] > end - timedelta(400)]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO price_obs (source, mandi_id, crop_id, market_date, reported_at, min_pkr100kg, max_pkr100kg,"
            " avg_pkr100kg, unit_raw, value_raw, outlier_flag, raw_ref, raw_sha256)"
            " VALUES ('SYN', %s, %s, %s, %s, %s, %s, %s, 'PKR/100kg', %s, %s, 't', 'h')",
            [(r["mandi_id"], r["crop_id"], r["market_date"], r["reported_at"], r["min_pkr100kg"], r["max_pkr100kg"],
              r["avg_pkr100kg"], r["avg_pkr100kg"], r["outlier_flag"]) for r in rows])
    refresh_coverage(conn, end)
    cov = coverage(conn)
    thin = {m["id"] for m in SPEC["mandis"] if m["thin"]}
    assert Counter(c for (c, _), (_, ok) in cov.items() if ok) == {"ONION": 12, "TOMATO": 12, "POTATO": 12}
    assert all(not ok for (_, m), (_, ok) in cov.items() if m in thin)
