"""Task 3.3: real-data loader contract. DONE check: a 5-row HAND-MADE file in the requested export format
(docs/requests/2026-11-23_real_data_request.md item 4) goes through the same load() as SYN. Not real data (D-015)."""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from app.migrate import migrate
from mandi.gazetteer import load_gazetteer
from mandi.ingest.loader import PKT, load, name_resolver, read_export_csv

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/handmade_export_5rows.csv"


def test_handmade_export_file_loads_through_the_shared_loader(db):
    migrate(db)
    with psycopg.connect(db, autocommit=True) as c:
        load_gazetteer(c)
        res = load(c, "SYN", read_export_csv(FIXTURE), "h" * 64, name_resolver(c))  # SYN: hand-made, not market data
        rows = c.execute(
            "SELECT source, mandi_id, crop_id, grade, market_date, reported_at, min_pkr100kg, max_pkr100kg, avg_pkr100kg,"
            " unit_raw, value_raw, arrivals_qty, arrivals_unit, raw_ref FROM price_obs ORDER BY raw_ref"
        ).fetchall()

    ref = FIXTURE.name + "#L"
    assert res.unmatched == []  # "Lahore (Badami Bagh)" resolves to LAHORE (task 4.2, D-018)
    assert res.rejected == [(ref + "6", "unknown unit 'per kg'")]
    assert res.upserted == 4
    d, at = date(2026, 11, 20), datetime(2026, 11, 20, 18, 0, tzinfo=PKT)
    D = Decimal
    assert rows == [
        ("SYN", "LAHORE", "ONION", "A", d, at, D(3000), D(3250), D(3125), "per 40 kg", D(1250), D(450), "bags", ref + "2"),
        ("SYN", "LAHORE", "ONION", "B", d, at, D(2500), D(2750), D(2625), "per 40 kg", D(1050), D(300), "bags", ref + "3"),
        ("SYN", "OKARA", "TOMATO", None, d, at, None, None, D(5000), "per 100 kg", D(5000), None, None, ref + "4"),
        ("SYN", "LAHORE", "POTATO", None, d, at, D(3000), D(3200), D(3100), "per 100 kg", D(3100), D(12), "tonne", ref + "5"),
    ]
