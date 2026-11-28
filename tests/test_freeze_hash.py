"""Task 10.3: the G2 freeze hash command is deterministic and line-ending safe (D-049).
The guard "files still match the recorded hash" is added on freeze day, with the recorded hash (D-046 / G2 record)."""
import hashlib
import shutil
import subprocess

import pytest

from scripts import freeze_hash as fh

FILES = ["a/x.txt", "a/y.csv"]


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/x.txt").write_bytes(b"line one\nline two\n")
    (tmp_path / "a/y.csv").write_bytes(b"id,v\n1,2\n")
    return tmp_path


def test_same_content_same_hash_and_crlf_does_not_matter(tree):
    lf = fh.group_hash(tree, FILES)[0]
    assert fh.group_hash(tree, list(reversed(FILES)))[0] == lf  # order of the list does not matter
    (tree / "a/x.txt").write_bytes(b"line one\r\nline two\r\n")  # a Windows checkout of the same commit
    assert fh.group_hash(tree, FILES)[0] == lf


def test_any_edit_or_rename_changes_the_hash(tree):
    before = fh.group_hash(tree, FILES)[0]
    (tree / "a/y.csv").write_bytes(b"id,v\n1,3\n")
    assert fh.group_hash(tree, FILES)[0] != before
    (tree / "a/y.csv").rename(tree / "a/z.csv")
    assert fh.group_hash(tree, ["a/x.txt", "a/z.csv"])[0] != before


def test_a_missing_file_refuses_to_freeze(tree):
    with pytest.raises(SystemExit, match="missing: a/nope.txt"):
        fh.group_hash(tree, FILES + ["a/nope.txt"])


def test_verify_reports_unrecorded_and_mismatched_groups(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(fh, "GROUPS", {"g": FILES, "h": ["a/x.txt"]})
    d = tmp_path / "D.md"
    d.write_text(f"- freeze g sha256 {fh.group_hash(tree, FILES)[0]}\n- freeze h sha256 {'0' * 64}\n", encoding="utf-8")
    assert fh.verify(tree, d) == [f"h: sha256 {fh.group_hash(tree, ['a/x.txt'])[0]} != recorded {'0' * 64}"]
    d.write_text("nothing recorded\n", encoding="utf-8")
    assert fh.verify(tree, d) == ["g: not recorded in DECISIONS.md", "h: not recorded in DECISIONS.md"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_spec_file_hash_equals_the_committed_blob():
    """The working file on any OS hashes like the committed (LF) bytes, so the VM, CI and a Windows laptop agree."""
    blob = subprocess.run(["git", "show", "HEAD:data/synthetic/spec.yaml"], cwd=fh.ROOT, capture_output=True, check=True)
    assert fh.file_sha(fh.ROOT / "data/synthetic/spec.yaml") == hashlib.sha256(blob.stdout).hexdigest()
