import base64
import io
import json
import re
import time
from pathlib import Path

import requests
from PIL import Image, ImageOps

from . import config, raw_extract

PROMPT = (
    "Look at this photo and return ONLY JSON in the form "
    '{"tags": [...]}, with 5-15 short lowercase tags describing the '
    "subjects, objects, setting, and activity in the image. "
    "Do NOT include colors, mood, or emotional descriptions - "
    "those are handled separately."
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class VisionError(Exception):
    pass


def _load_source_image(path: Path) -> Image.Image:
    if path.suffix.lower() in raw_extract.RAW_EXTENSIONS:
        img, _, _ = raw_extract.extract_preview(path)
        return img
    return Image.open(path)


def _prepare_image_b64(path: Path) -> str:
    with _load_source_image(path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(
            (config.VISION_IMAGE_MAX_DIMENSION, config.VISION_IMAGE_MAX_DIMENSION),
            Image.LANCZOS,
        )
        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=config.VISION_IMAGE_QUALITY)
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def _parse_tags(content: str) -> list[str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(content)
        if not match:
            raise VisionError(f"could not parse JSON from response: {content!r}")
        data = json.loads(match.group(0))

    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise VisionError(f"'tags' field is not a list: {tags!r}")

    normalized = []
    seen = set()
    for tag in tags:
        name = str(tag).strip().lower()
        if name and name not in seen:
            seen.add(name)
            normalized.append(name)
    return normalized


def generate_tags(
    path: Path,
    model: str = config.DEFAULT_VISION_MODEL,
    ollama_url: str = config.OLLAMA_URL,
) -> tuple[list[str], str]:
    """Call Ollama's vision model on the image. Returns (tags, raw_response_text)."""
    image_b64 = _prepare_image_b64(path)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT, "images": [image_b64]}],
        "format": "json",
        "stream": False,
    }

    last_error = None
    for attempt in range(config.VISION_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                ollama_url, json=payload, timeout=config.VISION_TIMEOUT_SECONDS
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            tags = _parse_tags(content)
            return tags, content
        except (requests.RequestException, VisionError, KeyError, ValueError) as exc:
            last_error = exc
            if attempt < config.VISION_MAX_RETRIES:
                time.sleep(2**attempt)

    raise VisionError(str(last_error)) from last_error
