from pathlib import Path

import pytest

from photocatalog import db
from photocatalog.viewer.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    conn = db.connect(db_path)

    def make_image(path, tags):
        image_id = db.insert_image(
            conn,
            {
                "path": path,
                "file_hash": path,
                "file_size": 100,
                "mtime": 1.0,
                "added_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "tags_status": "done",
            },
        )
        db.set_tags(conn, image_id, tags)
        return image_id

    ids = {
        "beach_sunset": make_image("/photos/a.jpg", ["beach", "sunset"]),
        "beach_only": make_image("/photos/b.jpg", ["beach"]),
        "sunset_only": make_image("/photos/c.jpg", ["sunset"]),
        "neither": make_image("/photos/d.jpg", ["mountain"]),
    }
    conn.close()

    app = create_app(db_path)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.image_ids = ids
        yield c


def test_tag_filter_and_mode_requires_all_tags(client):
    resp = client.get("/?tags=beach&tags=sunset&tag_mode=and")
    html = resp.get_data(as_text=True)
    assert f'/image/{client.image_ids["beach_sunset"]}' in html
    assert f'/image/{client.image_ids["beach_only"]}' not in html
    assert f'/image/{client.image_ids["sunset_only"]}' not in html


def test_tag_filter_or_mode_matches_any_tag(client):
    resp = client.get("/?tags=beach&tags=sunset&tag_mode=or")
    html = resp.get_data(as_text=True)
    assert f'/image/{client.image_ids["beach_sunset"]}' in html
    assert f'/image/{client.image_ids["beach_only"]}' in html
    assert f'/image/{client.image_ids["sunset_only"]}' in html
    assert f'/image/{client.image_ids["neither"]}' not in html


def test_no_tag_filter_returns_everything(client):
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    for image_id in client.image_ids.values():
        assert f'/image/{image_id}' in html


def test_index_card_links_include_back_query_string(client):
    resp = client.get("/?tags=beach&tag_mode=or")
    html = resp.get_data(as_text=True)
    assert "back=tags%3Dbeach" in html


def test_detail_back_link_reuses_back_param(client):
    image_id = client.image_ids["beach_only"]
    resp = client.get(f"/image/{image_id}?back=tags%3Dbeach%26tag_mode%3Dor")
    html = resp.get_data(as_text=True)
    assert 'href="/?tags=beach&amp;tag_mode=or"' in html


def test_detail_back_link_plain_when_no_filters(client):
    image_id = client.image_ids["beach_only"]
    resp = client.get(f"/image/{image_id}")
    html = resp.get_data(as_text=True)
    assert 'href="/"' in html
