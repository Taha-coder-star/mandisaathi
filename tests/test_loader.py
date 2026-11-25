"""Task 3.2: loader -> price_obs. DONE check: a per-40 kg row converts x 2.5 exactly; known rows load exactly once."""
import copy
import importlib.util
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
import yaml

from app.migrate import migrate
from mandi.gazetteer import load_gazetteer
from mandi.ingest.loader import PKT, RawObs, load, name_resolver, read_syn_csv, to_price_row

ROOT = Path(__file__).resolve().parent.parent
SPEC = yaml.safe_load((ROOT / "data/synthetic/spec.yaml").read_text(encoding="utf-8"))

CSV = """\
market_date,crop_id,mandi_raw,unit_raw,min_raw,max_raw,avg_raw,arrivals_qty,arrivals_unit,reported_at
2026-11-20,ONION,Lahore,PKR/40kg,1200,1300.4,1250.508,12.50,tonne,2026-11-20 18:00+05:00
2026-11-20,ONION,okara,PKR/100kg,2900.00,3100.00,3000.00,8.00,tonne,2026-11-21 18:00+05:00
2026-11-20,TOMATO,SAHIWAL,PKR/100kg,,,5000.00,,,
2026-11-20,POTATO,Hyderabad,PKR/100kg,3000.00,3200.00,3100.00,5.00,tonne,2026-11-20 18:00+05:00
2026-11-20,POTATO,Okara,PKR/kg,30.00,32.00,31.00,5.00,tonne,2026-11-20 18:00+05:00
"""


def obs(unit="PKR/40kg", prices=("1200", "1300.4", "1250.508"), reported_at=None):
    lo, hi, avg = (Decimal(v) if v else None for v in prices)
    return RawObs(date(2026, 11, 20), "ONION", "Lahore", unit, lo, hi, avg, Decimal("12.5"), "tonne", reported_at, "t.csv#L2")


def test_per_40kg_row_converts_times_2_5_exactly():
    r = to_price_row(obs(), "LAHORE")
    assert (r["min_pkr100kg"], r["max_pkr100kg"], r["avg_pkr100kg"]) == (Decimal("3000"), Decimal("3251.0"), Decimal("3126.27"))
    assert r["unit_raw"] == "PKR/40kg" and r["value_raw"] == Decimal("1250.508")


def test_per_100kg_row_unchanged_and_value_raw_falls_back_to_max():
    r = to_price_row(obs("PKR/100kg", ("2900.00", "3100.00", "")), "LAHORE")
    assert (r["min_pkr100kg"], r["max_pkr100kg"], r["avg_pkr100kg"]) == (Decimal("2900.00"), Decimal("3100.00"), None)
    assert r["value_raw"] == Decimal("3100.00")


@pytest.mark.parametrize("unit, prices", [("PKR/kg", ("30", "32", "31")), ("", ("30", "32", "31")), ("PKR/100kg", ("", "", ""))])
def test_unknown_unit_or_no_price_is_refused(unit, prices):
    with pytest.raises(ValueError):
        to_price_row(obs(unit, prices), "LAHORE")


def test_reported_at_defaults_to_1800_pkt_and_explicit_time_is_kept():
    assert to_price_row(obs(), "LAHORE")["reported_at"] == datetime(2026, 11, 20, 18, 0, tzinfo=PKT)
    late = datetime(2026, 11, 21, 18, 0, tzinfo=PKT)
    assert to_price_row(obs(reported_at=late), "LAHORE")["reported_at"] == late
    naive = datetime(2026, 11, 20, 20, 30)
    assert to_price_row(obs(reported_at=naive), "LAHORE")["reported_at"] == naive.replace(tzinfo=PKT)


