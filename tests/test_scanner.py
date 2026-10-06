import os
import shutil
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from photocatalog import db, scanner, thumbnails, vision
from photocatalog.hashing import sha256_file


def _make_photos(folder: Path, n: int) -> None:
    folder.mkdir(exist_ok=True)
    for i in range(n):
        Image.new("RGB", (10, 10), (i * 10 % 255, 50, 50)).save(folder / f"p{i}.jpg", "JPEG")


def test_scan_stage_a_completes_without_cancel(tmp_path: Path):
    folder = tmp_path / "photos"
    _make_photos(folder, 3)
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()

    completed = scanner.scan_stage_a(conn, folder, summary)

    assert completed is True
    assert summary.added == 3


def test_scan_stage_a_stops_when_cancelled(tmp_path: Path):
    folder = tmp_path / "photos"
    _make_photos(folder, 5)
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()

    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before the walk starts

    completed = scanner.scan_stage_a(conn, folder, summary, cancel_event=cancel_event)

    assert completed is False
    assert summary.added == 0


def test_scan_stage_b_stops_when_cancelled(tmp_path: Path):
    folder = tmp_path / "photos"
    _make_photos(folder, 3)
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, folder, summary)

    cancel_event = threading.Event()
    call_count = 0

    def fake_tags(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            cancel_event.set()  # cancel after the first image is tagged
        return ["x"], "{}"

    with patch("photocatalog.vision.generate_tags", side_effect=fake_tags):
        completed = scanner.scan_stage_b(conn, summary, cancel_event=cancel_event)

    assert completed is False
    assert summary.tagged == 1  # stopped before tagging the remaining images


def test_scan_stage_b_records_tagging_events_on_success(tmp_path: Path):
    folder = tmp_path / "photos"
    _make_photos(folder, 2)
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, folder, summary)

    def slow_tags(*_args, **_kwargs):
        time.sleep(0.05)
        return ["x"], "{}"

    with patch("photocatalog.vision.generate_tags", side_effect=slow_tags):
        scanner.scan_stage_b(conn, summary, model="test-model")

    events = conn.execute(
        "SELECT model, duration_seconds, success FROM tagging_events"
    ).fetchall()
    assert len(events) == 2
    for event in events:
        assert event["model"] == "test-model"
        assert event["success"] == 1
        assert event["duration_seconds"] >= 0.05

    assert summary.tag_seconds >= 0.1
    assert summary.tag_seconds == sum(e["duration_seconds"] for e in events)


def test_scan_stage_b_records_tagging_events_on_failure(tmp_path: Path):
    folder = tmp_path / "photos"
    _make_photos(folder, 1)
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, folder, summary)

    from photocatalog import vision

    with patch("photocatalog.vision.generate_tags", side_effect=vision.VisionError("boom")):
        scanner.scan_stage_b(conn, summary, model="test-model")

    events = conn.execute(
        "SELECT model, duration_seconds, success FROM tagging_events"
    ).fetchall()
    assert len(events) == 1
    assert events[0]["success"] == 0
    assert summary.tag_errors == 1
    assert summary.tag_seconds == 0.0  # only successful taggings count toward this total


# --- regression tests -------------------------------------------------------


def _solid(path: Path, color) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), color).save(path, "JPEG")


def _scan_a(conn, folder: Path) -> scanner.ScanSummary:
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, folder, summary)
    return summary


def _count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]


def test_stage_a_skips_corrupt_image_and_keeps_scanning(tmp_path: Path):
    folder = tmp_path / "photos"
    _solid(folder / "a_good.jpg", (200, 10, 10))
    bad = folder / "b_bad.jpg"
    Image.effect_noise((600, 600), 80).convert("RGB").save(bad, "JPEG")
    bad.write_bytes(bad.read_bytes()[:-3000])  # truncated: opens fine, fails on decode
    _solid(folder / "c_good.jpg", (10, 10, 200))
    conn = db.connect(tmp_path / "catalog.db")

    summary = _scan_a(conn, folder)

    assert summary.added == 2
    assert summary.skipped == [str(bad.resolve())]


