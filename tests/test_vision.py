from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from PIL import Image

from photocatalog import vision


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "p.jpg"
    Image.new("RGB", (20, 20), (10, 20, 30)).save(path, "JPEG")
    return path


@pytest.fixture(autouse=True)
def _no_retry_sleep():
    with patch("photocatalog.vision.time.sleep"):
        yield


def _response(status=200, content='{"tags": ["a"]}'):
    resp = Mock(status_code=status)
    resp.json.return_value = {"message": {"content": content}}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    return resp


def test_parse_tags_normalizes_and_dedupes():
    assert vision._parse_tags('{"tags": [" Beach ", "beach", "Sunset", ""]}') == ["beach", "sunset"]


@pytest.mark.parametrize("content", ['["a", "b"]', '"just text"', "42", 'noise ["a"] noise'])
def test_parse_tags_rejects_non_object_json_with_vision_error(content):
    with pytest.raises(vision.VisionError):
        vision._parse_tags(content)


def test_generate_tags_success(photo):
    with patch("photocatalog.vision.requests.post", return_value=_response()):
        tags, raw = vision.generate_tags(photo)
    assert tags == ["a"]
    assert raw == '{"tags": ["a"]}'


def test_generate_tags_unreachable_ollama_raises_unavailable_after_retries(photo):
    with patch(
        "photocatalog.vision.requests.post", side_effect=requests.ConnectionError("refused")
    ) as post:
        with pytest.raises(vision.VisionUnavailable):
            vision.generate_tags(photo)
    assert post.call_count == vision.config.VISION_MAX_RETRIES + 1


def test_generate_tags_missing_model_fails_fast_as_unavailable(photo):
    with patch("photocatalog.vision.requests.post", return_value=_response(404)) as post:
        with pytest.raises(vision.VisionUnavailable, match="ollama pull"):
            vision.generate_tags(photo, model="nope:1b")
    assert post.call_count == 1


def test_generate_tags_server_error_is_a_per_image_error_not_unavailable(photo):
    with patch("photocatalog.vision.requests.post", return_value=_response(500)):
        with pytest.raises(vision.VisionError) as exc_info:
            vision.generate_tags(photo)
    assert not isinstance(exc_info.value, vision.VisionUnavailable)


def test_generate_tags_non_object_reply_is_a_vision_error(photo):
    with patch("photocatalog.vision.requests.post", return_value=_response(content='["a", "b"]')):
        with pytest.raises(vision.VisionError):
            vision.generate_tags(photo)