def test_reader_keeps_raw_text_and_line_refs(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text(CSV, encoding="utf-8")
    rows = list(read_syn_csv(f))
    assert [r.raw_ref for r in rows] == [f"t.csv#L{i}" for i in range(2, 7)]
    assert rows[0].avg_raw == Decimal("1250.508") and rows[0].unit_raw == "PKR/40kg"
    assert rows[2].min_raw is None and rows[2].reported_at is None and rows[2].arrivals_unit is None


# --- with a database -------------------------------------------------------

def run(url, path, source="SYN"):
    with psycopg.connect(url, autocommit=True) as c:
        load_gazetteer(c)
        return load(c, source, read_syn_csv(path), "h" * 64, name_resolver(c))


def price_rows(url):
    with psycopg.connect(url) as c:
        return c.execute(
            "SELECT obs_id, source, mandi_id, crop_id, min_pkr100kg, max_pkr100kg, avg_pkr100kg, unit_raw, value_raw,"
            " reported_at, raw_ref, raw_sha256, outlier_flag, grade FROM price_obs ORDER BY obs_id"
        ).fetchall()


def test_known_rows_load_exactly_and_reload_changes_nothing(db, tmp_path):
    migrate(db)
    f = tmp_path / "t.csv"
    f.write_text(CSV, encoding="utf-8")
    res = run(db, f)
    assert res.upserted == 3
    assert res.unmatched == [("t.csv#L5", "Hyderabad")]  # not a mandi we know: refused, not guessed
    assert res.rejected == [("t.csv#L6", "unknown unit 'PKR/kg'")]

    first = price_rows(db)
    assert [r[1:4] for r in first] == [("SYN", "LAHORE", "ONION"), ("SYN", "OKARA", "ONION"), ("SYN", "SAHIWAL", "TOMATO")]
    lahore, okara, sahiwal = first
    assert lahore[4:9] == (Decimal("3000"), Decimal("3251.0"), Decimal("3126.27"), "PKR/40kg", Decimal("1250.508"))
    assert lahore[10:] == ("t.csv#L2", "h" * 64, "OK", None)
    assert okara[9] == datetime(2026, 11, 21, 18, 0, tzinfo=PKT)  # late publish kept
    assert sahiwal[4] is None and sahiwal[6] == Decimal("5000.00") and sahiwal[9] == datetime(2026, 11, 20, 18, 0, tzinfo=PKT)

    assert run(db, f).upserted == 3
    assert price_rows(db) == first  # same obs_ids, same values


def test_syn_and_syn_null_rows_coexist(db, tmp_path):
    migrate(db)
    f = tmp_path / "t.csv"
    f.write_text(CSV, encoding="utf-8")
    run(db, f, "SYN")
    run(db, f, "SYN-NULL")
    with psycopg.connect(db) as c:
        counts = c.execute("SELECT source, count(*) FROM price_obs GROUP BY source ORDER BY source").fetchall()
    assert counts == [("SYN", 3), ("SYN-NULL", 3)]


def test_generated_file_loads_end_to_end(db, tmp_path):
    _mod = importlib.util.spec_from_file_location("make_synthetic", ROOT / "scripts" / "make_synthetic.py")
    ms = importlib.util.module_from_spec(_mod)
    _mod.loader.exec_module(ms)
    spec = copy.deepcopy(SPEC)
    spec["period"]["end"] = date(2016, 1, 31)
    rows = ms.generate(spec, "SYN")
    ms.write_csv(rows, tmp_path / "syn.csv")

    migrate(db)
    res = run(db, tmp_path / "syn.csv")
    assert res.rejected == []
    assert {raw for _, raw in res.unmatched} <= {"Ukara"}  # the one reviewed refusal (D-018)
    assert res.upserted == len(rows) - len(res.unmatched)
    with psycopg.connect(db) as c:
        loaded = c.execute("SELECT raw_ref, mandi_id FROM price_obs WHERE source = 'SYN'").fetchall()
    assert len(loaded) == res.upserted
    assert all(mandi_id == rows[int(ref.split("#L")[1]) - 2]["truth_mandi_id"] for ref, mandi_id in loaded)  # line 2 = rows[0]
