from pathlib import Path

from photocatalog import db


def test_insert_and_get_image(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")
    image_id = db.insert_image(
        conn,
        {
            "path": "/photos/a.jpg",
            "file_hash": "abc123",
            "file_size": 1000,
            "mtime": 123.0,
            "added_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )

    row = db.get_image(conn, image_id)
    assert row["path"] == "/photos/a.jpg"

    by_path = db.get_image_by_path(conn, "/photos/a.jpg")
    assert by_path["id"] == image_id

    by_hash = db.get_image_by_hash(conn, "abc123")
    assert by_hash["id"] == image_id


def test_tags_roundtrip(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")
    image_id = db.insert_image(
        conn,
        {
            "path": "/photos/b.jpg",
            "file_hash": "def456",
            "file_size": 1000,
            "mtime": 123.0,
            "added_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )

    db.set_tags(conn, image_id, ["beach", "sunset", "beach"])
    tags = db.get_tags_for_image(conn, image_id)
    assert tags == ["beach", "sunset"]

    db.set_tags(conn, image_id, ["mountain"])
    tags = db.get_tags_for_image(conn, image_id)
    assert tags == ["mountain"]


def test_stats(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")
    image_id = db.insert_image(
        conn,
        {
            "path": "/photos/c.jpg",
            "file_hash": "ghi789",
            "file_size": 1000,
            "mtime": 123.0,
            "added_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "tags_status": "done",
        },
    )
    db.set_tags(conn, image_id, ["beach"])

    data = db.stats(conn)
    assert data["total_images"] == 1
    assert data["by_status"] == {"done": 1}
    assert data["top_tags"] == [("beach", 1)]


def test_record_tagging_event_and_model_speed_stats(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")

    db.record_tagging_event(conn, "qwen3-vl:8b", 4.0, True, "2026-01-01T00:00:00")
    db.record_tagging_event(conn, "qwen3-vl:8b", 6.0, True, "2026-01-01T00:00:01")
    db.record_tagging_event(conn, "qwen3-vl:8b", 1.0, False, "2026-01-01T00:00:02")
    db.record_tagging_event(conn, "llava:7b", 2.0, True, "2026-01-01T00:00:03")

    stats = db.model_speed_stats(conn)
    by_model = {row["model"]: row for row in stats}

    assert by_model["qwen3-vl:8b"]["n"] == 3
    assert by_model["qwen3-vl:8b"]["successes"] == 2
    # average is over successful events only: (4.0 + 6.0) / 2 = 5.0
    assert by_model["qwen3-vl:8b"]["avg_seconds"] == 5.0

    assert by_model["llava:7b"]["n"] == 1
    assert by_model["llava:7b"]["successes"] == 1
    assert by_model["llava:7b"]["avg_seconds"] == 2.0


def test_model_speed_stats_with_only_failures_has_no_average(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")
    db.record_tagging_event(conn, "broken-model", 0.5, False, "2026-01-01T00:00:00")

    stats = db.model_speed_stats(conn)
    assert stats[0]["model"] == "broken-model"
    assert stats[0]["avg_seconds"] is None


def test_stats_includes_empty_model_stats_when_no_events(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")
    data = db.stats(conn)
    assert data["model_stats"] == []


def test_delete_image(tmp_path: Path):
    conn = db.connect(tmp_path / "catalog.db")
    image_id = db.insert_image(
        conn,
        {
            "path": "/photos/d.jpg",
            "file_hash": "jkl000",
            "file_size": 1000,
            "mtime": 123.0,
            "added_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    )
    db.delete_image(conn, image_id)
    assert db.get_image(conn, image_id) is None
