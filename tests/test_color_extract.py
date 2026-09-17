from pathlib import Path

from PIL import Image

from photocatalog.color_extract import extract_dominant_color


def _make_solid_image(path: Path, rgb: tuple[int, int, int], size=(100, 100)):
    Image.new("RGB", size, rgb).save(path, "JPEG")


def test_dominant_color_solid_red(tmp_path: Path):
    path = tmp_path / "red.jpg"
    _make_solid_image(path, (220, 30, 30))

    result = extract_dominant_color(path)

    assert result["hex"] is not None
    assert "red" in result["name"]
    assert len(result["palette"]) >= 1
    assert result["palette"][0]["fraction"] > 0.9


def test_dominant_color_solid_blue(tmp_path: Path):
    path = tmp_path / "blue.jpg"
    _make_solid_image(path, (20, 40, 220))

    result = extract_dominant_color(path)

    assert "blue" in result["name"]


def test_dominant_color_grayscale(tmp_path: Path):
    path = tmp_path / "gray.jpg"
    _make_solid_image(path, (128, 128, 128))

    result = extract_dominant_color(path)

    assert result["name"] == "gray"
