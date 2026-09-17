import threading
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
