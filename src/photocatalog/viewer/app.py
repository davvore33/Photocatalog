import json
import sqlite3
from pathlib import Path

from flask import Flask, abort, g, render_template, request, send_file

from .. import config, db, thumbnails


def create_app(db_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    def get_conn() -> sqlite3.Connection:
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.route("/")
    def index():
        conn = get_conn()

        tag = request.args.get("tag", "").strip()
        camera = request.args.get("camera", "").strip()
        color = request.args.get("color", "").strip()
        search = request.args.get("q", "").strip()
        date_from = request.args.get("from", "").strip()
        date_to = request.args.get("to", "").strip()
        page = max(1, request.args.get("page", 1, type=int))
        page_size = config.DEFAULT_PAGE_SIZE

        clauses = ["1=1"]
        params: list = []

        query_base = "SELECT DISTINCT images.* FROM images"
        joins = ""

        if tag:
            joins += (
                " JOIN image_tags it ON it.image_id = images.id"
                " JOIN tags t ON t.id = it.tag_id"
            )
            clauses.append("t.name = ?")
            params.append(tag)

        if camera:
            clauses.append("images.exif_camera_model = ?")
            params.append(camera)

        if color:
            clauses.append("images.dominant_color_name = ?")
            params.append(color)

        if search:
            clauses.append(
                "images.id IN (SELECT it3.image_id FROM image_tags it3 "
                "JOIN tags t3 ON t3.id = it3.tag_id WHERE t3.name LIKE ?)"
            )
            params.append(f"%{search}%")

        if date_from:
            clauses.append("images.exif_datetime_original >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("images.exif_datetime_original <= ?")
            params.append(date_to)

        where = " AND ".join(clauses)
        count_sql = f"SELECT COUNT(DISTINCT images.id) AS n FROM images {joins} WHERE {where}"
        total = conn.execute(count_sql, params).fetchone()["n"]

        offset = (page - 1) * page_size
        list_sql = (
            f"{query_base} {joins} WHERE {where} "
            "ORDER BY images.exif_datetime_original DESC, images.added_at DESC "
            "LIMIT ? OFFSET ?"
        )
        rows = conn.execute(list_sql, [*params, page_size, offset]).fetchall()

        cameras = [
            r["exif_camera_model"]
            for r in conn.execute(
                "SELECT DISTINCT exif_camera_model FROM images "
                "WHERE exif_camera_model IS NOT NULL ORDER BY 1"
            )
        ]
        colors = [
            r["dominant_color_name"]
            for r in conn.execute(
                "SELECT DISTINCT dominant_color_name FROM images "
                "WHERE dominant_color_name IS NOT NULL ORDER BY 1"
            )
        ]

        total_pages = max(1, (total + page_size - 1) // page_size)

        return render_template(
            "index.html",
            images=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            filters={
                "tag": tag,
                "camera": camera,
                "color": color,
                "q": search,
                "from": date_from,
                "to": date_to,
            },
            cameras=cameras,
            colors=colors,
        )

    @app.route("/image/<int:image_id>")
    def image_detail(image_id: int):
        conn = get_conn()
        row = db.get_image(conn, image_id)
        if row is None:
            abort(404)
        tags = db.get_tags_for_image(conn, image_id)
        exif = json.loads(row["exif_json"]) if row["exif_json"] else {}
        palette = json.loads(row["palette_json"]) if row["palette_json"] else []
        return render_template(
            "detail.html", image=row, tags=tags, exif=exif, palette=palette
        )

    @app.route("/thumb/<int:image_id>.jpg")
    def thumb(image_id: int):
        conn = get_conn()
        row = db.get_image(conn, image_id)
        if row is None:
            abort(404)
        path = thumbnails.thumbnail_path(row["file_hash"])
        if not path.exists():
            abort(404)
        return send_file(path, mimetype="image/jpeg")

    @app.route("/original/<int:image_id>")
    def original(image_id: int):
        conn = get_conn()
        row = db.get_image(conn, image_id)
        if row is None:
            abort(404)
        path = Path(row["path"])
        if not path.exists():
            abort(404)
        return send_file(path)

    return app