def test_stage_a_handles_swapped_filenames(tmp_path: Path):
    folder = tmp_path / "photos"
    a, b, tmp = folder / "a.jpg", folder / "b.jpg", folder / "tmp.jpg"
    _solid(a, (200, 10, 10))
    _solid(b, (10, 10, 200))
    conn = db.connect(tmp_path / "catalog.db")
    _scan_a(conn, folder)

    a.rename(tmp)
    b.rename(a)
    tmp.rename(b)
    summary = _scan_a(conn, folder)  # used to raise IntegrityError (UNIQUE path)

    assert summary.updated == 2
    assert _count(conn) == 2
    for path in (a, b):
        row = db.get_image_by_path(conn, str(path.resolve()))
        assert row["file_hash"] == sha256_file(path)
        assert thumbnails.thumbnail_path(row["file_hash"]).exists()


def test_duplicate_copies_are_cataloged_and_stable_across_scans(tmp_path: Path):
    folder = tmp_path / "photos"
    _solid(folder / "a" / "x.jpg", (200, 10, 10))
    shutil.copy(folder / "a" / "x.jpg", folder / "b_x.jpg")
    conn = db.connect(tmp_path / "catalog.db")

    first = _scan_a(conn, folder)
    assert (first.added, first.moved) == (2, 0)
    assert _count(conn) == 2

    for _ in range(2):  # used to flip-flop the single row between the two paths
        again = _scan_a(conn, folder)
        assert (again.added, again.moved, again.unchanged) == (0, 0, 2)
    assert _count(conn) == 2


def test_duplicate_copy_inherits_tags_and_status(tmp_path: Path):
    folder = tmp_path / "photos"
    original = folder / "x.jpg"
    _solid(original, (200, 10, 10))
    conn = db.connect(tmp_path / "catalog.db")
    _scan_a(conn, folder)
    row = db.get_image_by_path(conn, str(original.resolve()))
    db.set_tags(conn, row["id"], ["cat", "sofa"])
    db.update_image(conn, row["id"], {"tags_status": "done"})

    shutil.copy(original, folder / "copy.jpg")
    _scan_a(conn, folder)

    copy = db.get_image_by_path(conn, str((folder / "copy.jpg").resolve()))
    assert copy["tags_status"] == "done"
    assert db.get_tags_for_image(conn, copy["id"]) == ["cat", "sofa"]


def test_moved_file_keeps_its_row_and_is_not_rehashed_next_scan(tmp_path: Path):
    folder = tmp_path / "photos"
    _solid(folder / "x.jpg", (200, 10, 10))
    conn = db.connect(tmp_path / "catalog.db")
    _scan_a(conn, folder)

    (folder / "sub").mkdir()
    (folder / "x.jpg").rename(folder / "sub" / "x.jpg")
    moved = _scan_a(conn, folder)
    assert (moved.moved, moved.added) == (1, 0)
    assert _count(conn) == 1

    settled = _scan_a(conn, folder)
    assert (settled.unchanged, settled.moved) == (1, 0)


def test_changed_file_drops_its_old_thumbnail(tmp_path: Path):
    folder = tmp_path / "photos"
    path = folder / "x.jpg"
    _solid(path, (200, 10, 10))
    conn = db.connect(tmp_path / "catalog.db")
    _scan_a(conn, folder)
    old_hash = db.get_image_by_path(conn, str(path.resolve()))["file_hash"]
    assert thumbnails.thumbnail_path(old_hash).exists()

    _solid(path, (10, 200, 10))
    os.utime(path, (time.time() + 10, time.time() + 10))
    summary = _scan_a(conn, folder)

    new_hash = db.get_image_by_path(conn, str(path.resolve()))["file_hash"]
    assert summary.updated == 1
    assert new_hash != old_hash
    assert not thumbnails.thumbnail_path(old_hash).exists()
    assert thumbnails.thumbnail_path(new_hash).exists()


