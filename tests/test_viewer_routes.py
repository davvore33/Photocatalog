import csv
import io
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


def _read_csv_rows(resp) -> list[dict]:
    text = resp.get_data(as_text=True).lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text)))


def test_export_csv_headers_and_content_type(client):
    resp = client.get("/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "photocatalog-export.csv" in resp.headers["Content-Disposition"]


def test_export_csv_contains_all_images_when_unfiltered(client):
    resp = client.get("/export.csv")
    rows = _read_csv_rows(resp)
    assert len(rows) == len(client.image_ids)
    paths = {row["path"] for row in rows}
    assert paths == {"/photos/a.jpg", "/photos/b.jpg", "/photos/c.jpg", "/photos/d.jpg"}


def test_export_csv_respects_tag_filter(client):
    resp = client.get("/export.csv?tags=beach&tags=sunset&tag_mode=and")
    rows = _read_csv_rows(resp)
    assert len(rows) == 1
    assert rows[0]["path"] == "/photos/a.jpg"
    assert "beach" in rows[0]["tags"]
    assert "sunset" in rows[0]["tags"]


def test_export_csv_is_not_paginated(client):
    resp = client.get("/export.csv?tags=beach&tags=sunset&tag_mode=or")
    rows = _read_csv_rows(resp)
    # beach_sunset, beach_only, sunset_only all match OR - more than one page_size would allow
    assert len(rows) == 3


# --- regression tests -------------------------------------------------------


def _make_client(tmp_path: Path, images: list[dict]):
    db_path = tmp_path / "catalog.db"
    conn = db.connect(db_path)
    ids = []
    for i, spec in enumerate(images):
        tags = spec.pop("tags", [])
        image_id = db.insert_image(
            conn,
            {
                "path": f"/photos/{i}.jpg",
                "file_hash": f"hash{i}",
                "file_size": 100,
                "mtime": 1.0,
                "added_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "tags_status": "done",
                **spec,
            },
        )
        db.set_tags(conn, image_id, tags)
        ids.append(image_id)
    conn.close()
    app = create_app(db_path)
    app.config["TESTING"] = True
    return app.test_client(), ids


def _shown(resp, ids) -> list[int]:
    html = resp.get_data(as_text=True)
    return [i for i in ids if f"/image/{i}" in html]


@pytest.fixture
def dated(tmp_path: Path):
    # EXIF stores timestamps as 'YYYY:MM:DD HH:MM:SS'
    client, ids = _make_client(
        tmp_path,
        [
            {"exif_datetime_original": "2024:01:15 10:00:00"},
            {"exif_datetime_original": "2024:03:01 12:00:00"},
            {"exif_datetime_original": "2024:12:20 09:00:00"},
            {"exif_datetime_original": None},
        ],
    )
    jan, mar, dec, undated = ids
    return client, jan, mar, dec, undated


def test_date_from_filter(dated):
    client, jan, mar, dec, _ = dated
    assert _shown(client.get("/?from=2024-12-01"), [jan, mar, dec]) == [dec]
    assert _shown(client.get("/?from=2024-03-01"), [jan, mar, dec]) == [mar, dec]


def test_date_to_filter_is_inclusive_of_the_whole_day(dated):
    client, jan, mar, dec, _ = dated
    assert _shown(client.get("/?to=2024-06-30"), [jan, mar, dec]) == [jan, mar]
    assert _shown(client.get("/?to=2024-12-20"), [jan, mar, dec]) == [jan, mar, dec]


def test_date_range_and_month_prefix(dated):
    client, jan, mar, dec, _ = dated
    assert _shown(client.get("/?from=2024-03-01&to=2024-03-01"), [jan, mar, dec]) == [mar]
    assert _shown(client.get("/?from=2024-03&to=2024-03"), [jan, mar, dec]) == [mar]


def test_date_filter_excludes_undated_images(dated):
    client, *_ids, undated = dated
    assert undated not in _shown(client.get("/?from=2000-01-01"), [undated])


def test_duplicate_tag_params_do_not_empty_the_and_filter(client):
    html = client.get("/?tags=beach&tags=beach&tag_mode=and").get_data(as_text=True)
    assert f'/image/{client.image_ids["beach_only"]}' in html
    assert f'/image/{client.image_ids["beach_sunset"]}' in html


def test_search_treats_like_wildcards_literally(client):
    ids = list(client.image_ids.values())
    assert _shown(client.get("/?q=%25"), ids) == []  # '%' used to match everything
    assert _shown(client.get("/?q=_"), ids) == []
    assert _shown(client.get("/?q=beac"), ids) == [
        client.image_ids["beach_sunset"],
        client.image_ids["beach_only"],
    ]


def test_lang_switch_refuses_external_redirects(client):
    for target in ("https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)"):
        resp = client.get("/lang/en", query_string={"next": target})
        assert resp.status_code == 302
        assert "evil" not in resp.headers["Location"]
        assert "javascript" not in resp.headers["Location"]


def test_lang_switch_keeps_local_redirects(client):
    resp = client.get("/lang/en?next=/scan")
    assert resp.headers["Location"].endswith("/scan")
    assert "lang=en" in resp.headers["Set-Cookie"]


def test_cross_origin_post_is_rejected(client):
    resp = client.post("/scan/stop", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403


def test_same_origin_and_originless_posts_are_allowed(client):
    assert client.post("/scan/stop", headers={"Origin": "http://localhost"}).status_code == 302
    assert client.post("/scan/stop").status_code == 302


def test_scan_start_while_busy_shows_a_message(client, tmp_path: Path):
    from unittest.mock import patch

    with patch("photocatalog.viewer.jobs.start_scan", return_value=False):
        resp = client.post("/scan/start", data={"folder": str(tmp_path)})
    assert resp.status_code == 302
    assert "error=busy" in resp.headers["Location"]

    html = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "già uno scan in corso" in html


def test_export_csv_defuses_formula_injection(tmp_path: Path):
    client, _ = _make_client(tmp_path, [{"tags": ["=HYPERLINK(\"http://x\")", "ok"]}])
    rows = _read_csv_rows(client.get("/export.csv"))
    assert rows[0]["tags"].startswith("'=HYPERLINK")
    assert rows[0]["path"] == "/photos/0.jpg"


# --- optimization regression tests -----------------------------------------


def test_export_csv_orders_and_joins_tags_and_handles_untagged(tmp_path: Path):
    client, _ = _make_client(
        tmp_path,
        [
            {"tags": ["zebra", "apple", "mango"], "exif_datetime_original": "2024:02:01 10:00:00"},
            {"tags": [], "exif_datetime_original": "2024:01:01 10:00:00"},
        ],
    )
    rows = _read_csv_rows(client.get("/export.csv"))
    assert [r["tags"] for r in rows] == ["apple; mango; zebra", ""]  # newest first, tags sorted


def test_export_csv_streams_every_row_across_chunk_boundaries(tmp_path: Path):
    big_exif = '{"MakerNote": "' + "x" * 5000 + '"}'  # ~5KB per row => several 64KB chunks
    client, ids = _make_client(
        tmp_path, [{"exif_json": big_exif, "tags": ["t"]} for _ in range(60)]
    )
    resp = client.get("/export.csv")
    assert resp.get_data().startswith(b"\xef\xbb\xbf")  # BOM exactly once, at the start
    rows = _read_csv_rows(resp)
    assert len(rows) == 60
    assert all(row["exif_json"] == big_exif and row["tags"] == "t" for row in rows)


def test_grid_ordering_uses_the_composite_index(tmp_path: Path):
    db_path = tmp_path / "catalog.db"
    conn = db.connect(db_path)
    plan = " ".join(
        str(tuple(row))
        for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM images WHERE 1=1 "
            "ORDER BY exif_datetime_original DESC, added_at DESC LIMIT 60 OFFSET 0"
        )
    )
    assert "idx_images_sort" in plan
    assert "TEMP B-TREE" not in plan
