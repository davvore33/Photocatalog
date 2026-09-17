import base64
import io
from pathlib import Path

import piexif
from PIL import ExifTags, Image

from . import raw_extract

_PIEXIF_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}

# Structural IFD-offset pointers, not actual metadata - always present, never useful to show.
_POINTER_TAGS = {"ExifTag", "GPSTag", "InteroperabilityTag"}


def _rational_to_value(value):
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], int):
        num, den = value
        if den == 0:
            return None
        return num / den
    return value


def _jsonify(value):
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        # Could be a rational (num, den) pair or a plain sequence.
        if len(value) == 2 and all(isinstance(v, int) for v in value):
            rational = _rational_to_value(value)
            if rational is not None:
                return rational
        return [_jsonify(v) for v in value]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, float) and (value != value):  # NaN
        return None
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        # Covers Pillow's IFDRational and other Fraction-like rationals.
        try:
            return float(value)
        except (TypeError, ZeroDivisionError):
            return None
    return str(value)


def _dms_to_decimal(dms, ref: str | None) -> float | None:
    try:
        degrees, minutes, seconds = (_rational_to_value(v) for v in dms)
        decimal = degrees + minutes / 60 + seconds / 3600
    except (TypeError, ZeroDivisionError, ValueError):
        return None
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _extract_via_piexif(path: Path) -> dict:
    raw = piexif.load(str(path))
    result: dict = {}
    for ifd_name in ("0th", "Exif", "GPS", "1st"):
        ifd = raw.get(ifd_name) or {}
        section = {}
        for tag_id, value in ifd.items():
            tag_info = piexif.TAGS.get(ifd_name, {}).get(tag_id)
            name = tag_info["name"] if tag_info else str(tag_id)
            if name in _POINTER_TAGS:
                continue
            section[name] = _jsonify(value)
        if section:
            result[ifd_name] = section
    return result


def _extract_via_pillow(source: Path | io.BytesIO) -> dict:
    result: dict = {}
    with Image.open(source) as img:
        exif = img.getexif()
        if not exif:
            return result

        base = {}
        for tag_id, value in exif.items():
            name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if name in _POINTER_TAGS:
                continue
            base[name] = _jsonify(value)
        if base:
            result["0th"] = base

        try:
            exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
        except (KeyError, AttributeError):
            exif_ifd = {}
        if exif_ifd:
            result["Exif"] = {
                ExifTags.TAGS.get(tag_id, str(tag_id)): _jsonify(value)
                for tag_id, value in exif_ifd.items()
            }

        try:
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
        except (KeyError, AttributeError):
            gps_ifd = {}
        if gps_ifd:
            result["GPS"] = {
                ExifTags.GPSTAGS.get(tag_id, str(tag_id)): _jsonify(value)
                for tag_id, value in gps_ifd.items()
            }
    return result


def extract_exif(path: Path, fallback_bytes: bytes | None = None) -> dict:
    """Return the full EXIF data as a JSON-safe nested dict, grouped by IFD.

    For RAW files, ``fallback_bytes`` should be the embedded preview JPEG:
    RAW containers that aren't TIFF-based (e.g. .cr3, .raf) can't be read by
    piexif directly, but the camera-written EXIF usually survives in the
    preview JPEG's own APP1 segment.
    """
    ext = path.suffix.lower()
    is_raw = ext in raw_extract.RAW_EXTENSIONS

    if ext in _PIEXIF_EXTENSIONS or is_raw:
        try:
            data = _extract_via_piexif(path)
            if data:
                return data
        except Exception:
            pass

    try:
        if fallback_bytes is not None:
            return _extract_via_pillow(io.BytesIO(fallback_bytes))
        if not is_raw:
            return _extract_via_pillow(path)
    except Exception:
        pass

    return {}


def promote_fields(exif: dict) -> dict:
    """Pull out the handful of commonly-queried fields as flat, typed values."""
    zeroth = exif.get("0th", {})
    exif_ifd = exif.get("Exif", {})
    gps = exif.get("GPS", {})

    lat = lon = None
    if gps.get("GPSLatitude") and gps.get("GPSLatitudeRef"):
        lat = _dms_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef"))
    if gps.get("GPSLongitude") and gps.get("GPSLongitudeRef"):
        lon = _dms_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef"))

    return {
        "exif_datetime_original": exif_ifd.get("DateTimeOriginal")
        or zeroth.get("DateTime"),
        "exif_camera_make": zeroth.get("Make"),
        "exif_camera_model": zeroth.get("Model"),
        "exif_lens_model": exif_ifd.get("LensModel"),
        "exif_gps_lat": lat,
        "exif_gps_lon": lon,
    }
