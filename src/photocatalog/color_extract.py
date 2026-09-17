import colorsys
import json
from pathlib import Path

from PIL import Image, ImageOps

_QUANTIZE_COLORS = 8
_DOWNSAMPLE_SIZE = (150, 150)

_HUE_FAMILIES = [
    (15, "red"),
    (45, "orange"),
    (70, "yellow"),
    (160, "green"),
    (200, "cyan"),
    (255, "blue"),
    (290, "purple"),
    (330, "magenta"),
    (360, "red"),
]


def _hue_family(hue_degrees: float) -> str:
    for upper, name in _HUE_FAMILIES:
        if hue_degrees <= upper:
            return name
    return "red"


def _color_name(r: int, g: int, b: int) -> str:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hue_degrees = h * 360

    if v < 0.15:
        return "black"
    if s < 0.12:
        if v > 0.85:
            return "white"
        return "gray"

    family = _hue_family(hue_degrees)
    warm = family in ("red", "orange", "yellow", "magenta")
    temperature = "warm" if warm else "cool"

    if s < 0.35:
        return f"muted {family}"
    if v < 0.35:
        return f"dark {family}"
    if s > 0.75 and v > 0.75:
        return f"vivid {family}"
    return f"{temperature} {family}"


def extract_dominant_color(path: Path) -> dict:
    """Return {hex, name, palette: [{hex, fraction}, ...]} for the image's colors."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(_DOWNSAMPLE_SIZE, Image.BILINEAR)

        quantized = img.quantize(colors=_QUANTIZE_COLORS, method=Image.MEDIANCUT)
        counts = quantized.getcolors(maxcolors=_QUANTIZE_COLORS)
        if not counts:
            return {"hex": None, "name": None, "palette": []}

        palette = quantized.getpalette()
        counts.sort(key=lambda item: item[0], reverse=True)
        total = sum(count for count, _ in counts)

        entries = []
        for count, index in counts:
            r, g, b = palette[index * 3 : index * 3 + 3]
            entries.append(
                {
                    "hex": f"#{r:02x}{g:02x}{b:02x}",
                    "fraction": round(count / total, 4),
                    "rgb": (r, g, b),
                }
            )

        dominant = entries[0]
        r, g, b = dominant["rgb"]
        return {
            "hex": dominant["hex"],
            "name": _color_name(r, g, b),
            "palette": [
                {"hex": e["hex"], "fraction": e["fraction"]} for e in entries[:5]
            ],
        }


def palette_to_json(palette: list[dict]) -> str:
    return json.dumps(palette)