def test_prune_only_touches_the_given_folder(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    _solid(a / "1.jpg", (200, 10, 10))
    _solid(b / "2.jpg", (10, 200, 10))
    conn = db.connect(tmp_path / "catalog.db")
    _scan_a(conn, a)
    _scan_a(conn, b)
    hash_a = db.get_image_by_path(conn, str((a / "1.jpg").resolve()))["file_hash"]
    (a / "1.jpg").unlink()
    (b / "2.jpg").unlink()  # e.g. an unmounted volume: must survive a scoped prune

    removed = scanner.prune(conn, folder=a)

    assert removed == [str((a / "1.jpg").resolve())]
    assert _count(conn) == 1
    assert not thumbnails.thumbnail_path(hash_a).exists()
    assert len(scanner.prune(conn)) == 1  # unscoped prune still sees the rest


def test_prune_keeps_thumbnail_shared_with_a_surviving_copy(tmp_path: Path):
    folder = tmp_path / "photos"
    _solid(folder / "x.jpg", (200, 10, 10))
    shutil.copy(folder / "x.jpg", folder / "copy.jpg")
    conn = db.connect(tmp_path / "catalog.db")
    _scan_a(conn, folder)
    file_hash = sha256_file(folder / "x.jpg")

    (folder / "copy.jpg").unlink()
    scanner.prune(conn)

    assert _count(conn) == 1
    assert thumbnails.thumbnail_path(file_hash).exists()


def test_stage_b_only_tags_rows_under_the_given_folder(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    _solid(a / "1.jpg", (200, 10, 10))
    _solid(b / "2.jpg", (10, 200, 10))
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, a, summary)
    scanner.scan_stage_a(conn, b, summary)

    with patch("photocatalog.vision.generate_tags", return_value=(["x"], "{}")):
        scanner.scan_stage_b(conn, summary, folder=a)

    status = dict(conn.execute("SELECT path, tags_status FROM images").fetchall())
    assert status[str((a / "1.jpg").resolve())] == "done"
    assert status[str((b / "2.jpg").resolve())] == "pending"


def test_stage_b_folder_filter_accepts_filesystem_root(tmp_path: Path):
    folder = tmp_path / "photos"
    _solid(folder / "1.jpg", (200, 10, 10))
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, folder, summary)

    with patch("photocatalog.vision.generate_tags", return_value=(["x"], "{}")):
        scanner.scan_stage_b(conn, summary, folder=Path("/"))

    assert summary.tagged == 1


def test_stage_b_aborts_without_marking_errors_when_vision_unavailable(tmp_path: Path):
    folder = tmp_path / "photos"
    _make_photos(folder, 3)
    conn = db.connect(tmp_path / "catalog.db")
    summary = scanner.ScanSummary()
    scanner.scan_stage_a(conn, folder, summary)

    with patch(
        "photocatalog.vision.generate_tags", side_effect=vision.VisionUnavailable("ollama down")
    ) as fake:
        with pytest.raises(vision.VisionUnavailable):
            scanner.scan_stage_b(conn, summary)

    assert fake.call_count == 1  # gave up immediately instead of failing every image
    assert summary.tag_errors == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM images WHERE tags_status = 'pending'"
    ).fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM tagging_events").fetchone()[0] == 0


def test_extraction_records_true_size_even_though_jpeg_is_decoded_downscaled(tmp_path: Path):
    folder = tmp_path / "photos"
    folder.mkdir()
    path = folder / "big.jpg"
    Image.new("RGB", (2400, 1600), (200, 20, 20)).save(path, "JPEG")
    conn = db.connect(tmp_path / "catalog.db")

    _scan_a(conn, folder)

    row = db.get_image_by_path(conn, str(path.resolve()))
    assert (row["width"], row["height"]) == (2400, 1600)
    assert row["dominant_color_name"] is not None and "red" in row["dominant_color_name"]
    with Image.open(thumbnails.thumbnail_path(row["file_hash"])) as thumb:
        assert max(thumb.size) == 320  # still a full-size thumbnail, not a 1/8-scale one blown up


def test_thumbnail_respects_exif_orientation_after_draft_decode(tmp_path: Path):
    folder = tmp_path / "photos"
    folder.mkdir()
    path = folder / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # needs a 90° rotation: landscape pixels, portrait when displayed
    Image.new("RGB", (1600, 1000), (20, 20, 200)).save(path, "JPEG", exif=exif)
    conn = db.connect(tmp_path / "catalog.db")

    _scan_a(conn, folder)

    row = db.get_image_by_path(conn, str(path.resolve()))
    with Image.open(thumbnails.thumbnail_path(row["file_hash"])) as thumb:
        assert thumb.height > thumb.width
