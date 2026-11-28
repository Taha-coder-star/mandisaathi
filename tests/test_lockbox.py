"""Task 2.5: sealing script + CI read-guard (T6: lockbox untouched until S8)."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("lockbox", ROOT / "scripts" / "lockbox.py")
lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lb)

GUARDED = ["app", "mandi", "scripts"]
ALLOWED = {"scripts/lockbox.py"}


def offenders(root: Path) -> list[str]:
    """Python files that mention the sealed folder, other than the sealing script."""
    return [
        p.relative_to(root).as_posix()
        for d in GUARDED
        for p in (root / d).rglob("*.py")
        if p.relative_to(root).as_posix() not in ALLOWED and re.search("lockbox", p.read_text(encoding="utf-8"), re.I)
    ]


def test_no_code_path_reads_the_lockbox():
    assert offenders(ROOT) == []


def test_guard_catches_a_planted_reader(tmp_path):
    (tmp_path / "mandi").mkdir()
    (tmp_path / "mandi" / "peek.py").write_text("df = read('data/lockbox/holdout/x.csv')\n")
    assert offenders(tmp_path) == ["mandi/peek.py"]


@pytest.fixture
def box(tmp_path):
    (tmp_path / "lockbox" / "holdout").mkdir(parents=True)
    (tmp_path / "lockbox" / "holdout" / "a.csv").write_text("1,2\n")
    (tmp_path / "lockbox" / "holdout" / "sub").mkdir()
    (tmp_path / "lockbox" / "holdout" / "sub" / "b.csv").write_text("3,4\n")
    dec = tmp_path / "DECISIONS.md"
    dec.write_text("# Decisions\n\n## D-007 · 2026-11-24 · Taha · CONFIRMED\nx\n", encoding="utf-8")
    return tmp_path / "lockbox", dec


def test_seal_records_hash_with_next_id_and_verifies(box):
    lockbox, dec = box
    digest = lb.seal("holdout", lockbox, dec)
    assert "## D-008 " in dec.read_text(encoding="utf-8")
    assert lb.recorded(dec) == {"holdout": digest}
    assert lb.verify("holdout", lockbox, dec)


@pytest.mark.parametrize("tamper", ["edit", "add", "remove", "rename"])
def test_any_change_breaks_verify(box, tamper):
    lockbox, dec = box
    lb.seal("holdout", lockbox, dec)
    a, b = lockbox / "holdout" / "a.csv", lockbox / "holdout" / "sub" / "b.csv"
    if tamper == "edit":
        a.write_text("1,9\n")
    elif tamper == "add":
        (lockbox / "holdout" / "c.csv").write_text("5\n")
    elif tamper == "remove":
        b.unlink()
    else:
        a.rename(lockbox / "holdout" / "z.csv")
    assert not lb.verify("holdout", lockbox, dec)


def test_seal_is_never_replaced_and_empty_folder_refused(box):
    lockbox, dec = box
    lb.seal("holdout", lockbox, dec)
    with pytest.raises(SystemExit, match="already sealed"):
        lb.seal("holdout", lockbox, dec)
    (lockbox / "empty").mkdir()
    with pytest.raises(SystemExit, match="nothing to seal"):
        lb.seal("empty", lockbox, dec)


def test_real_lockbox_if_present_matches_decisions():
    # T6 hash check: locally present sealed folders must still match; CI has none, so this is a no-op there.
    assert lb.verify()


def test_holdout_writes_only_the_holdout_year_once(tmp_path):
    """Task 9.3: SYN (+ wheat months) and SYN-NULL holdout folders; nothing before the holdout start; never rewritten."""
    import csv
    from datetime import date

    counts = lb.write_holdout(tmp_path)
    assert set(counts) == {"holdout/syn.csv", "holdout/wheat_monthly.csv", "holdout_null/syn_null.csv"}
    assert counts["holdout/syn.csv"] == counts["holdout_null/syn_null.csv"] > 0 and counts["holdout/wheat_monthly.csv"] == 12
    cols = {"holdout/syn.csv": "market_date", "holdout_null/syn_null.csv": "market_date", "holdout/wheat_monthly.csv": "month"}
    for f, col in cols.items():
        with open(tmp_path / f, encoding="utf-8", newline="") as fh:
            days = {date.fromisoformat(r[col]) for r in csv.DictReader(fh)}
        assert date(2025, 12, 19) <= min(days) and max(days) <= date(2026, 12, 18), f
    with pytest.raises(SystemExit):
        lb.write_holdout(tmp_path)
