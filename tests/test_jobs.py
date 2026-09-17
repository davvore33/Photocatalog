import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from photocatalog import db
from photocatalog.viewer import jobs


def _wait_until_idle_or_done(timeout=5.0):
    deadline = time.time() + timeout
    status = jobs.get_status()
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
        status = jobs.get_status()
    return status


def test_start_scan_runs_in_background_and_completes(tmp_path: Path):
    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (20, 20), (10, 20, 30)).save(folder / "a.jpg", "JPEG")
    db_path = tmp_path / "catalog.db"

    with patch("photocatalog.vision.generate_tags", return_value=(["test"], "{}")):
        assert jobs.start_scan(db_path, folder, "fake-model") is True
        status = _wait_until_idle_or_done()

    assert status["status"] == "done"
    assert status["counts"]["added"] == 1
    assert status["counts"]["tagged"] == 1

    with db.open_db(db_path) as conn:
        assert db.stats(conn)["total_images"] == 1


def test_start_scan_rejects_concurrent_run(tmp_path: Path):
    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (20, 20), (10, 20, 30)).save(folder / "a.jpg", "JPEG")
    db_path = tmp_path / "catalog.db"

    def slow_tags(*_args, **_kwargs):
        time.sleep(0.5)
        return ["x"], "{}"

    with patch("photocatalog.vision.generate_tags", side_effect=slow_tags):
        assert jobs.start_scan(db_path, folder, "fake-model") is True
        assert jobs.start_scan(db_path, folder, "fake-model") is False
        _wait_until_idle_or_done()


def test_request_stop_cancels_running_scan(tmp_path: Path):
    folder = tmp_path / "photos"
    folder.mkdir()
    for i in range(3):
        Image.new("RGB", (10, 10), (i * 10, 20, 30)).save(folder / f"{i}.jpg", "JPEG")
    db_path = tmp_path / "catalog.db"

    def slow_tags(*_args, **_kwargs):
        time.sleep(0.3)
        return ["x"], "{}"

    with patch("photocatalog.vision.generate_tags", side_effect=slow_tags):
        assert jobs.start_scan(db_path, folder, "fake-model") is True
        # let it get past stage A into tagging before stopping
        for _ in range(50):
            if jobs.get_status()["phase"] == "tagging":
                break
            time.sleep(0.05)
        assert jobs.request_stop() is True
        status = _wait_until_idle_or_done()

    assert status["status"] == "cancelled"
    assert status["counts"]["tagged"] < 3


def test_request_stop_when_idle_returns_false():
    assert jobs.request_stop() is False


def test_start_scan_reports_error(tmp_path: Path):
    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (20, 20), (10, 20, 30)).save(folder / "a.jpg", "JPEG")
    db_path = tmp_path / "catalog.db"

    with patch("photocatalog.scanner.scan_stage_a", side_effect=RuntimeError("boom")):
        assert jobs.start_scan(db_path, folder, "fake-model") is True
        status = _wait_until_idle_or_done()

    assert status["status"] == "error"
    assert "boom" in status["error"]
