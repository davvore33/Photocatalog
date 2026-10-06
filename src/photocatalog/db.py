import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    path                    TEXT NOT NULL UNIQUE,
    file_hash               TEXT NOT NULL,
    file_size               INTEGER NOT NULL,
    mtime                   REAL NOT NULL,
    width                   INTEGER,
    height                  INTEGER,
    format                  TEXT,
    added_at                TEXT NOT NULL,
    updated_at              TEXT NOT NULL,

    exif_json               TEXT,
    exif_datetime_original  TEXT,
    exif_camera_make        TEXT,
    exif_camera_model       TEXT,
    exif_lens_model         TEXT,
    exif_gps_lat            REAL,
    exif_gps_lon            REAL,

    dominant_color_hex      TEXT,
    dominant_color_name     TEXT,
    palette_json             TEXT,

    tags_status              TEXT NOT NULL DEFAULT 'pending',
    vision_model              TEXT,
    vision_raw_response        TEXT,
    error_message               TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS image_tags (
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (image_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_images_hash     ON images(file_hash);
CREATE INDEX IF NOT EXISTS idx_images_datetime ON images(exif_datetime_original);
CREATE INDEX IF NOT EXISTS idx_images_camera   ON images(exif_camera_model);
CREATE INDEX IF NOT EXISTS idx_images_color    ON images(dominant_color_name);
CREATE INDEX IF NOT EXISTS idx_images_status   ON images(tags_status);
CREATE INDEX IF NOT EXISTS idx_image_tags_tag  ON image_tags(tag_id);

CREATE TABLE IF NOT EXISTS tagging_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    model             TEXT NOT NULL,
    duration_seconds  REAL NOT NULL,
    success           INTEGER NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tagging_events_model ON tagging_events(model);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def open_db(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_image_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM images WHERE path = ?", (path,)).fetchone()


def get_image_by_hash(conn: sqlite3.Connection, file_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM images WHERE file_hash = ?", (file_hash,)
    ).fetchone()


def get_images_by_hash(conn: sqlite3.Connection, file_hash: str) -> list[sqlite3.Row]:
    """Every row with this content hash: identical copies of a file share one hash."""
    return conn.execute(
        "SELECT * FROM images WHERE file_hash = ? ORDER BY id", (file_hash,)
    ).fetchall()


def get_image(conn: sqlite3.Connection, image_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def insert_image(conn: sqlite3.Connection, fields: dict) -> int:
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(
        f"INSERT INTO images ({columns}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    conn.commit()
    return cur.lastrowid


def update_image(conn: sqlite3.Connection, image_id: int, fields: dict) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE images SET {assignments} WHERE id = ?",
        (*fields.values(), image_id),
    )
    conn.commit()


def update_image_path(conn: sqlite3.Connection, image_id: int, new_path: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE images SET path = ?, updated_at = ? WHERE id = ?",
        (new_path, updated_at, image_id),
    )
    conn.commit()


def delete_image(conn: sqlite3.Connection, image_id: int) -> None:
    conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.commit()


def set_tags(conn: sqlite3.Connection, image_id: int, tag_names: list[str]) -> None:
    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
    for name in tag_names:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        tag_id = conn.execute(
            "SELECT id FROM tags WHERE name = ?", (name,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO image_tags (image_id, tag_id) VALUES (?, ?)",
            (image_id, tag_id),
        )
    conn.commit()


def get_tags_for_image(conn: sqlite3.Connection, image_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN image_tags it ON it.tag_id = t.id
        WHERE it.image_id = ?
        ORDER BY t.name
        """,
        (image_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def all_paths(conn: sqlite3.Connection) -> list[str]:
    return [row["path"] for row in conn.execute("SELECT path FROM images")]


def images_by_status(conn: sqlite3.Connection, statuses: list[str]) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT * FROM images WHERE tags_status IN ({placeholders})", statuses
    ).fetchall()


def record_tagging_event(
    conn: sqlite3.Connection,
    model: str,
    duration_seconds: float,
    success: bool,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO tagging_events (model, duration_seconds, success, created_at) "
        "VALUES (?, ?, ?, ?)",
        (model, duration_seconds, int(success), created_at),
    )
    conn.commit()


def model_speed_stats(conn: sqlite3.Connection) -> list[dict]:
    """Per-model tagging throughput, most-used model first."""
    rows = conn.execute(
        """
        SELECT
            model,
            COUNT(*) AS n,
            SUM(success) AS successes,
            AVG(CASE WHEN success THEN duration_seconds END) AS avg_seconds
        FROM tagging_events
        GROUP BY model
        ORDER BY n DESC
        """
    ).fetchall()
    return [
        {
            "model": row["model"],
            "n": row["n"],
            "successes": row["successes"],
            "avg_seconds": row["avg_seconds"],
        }
        for row in rows
    ]


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) AS n FROM images").fetchone()["n"]
    by_status = {
        row["tags_status"]: row["n"]
        for row in conn.execute(
            "SELECT tags_status, COUNT(*) AS n FROM images GROUP BY tags_status"
        )
    }
    top_tags = conn.execute(
        """
        SELECT t.name, COUNT(*) AS n FROM tags t
        JOIN image_tags it ON it.tag_id = t.id
        GROUP BY t.id ORDER BY n DESC LIMIT 20
        """
    ).fetchall()
    return {
        "total_images": total,
        "by_status": by_status,
        "top_tags": [(row["name"], row["n"]) for row in top_tags],
        "model_stats": model_speed_stats(conn),
    }
