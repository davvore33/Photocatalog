import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import color_extract, config, db, exif_extract, raw_extract, thumbnails, vision
from .hashing import sha256_file, stat_fingerprint

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScanSummary:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    moved: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)
    tagged: int = 0
    tag_errors: int = 0
    tag_seconds: float = 0.0


def iter_image_files(folder: Path, skip_raw: bool = False):
    for path in sorted(folder.rglob("*")):
        suffix = path.suffix.lower()
        if skip_raw and suffix in raw_extract.RAW_EXTENSIONS:
            continue
        if suffix not in config.SUPPORTED_EXTENSIONS:
            continue
        if path.is_file():
            yield path


def _extract_static_fields_raw(path: Path, file_hash: str) -> dict | None:
    """Same as _extract_static_fields, for RAW files: everything is derived from
    the embedded JPEG preview rather than full demosaicing of the sensor data."""
    try:
        preview_img, preview_bytes, (width, height) = raw_extract.extract_preview(path)
    except raw_extract.RawPreviewError:
        return None

    with preview_img:
        exif = exif_extract.extract_exif(path, fallback_bytes=preview_bytes)
        promoted = exif_extract.promote_fields(exif)
        color = color_extract.dominant_color_from_image(preview_img)
        thumbnails.generate_thumbnail_from_image(preview_img, file_hash)

    fields = {
        "width": width,
        "height": height,
        "format": path.suffix.upper().lstrip("."),
        "exif_json": json.dumps(exif),
        "dominant_color_hex": color["hex"],
        "dominant_color_name": color["name"],
        "palette_json": color_extract.palette_to_json(color["palette"]),
    }
    fields.update(promoted)
    return fields


def _extract_static_fields(path: Path, file_hash: str) -> dict | None:
    """Everything that doesn't need the network: dimensions, EXIF, color, thumbnail."""
    if path.suffix.lower() in raw_extract.RAW_EXTENSIONS:
        return _extract_static_fields_raw(path, file_hash)

    try:
        with Image.open(path) as img:
            width, height = img.size
            fmt = img.format
    except (UnidentifiedImageError, OSError):
        return None

    exif = exif_extract.extract_exif(path)
    promoted = exif_extract.promote_fields(exif)
    color = color_extract.extract_dominant_color(path)
    thumbnails.generate_thumbnail(path, file_hash)

    fields = {
        "width": width,
        "height": height,
        "format": fmt,
        "exif_json": json.dumps(exif),
        "dominant_color_hex": color["hex"],
        "dominant_color_name": color["name"],
        "palette_json": color_extract.palette_to_json(color["palette"]),
    }
    fields.update(promoted)
    return fields


