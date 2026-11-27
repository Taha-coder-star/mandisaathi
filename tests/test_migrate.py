"""Task 2.3 DONE check: migrations apply on an empty DB and re-run idempotently.

Each test gets its own throwaway database (`db` fixture in conftest.py).
"""
import threading
from pathlib import Path

import psycopg
import pytest

from app.migrate import MIGRATIONS, MigrationError, migrate

TABLES = {
    "crop", "crop_alias", "mandi", "place", "place_alias", "distance",
    "price_obs", "weather_daily", "macro_monthly", "data_health",
    "forecast", "outlook", "series_coverage", "model_registry",
    "inbound_event", "job", "outbound_message",
    "wa_user", "query_state", "stop_tally",
    "query_patch_log", "answer_shown", "pending_clarification",
    "message_log",
}
ALL = sorted(p.stem for p in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))


def tables(url):
    with psycopg.connect(url) as c:
        return {r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def history(url):
    with psycopg.connect(url) as c:
        return c.execute("SELECT version, checksum, applied_at FROM schema_migrations ORDER BY version").fetchall()


def test_empty_db_then_idempotent_rerun(db):
    assert migrate(db) == ALL
    assert tables(db) == TABLES | {"schema_migrations"}
    before = history(db)
    assert [v for v, _, _ in before] == ALL

    assert migrate(db) == []
    assert history(db) == before  # same rows, checksums and applied_at


def test_inbound_event_dedup_key_unique(db):
    migrate(db)
    with psycopg.connect(db) as c:
        c.execute("INSERT INTO inbound_event (dedup_key, kind, payload) VALUES ('wamid.X', 'message', '{}')")
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute("INSERT INTO inbound_event (dedup_key, kind, payload) VALUES ('wamid.X', 'message', '{}')")


def test_price_obs_rejects_unknown_source_and_dedups_null_grade(db):
    migrate(db)
    with psycopg.connect(db, autocommit=True) as c:
        c.execute("INSERT INTO crop VALUES ('ONION', 'Onion', 'پیاز', 'MED', 'mann', NULL, true)")
        c.execute("INSERT INTO mandi (mandi_id, name_en, name_ur, city, district, province, lat, lon)"
                  " VALUES ('LHR', 'Lahore', 'لاہور', 'Lahore', 'Lahore', 'Punjab', 31.5, 74.3)")
        row = ("INSERT INTO price_obs (source, mandi_id, crop_id, market_date, reported_at, avg_pkr100kg, unit_raw, value_raw,"
               " raw_ref, raw_sha256) VALUES (%s, 'LHR', 'ONION', '2026-11-20', '2026-11-20 18:00+05', 7000, '100kg', 7000, 'f', 'h')")
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(row, ("XYZ",))
        c.execute(row, ("SYN",))
        with pytest.raises(psycopg.errors.UniqueViolation):  # grade NULL twice is still the same observation
            c.execute(row, ("SYN",))
        c.execute(row, ("SYN-NULL",))


def test_failed_migration_rolls_back(db, tmp_path: Path):
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE a (x int);")
    (tmp_path / "002_bad.sql").write_text("CREATE TABLE b (x int); SELECT no_such_function();")
    with pytest.raises(MigrationError, match="002_bad.sql failed"):
        migrate(db, tmp_path)
    assert tables(db) == {"a", "schema_migrations"}  # b rolled back with its file
    assert [v for v, _, _ in history(db)] == ["001_ok"]


def test_edited_migration_is_detected(db, tmp_path: Path):
    f = tmp_path / "001_x.sql"
    f.write_text("CREATE TABLE a (x int);")
    migrate(db, tmp_path)
    f.write_text("CREATE TABLE a (x int, y int);")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        migrate(db, tmp_path)


def test_crlf_checkout_has_same_checksum(db, tmp_path: Path):
    f = tmp_path / "001_x.sql"
    f.write_bytes(b"CREATE TABLE a (x int);\n")
    migrate(db, tmp_path)
    f.write_bytes(b"CREATE TABLE a (x int);\r\n")
    assert migrate(db, tmp_path) == []


def test_concurrent_migrators_apply_once(db):
    results, errors = [], []

    def run():
        try:
            results.append(migrate(db, MIGRATIONS))
        except Exception as e:  # noqa: BLE001 - surfaced by the assert below
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(results) == [[], [], ALL]
