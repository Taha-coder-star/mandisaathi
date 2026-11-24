"""Lockbox sealing (task 2.5, docs/lockbox_procedure.md).

  python scripts/lockbox.py seal <name>    hash data/lockbox/<name>/ and record it in DECISIONS.md
  python scripts/lockbox.py verify [name]  re-hash and compare with DECISIONS.md (exit 1 on mismatch)

The only file allowed to name the sealed folder in code; tests/test_lockbox.py fails if any other
module under app/, mandi/ or scripts/ mentions it.
"""
import hashlib
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


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "seal" and len(args) == 1:
        print(f"sealed {args[0]}: {seal(args[0])}")
    elif cmd == "verify" and len(args) <= 1:
        sys.exit(0 if verify(*args) else 1)
    else:
        sys.exit(__doc__)
