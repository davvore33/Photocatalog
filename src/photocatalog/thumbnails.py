from pathlib import Path

from PIL import Image, ImageOps

from . import config


def thumbnail_path(file_hash: str) -> Path:
    return config.THUMBNAILS_DIR / f"{file_hash}.jpg"


def generate_thumbnail_from_image(img: Image.Image, file_hash: str) -> Path:
    dest = thumbnail_path(file_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)

    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail(config.THUMBNAIL_SIZE, Image.LANCZOS)
    img.save(dest, "JPEG", quality=85)

    return dest


def generate_thumbnail(source_path: Path, file_hash: str) -> Path:
    with Image.open(source_path) as img:
        return generate_thumbnail_from_image(img, file_hash)
