from pathlib import Path

from photocatalog.hashing import sha256_file, stat_fingerprint


def test_sha256_file_deterministic(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")

    h1 = sha256_file(f)
    h2 = sha256_file(f)
    assert h1 == h2
    assert len(h1) == 64


def test_sha256_file_differs_on_content(tmp_path: Path):
    f1 = tmp_path / "a.txt"
    f1.write_bytes(b"hello")
    f2 = tmp_path / "b.txt"
    f2.write_bytes(b"world")

    assert sha256_file(f1) != sha256_file(f2)


def test_stat_fingerprint(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")

    size, mtime = stat_fingerprint(f)
    assert size == 11
    assert mtime > 0
