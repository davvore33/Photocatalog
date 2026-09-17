import io
from fractions import Fraction
from pathlib import Path

import piexif
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from photocatalog.exif_extract import _jsonify, extract_exif, promote_fields


def _make_jpeg_with_exif(path: Path):
    img = Image.new("RGB", (50, 50), (200, 100, 50))

    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: b"Canon",
            piexif.ImageIFD.Model: b"EOS R5",
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2026:05:01 12:00:00",
            piexif.ExifIFD.LensModel: b"RF 24-70mm",
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: ((45, 1), (30, 1), (0, 1)),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: ((9, 1), (10, 1), (0, 1)),
        },
        "1st": {},
        "thumbnail": None,
    }
    exif_bytes = piexif.dump(exif_dict)
    img.save(path, "jpeg", exif=exif_bytes)


def test_extract_exif_jpeg(tmp_path: Path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(path)

    exif = extract_exif(path)

    assert exif["0th"]["Make"] == "Canon"
    assert exif["0th"]["Model"] == "EOS R5"
    assert exif["Exif"]["DateTimeOriginal"] == "2026:05:01 12:00:00"
    assert exif["Exif"]["LensModel"] == "RF 24-70mm"


def test_promote_fields(tmp_path: Path):
    path = tmp_path / "photo.jpg"
    _make_jpeg_with_exif(path)

    exif = extract_exif(path)
    promoted = promote_fields(exif)

    assert promoted["exif_camera_make"] == "Canon"
    assert promoted["exif_camera_model"] == "EOS R5"
    assert promoted["exif_datetime_original"] == "2026:05:01 12:00:00"
    assert promoted["exif_lens_model"] == "RF 24-70mm"
    assert promoted["exif_gps_lat"] == 45.5
    assert promoted["exif_gps_lon"] == 9.1667 or abs(promoted["exif_gps_lon"] - 9.1667) < 0.001


def test_extract_exif_no_exif(tmp_path: Path):
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (50, 50), (10, 10, 10)).save(path, "jpeg")

    exif = extract_exif(path)
    promoted = promote_fields(exif)

    assert promoted["exif_camera_make"] is None


def test_jsonify_ifdrational_is_json_safe():
    import json

    value = _jsonify(IFDRational(16, 10))
    assert value == 1.6
    json.dumps(value)  # must not raise


def test_jsonify_plain_fraction_is_json_safe():
    import json

    value = _jsonify(Fraction(3, 2))
    assert value == 1.5
    json.dumps(value)  # must not raise


def test_extract_exif_raw_falls_back_to_preview_bytes(tmp_path: Path):
    # A .raf path piexif can't parse (not a real TIFF/JPEG on disk), but the
    # caller supplies the embedded preview JPEG's bytes as a fallback - this
    # mirrors how scanner.py handles RAW files.
    fake_raw_path = tmp_path / "photo.raf"
    fake_raw_path.write_bytes(b"FUJIFILMCCD-RAW not-a-real-raw-file")

    preview = io.BytesIO()
    exif_dict = {
        "0th": {piexif.ImageIFD.Make: b"FUJIFILM"},
        "Exif": {},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    Image.new("RGB", (30, 30), (5, 5, 5)).save(
        preview, "jpeg", exif=piexif.dump(exif_dict)
    )

    exif = extract_exif(fake_raw_path, fallback_bytes=preview.getvalue())
    promoted = promote_fields(exif)

    assert promoted["exif_camera_make"] == "FUJIFILM"
