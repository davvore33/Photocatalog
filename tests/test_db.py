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
