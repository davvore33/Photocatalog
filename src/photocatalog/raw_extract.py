import io
from pathlib import Path

import rawpy
from PIL import Image

# Handled via LibRaw's embedded-preview extraction, not full demosaicing.
RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".raf"}


class RawPreviewError(Exception):
    pass


def extract_preview(path: Path) -> tuple[Image.Image, bytes | None, tuple[int, int]]:
    """Return (preview image, raw JPEG bytes if available, true sensor width/height)."""
    try:
        with rawpy.imread(str(path)) as raw:
            true_size = (raw.sizes.width, raw.sizes.height)
            thumb = raw.extract_thumb()
    except rawpy.LibRawError as exc:
        raise RawPreviewError(str(exc)) from exc

    if thumb.format == rawpy.ThumbFormat.JPEG:
        img = Image.open(io.BytesIO(thumb.data))
        img.load()
        return img, thumb.data, true_size
    if thumb.format == rawpy.ThumbFormat.BITMAP:
        return Image.fromarray(thumb.data), None, true_size

    raise RawPreviewError(f"unsupported embedded thumbnail format: {thumb.format}")
