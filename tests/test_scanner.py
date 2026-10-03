import threading
import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photocatalog import db, scanner


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