def scan_stage_a(
    conn: sqlite3.Connection,
    folder: Path,
    summary: ScanSummary,
    cancel_event: threading.Event | None = None,
    skip_raw: bool = False,
) -> bool:
    """Walk the folder, dedupe by hash, and populate everything that needs no network.

    Returns False if cancel_event was set before the walk finished, True otherwise.
    """
    logger.info("scan stage A starting: folder=%s", folder)
    t0 = time.monotonic()
    for path in iter_image_files(folder, skip_raw=skip_raw):
        if cancel_event is not None and cancel_event.is_set():
            return False
        summary.scanned += 1
        path_str = str(path.resolve())

        size, mtime = stat_fingerprint(path)
        existing = db.get_image_by_path(conn, path_str)

        if existing and existing["file_size"] == size and existing["mtime"] == mtime:
            summary.unchanged += 1
            continue

        try:
            file_hash = sha256_file(path)
        except OSError as exc:
            logger.warning("skipped %s: could not hash (%s)", path_str, exc)
            summary.skipped.append(path_str)
            continue

        if existing and existing["file_hash"] == file_hash:
            db.update_image(
                conn, existing["id"], {"mtime": mtime, "updated_at": _now()}
            )
            summary.unchanged += 1
            continue

        by_hash = db.get_image_by_hash(conn, file_hash)
        if by_hash is not None and by_hash["path"] != path_str:
            db.update_image_path(conn, by_hash["id"], path_str, _now())
            summary.moved += 1
            continue

        static_fields = _extract_static_fields(path, file_hash)
        if static_fields is None:
            logger.warning("skipped %s: unreadable/unsupported image data", path_str)
            summary.skipped.append(path_str)
            continue

        now = _now()
        if existing:
            fields = {
                **static_fields,
                "file_hash": file_hash,
                "file_size": size,
                "mtime": mtime,
                "updated_at": now,
                "tags_status": "pending",
                "vision_raw_response": None,
                "error_message": None,
            }
            db.update_image(conn, existing["id"], fields)
            summary.updated += 1
        else:
            fields = {
                **static_fields,
                "path": path_str,
                "file_hash": file_hash,
                "file_size": size,
                "mtime": mtime,
                "added_at": now,
                "updated_at": now,
                "tags_status": "pending",
            }
            db.insert_image(conn, fields)
            summary.added += 1

    logger.info(
        "scan stage A finished in %.1fs: folder=%s scanned=%d added=%d updated=%d "
        "moved=%d unchanged=%d skipped=%d",
        time.monotonic() - t0,
        folder,
        summary.scanned,
        summary.added,
        summary.updated,
        summary.moved,
        summary.unchanged,
        len(summary.skipped),
    )
    return True


def scan_stage_b(
    conn: sqlite3.Connection,
    summary: ScanSummary,
    model: str = config.DEFAULT_VISION_MODEL,
    retry_errors: bool = False,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Tag every pending (and optionally errored) image via the Ollama vision model.

    Returns False if cancel_event was set before tagging finished, True otherwise.
    """
    statuses = ["pending"] + (["error"] if retry_errors else [])
    rows = db.images_by_status(conn, statuses)
    logger.info("scan stage B starting: model=%s images_to_tag=%d", model, len(rows))
    t0 = time.monotonic()

    for row in rows:
        if cancel_event is not None and cancel_event.is_set():
            return False
        path = Path(row["path"])
        if not path.exists():
            continue

        tag_start = time.monotonic()
        try:
            tags, raw = vision.generate_tags(path, model=model)
        except (OSError, vision.VisionError) as exc:
            elapsed = time.monotonic() - tag_start
            db.record_tagging_event(conn, model, elapsed, False, _now())
            logger.warning("tagging failed for %s after %.1fs (model=%s): %s", path, elapsed, model, exc)
            db.update_image(
                conn,
                row["id"],
                {
                    "tags_status": "error",
                    "vision_model": model,
                    "error_message": str(exc),
                    "updated_at": _now(),
                },
            )
            summary.tag_errors += 1
            continue

        elapsed = time.monotonic() - tag_start
        db.record_tagging_event(conn, model, elapsed, True, _now())
        logger.info("tagged %s in %.1fs (model=%s): %s", path.name, elapsed, model, ", ".join(tags))

        db.set_tags(conn, row["id"], tags)
        db.update_image(
            conn,
            row["id"],
            {
                "tags_status": "done",
                "vision_model": model,
                "vision_raw_response": raw,
                "error_message": None,
                "updated_at": _now(),
            },
        )
        summary.tagged += 1
        summary.tag_seconds += elapsed

    logger.info(
        "scan stage B finished in %.1fs: model=%s tagged=%d errors=%d",
        time.monotonic() - t0,
        model,
        summary.tagged,
        summary.tag_errors,
    )
    return True


def prune(conn: sqlite3.Connection) -> list[str]:
    """Remove catalog entries whose source file no longer exists. Returns removed paths."""
    removed = []
    for row in conn.execute("SELECT id, path FROM images"):
        if not Path(row["path"]).exists():
            db.delete_image(conn, row["id"])
            removed.append(row["path"])
    return removed
