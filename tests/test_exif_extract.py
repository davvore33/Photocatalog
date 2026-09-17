from pathlib import Path

import piexif
from PIL import Image

from photocatalog.exif_extract import extract_exif, promote_fields


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
