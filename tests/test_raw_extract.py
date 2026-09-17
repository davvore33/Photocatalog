from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import rawpy
from PIL import Image

from photocatalog import raw_extract


def _fake_raw(sizes_wh, thumb):
    fake = MagicMock()
    fake.sizes.width, fake.sizes.height = sizes_wh
    fake.extract_thumb.return_value = thumb
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    return fake


def test_extract_preview_jpeg_thumb(tmp_path: Path):
    import io

    jpeg_bytes = io.BytesIO()
    Image.new("RGB", (20, 20), (10, 20, 30)).save(jpeg_bytes, "JPEG")
    thumb = rawpy.Thumbnail(rawpy.ThumbFormat.JPEG, jpeg_bytes.getvalue())
    fake = _fake_raw((6000, 4000), thumb)

    with patch.object(rawpy, "imread", return_value=fake):
        img, raw_bytes, size = raw_extract.extract_preview(tmp_path / "photo.raf")

    assert size == (6000, 4000)
    assert raw_bytes is not None
    assert img.size == (20, 20)


def test_extract_preview_bitmap_thumb(tmp_path: Path):
    array = np.zeros((10, 10, 3), dtype="uint8")
    thumb = rawpy.Thumbnail(rawpy.ThumbFormat.BITMAP, array)
    fake = _fake_raw((100, 50), thumb)

    with patch.object(rawpy, "imread", return_value=fake):
        img, raw_bytes, size = raw_extract.extract_preview(tmp_path / "photo.nef")

    assert size == (100, 50)
    assert raw_bytes is None
    assert img.size == (10, 10)


def test_extract_preview_raises_on_libraw_error(tmp_path: Path):
    with patch.object(rawpy, "imread", side_effect=rawpy.LibRawFileUnsupportedError()):
        try:
            raw_extract.extract_preview(tmp_path / "corrupt.cr2")
            assert False, "expected RawPreviewError"
        except raw_extract.RawPreviewError:
            pass
