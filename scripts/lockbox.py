"""Lockbox sealing (task 2.5, docs/lockbox_procedure.md).

  python scripts/lockbox.py seal <name>    hash data/lockbox/<name>/ and record it in DECISIONS.md
  python scripts/lockbox.py verify [name]  re-hash and compare with DECISIONS.md (exit 1 on mismatch)
  python scripts/lockbox.py holdout        write the synthetic holdout year (task 9.3), then seal holdout + holdout_null

The only file allowed to name the sealed folder in code; tests/test_lockbox.py fails if any other
module under app/, mandi/ or scripts/ mentions it.
"""
import hashlib
import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKBOX = ROOT / "data" / "lockbox"
DECISIONS = ROOT / "DECISIONS.md"
RECORD = re.compile(r"^- lockbox (\S+) sha256 ([0-9a-f]{64})\b", re.M)


def folder_hash(folder: Path) -> str:
    """sha256 over sorted 'relpath NUL file-sha256' lines: detects edits, additions, removals and renames."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    if not files:
        raise SystemExit(f"{folder} is empty or missing: nothing to seal")
    lines = [f"{p.relative_to(folder).as_posix()}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n" for p in files]
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def recorded(decisions: Path = DECISIONS) -> dict[str, str]:
    return dict(RECORD.findall(decisions.read_text(encoding="utf-8")))


def seal(name: str, lockbox: Path = LOCKBOX, decisions: Path = DECISIONS) -> str:
    if name in recorded(decisions):
        raise SystemExit(f"{name} is already sealed; a seal is never replaced")
    digest = folder_hash(lockbox / name)
    text = decisions.read_text(encoding="utf-8")
    next_id = max(int(i) for i in re.findall(r"^## D-(\d+)", text, re.M)) + 1
    entry = (
        f"\n## D-{next_id:03d} · {date.today()} · Taha · CONFIRMED\n"
        f"Lockbox `{name}` sealed (docs/lockbox_procedure.md). Nobody has run a model on it.\n"
        f"- lockbox {name} sha256 {digest}\n"
    )
    decisions.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")
    return digest


def verify(name: str | None = None, lockbox: Path = LOCKBOX, decisions: Path = DECISIONS) -> bool:
    """True if every sealed folder (or just `name`) that exists on disk still matches its recorded hash."""
    ok = True
    for n, digest in recorded(decisions).items():
        if name not in (None, n) or not (lockbox / n).exists():
            continue
        match = folder_hash(lockbox / n) == digest
        print(f"{n}: {'OK' if match else 'CHANGED since sealing'}")
        ok &= match
    return ok


def _generator():
    """scripts/make_synthetic.py by path: this file runs as a script (scripts/ on sys.path) and is loaded by path in tests."""
    spec = importlib.util.spec_from_file_location("make_synthetic", ROOT / "scripts" / "make_synthetic.py")
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    return ms


def write_holdout(lockbox: Path = LOCKBOX) -> dict[str, int]:
    """Task 9.3 rehearsal: the spec's holdout year from the same seed, SYN (+ the wheat months) in `holdout/` and
    SYN-NULL in `holdout_null/`. Written once (an existing folder is refused). Returns row counts per file: the only
    look allowed before sealing (procedure rule 3)."""
    ms = _generator()
    spec = ms.load_spec()
    start, end = spec["period"]["holdout"]["start"], spec["period"]["holdout"]["end"]
    counts = {}
    for name, variant in (("holdout", "SYN"), ("holdout_null", "SYN-NULL")):
        folder = lockbox / name
        if folder.exists():
            raise SystemExit(f"{folder} exists: a lockbox folder is written once")
        files = {ms.FILES[variant]: [r for r in ms.generate(spec, variant) if start <= date.fromisoformat(r["market_date"]) <= end]}
        if variant == "SYN":  # F3 panel: the months that start inside the holdout year
            files["wheat_monthly.csv"] = [r for r in ms.wheat_monthly(spec) if start <= date.fromisoformat(r["month"]) <= end]
        for fname, rows in files.items():
            ms.write_csv(rows, folder / fname)
            counts[f"{name}/{fname}"] = len(rows)
    return counts


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "seal" and len(args) == 1:
        print(f"sealed {args[0]}: {seal(args[0])}")
    elif cmd == "holdout" and not args:
        for f, n in write_holdout().items():
            print(f"{f}: {n} rows")
    elif cmd == "verify" and len(args) <= 1:
        sys.exit(0 if verify(*args) else 1)
    else:
        sys.exit(__doc__)
