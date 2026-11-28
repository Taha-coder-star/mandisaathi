"""Gate G2 freeze hashes (task 10.3; 9.4 benchmark freeze D-046). Choices: DECISIONS.md D-049.

  python -m scripts.freeze_hash            print the benchmark and spec hashes (per file + one per group)
  python -m scripts.freeze_hash verify     re-hash and compare with the "- freeze <group> sha256 <hex>" lines in
                                           DECISIONS.md (exit 1 on a mismatch or a group not recorded yet)

A group hash is sha256 over sorted "relpath NUL file-sha256" lines, the same scheme as the task 2.5 sealing script, so
edits, additions, removals and renames all change it. (This file must never name the sealed folder; a CI read-guard
test checks every module under scripts/.) Each file is hashed with CRLF turned into LF first: a Windows checkout
(core.autocrlf=true) and the VM / CI then give the same hash for the same committed content (D-014's E2.csv lesson).
The benchmark audio is git-ignored; manifest.csv holds each audio file's sha256 (scripts/voice_pull.py), so hashing the
manifest covers the audio without putting voices in git. The seed lives inside spec.yaml (meta.seed), so the spec
hash covers it.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "DECISIONS.md"
GROUPS = {
    "benchmark": ["data/benchmark/SPEC.md", "data/benchmark/text.jsonl", "data/benchmark/voice.jsonl",
                  "data/benchmark/controls.jsonl", "data/benchmark/multiturn.jsonl", "data/benchmark/speakers.csv",
                  "data/benchmark/manifest.csv"],
    "spec": ["data/synthetic/spec.yaml"],
}
RECORD = re.compile(r"^- freeze (\S+) sha256 ([0-9a-f]{64})\b", re.M)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def group_hash(root: Path, paths: list[str]) -> tuple[str, dict[str, str]]:
    """(group sha256, {relpath: file sha256}). Every listed file must exist."""
    missing = [p for p in paths if not (root / p).is_file()]
    if missing:
        raise SystemExit(f"cannot freeze, missing: {', '.join(missing)}")
    files = {p: file_sha(root / p) for p in sorted(paths)}
    return hashlib.sha256("".join(f"{p}\0{h}\n" for p, h in files.items()).encode()).hexdigest(), files


def recorded(decisions: Path = DECISIONS) -> dict[str, str]:
    return dict(RECORD.findall(decisions.read_text(encoding="utf-8")))


def verify(root: Path = ROOT, decisions: Path = DECISIONS) -> list[str]:
    """Problems found (empty = every group matches its recorded hash)."""
    rec, problems = recorded(decisions), []
    for name, paths in GROUPS.items():
        if name not in rec:
            problems.append(f"{name}: not recorded in DECISIONS.md")
        elif (now := group_hash(root, paths)[0]) != rec[name]:
            problems.append(f"{name}: sha256 {now} != recorded {rec[name]}")
    return problems


def main(argv: list[str]) -> int:
    if argv[1:2] == ["verify"]:
        problems = verify()
        print("\n".join(problems) or "freeze hashes match")
        return 1 if problems else 0
    for name, paths in GROUPS.items():
        digest, files = group_hash(ROOT, paths)
        for p, h in files.items():
            print(f"  {h}  {p}")
        print(f"- freeze {name} sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
