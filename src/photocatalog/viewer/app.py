import csv
import io
import json
import sqlite3
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, url_for

from .. import config, db, thumbnails
from . import i18n, jobs

EXPORT_COLUMNS = [
    "filename",
    "path",
    "width",
    "height",
    "format",
    "file_size_bytes",
    "camera_make",
    "camera_model",
    "lens_model",
    "datetime_original",
    "gps_lat",
    "gps_lon",
    "dominant_color_name",
    "dominant_color_hex",
    "tags",
    "tags_status",
    "added_at",
    "exif_json",
]


def _parse_filters(args) -> tuple[str, list, dict]:
    """Build a SQL WHERE clause + params from query args, shared by the grid and CSV export."""
    tags_selected = [t for t in args.getlist("tags") if t]
    tag_mode = args.get("tag_mode", "and")
    if tag_mode not in ("and", "or"):
        tag_mode = "and"
    camera = args.get("camera", "").strip()
    color = args.get("color", "").strip()
    search = args.get("q", "").strip()
    date_from = args.get("from", "").strip()
    date_to = args.get("to", "").strip()

    clauses = ["1=1"]
    params: list = []

    if tags_selected:
        placeholders = ", ".join("?" for _ in tags_selected)
        if tag_mode == "or":
            clauses.append(
                "images.id IN (SELECT it.image_id FROM image_tags it "
                f"JOIN tags t ON t.id = it.tag_id WHERE t.name IN ({placeholders}))"
            )
            params.extend(tags_selected)
        else:
            clauses.append(
                "images.id IN (SELECT it.image_id FROM image_tags it "
                f"JOIN tags t ON t.id = it.tag_id WHERE t.name IN ({placeholders}) "
                "GROUP BY it.image_id HAVING COUNT(DISTINCT t.name) = ?)"
            )
            params.extend(tags_selected)
            params.append(len(tags_selected))

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

    filters = {
        "tags": tags_selected,
        "tag_mode": tag_mode,
        "camera": camera,
        "color": color,
        "q": search,
        "from": date_from,
        "to": date_to,
    }
    return " AND ".join(clauses), params, filters


def _list_subdirs(path: Path) -> tuple[list[Path], str | None]:
    """Returns (entries, error). error is None, 'permission', or a raw OSError message."""
    try:
        entries = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except PermissionError:
        return [], "permission"
    except OSError as exc:
        return [], str(exc)
    return sorted(entries, key=lambda p: p.name.lower()), None


def _shortcuts() -> list[tuple[str, Path]]:
    """Returns (i18n key suffix, path) pairs for folders that exist."""
    home = Path.home()
    candidates = [
        ("home", home),
        ("desktop", home / "Desktop"),
        ("pictures", home / "Pictures"),
        ("documents", home / "Documents"),
        ("volumes", Path("/Volumes")),
    ]
    return [(key, p) for key, p in candidates if p.is_dir()]


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

    def current_lang() -> str:
        lang = request.cookies.get("lang", i18n.DEFAULT_LANG)
        return lang if lang in i18n.TRANSLATIONS else i18n.DEFAULT_LANG

    @app.context_processor
    def inject_i18n():
        lang = current_lang()
        return {"t": lambda key, **kw: i18n.translate(lang, key, **kw), "current_lang": lang}

    @app.route("/lang/<code>")
    def set_lang(code: str):
        resp = redirect(request.args.get("next") or url_for("index"))
        if code in i18n.TRANSLATIONS:
            resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365)
        return resp

    @app.route("/")
    def index():
        conn = get_conn()

        where, params, filters = _parse_filters(request.args)
        page = max(1, request.args.get("page", 1, type=int))
        page_size = config.DEFAULT_PAGE_SIZE

        count_sql = f"SELECT COUNT(*) AS n FROM images WHERE {where}"
        total = conn.execute(count_sql, params).fetchone()["n"]

        offset = (page - 1) * page_size
        list_sql = (
            f"SELECT * FROM images WHERE {where} "
            "ORDER BY exif_datetime_original DESC, added_at DESC "
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
        all_tags = [r["name"] for r in conn.execute("SELECT name FROM tags ORDER BY name")]

        total_pages = max(1, (total + page_size - 1) // page_size)

        return render_template(
            "index.html",
            images=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            filters=filters,
            cameras=cameras,
            colors=colors,
            all_tags=all_tags,
            back_qs=request.query_string.decode(),
        )

    @app.route("/export.csv")
    def export_csv():
        conn = get_conn()
        where, params, _filters = _parse_filters(request.args)
        list_sql = (
            f"SELECT * FROM images WHERE {where} "
            "ORDER BY exif_datetime_original DESC, added_at DESC"
        )
        rows = conn.execute(list_sql, params).fetchall()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_COLUMNS)
        for row in rows:
            tags = db.get_tags_for_image(conn, row["id"])
            writer.writerow(
                [
                    Path(row["path"]).name,
                    row["path"],
                    row["width"],
                    row["height"],
                    row["format"],
                    row["file_size"],
                    row["exif_camera_make"],
                    row["exif_camera_model"],
                    row["exif_lens_model"],
                    row["exif_datetime_original"],
                    row["exif_gps_lat"],
                    row["exif_gps_lon"],
                    row["dominant_color_name"],
                    row["dominant_color_hex"],
                    "; ".join(tags),
                    row["tags_status"],
                    row["added_at"],
                    row["exif_json"] or "",
                ]
            )

        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=photocatalog-export.csv"},
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
            "detail.html",
            image=row,
            tags=tags,
            exif=exif,
            palette=palette,
            back_qs=request.args.get("back", ""),
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

    @app.route("/scan")
    def scan_page():
        raw_path = request.args.get("path", "").strip()
        browse_path = Path(raw_path).expanduser() if raw_path else Path.home()
        if not browse_path.is_dir():
            browse_path = Path.home()

        entries, list_error = _list_subdirs(browse_path)

        return render_template(
            "scan.html",
            status=jobs.get_status(),
            browse_path=browse_path,
            parent=browse_path.parent if browse_path != browse_path.parent else None,
            entries=entries,
            list_error=list_error,
            shortcuts=_shortcuts(),
            default_model=jobs.default_model(),
            error=request.args.get("error"),
        )

    @app.route("/scan/start", methods=["POST"])
    def scan_start():
        folder_str = request.form.get("folder", "").strip()
        model = request.form.get("model", "").strip() or jobs.default_model()
        folder = Path(folder_str).expanduser()

        if not folder.is_dir():
            return redirect(url_for("scan_page", path=folder_str, error="notfound"))

        started = jobs.start_scan(app.config["DB_PATH"], folder, model)
        if not started:
            return redirect(url_for("scan_page", path=folder_str))

        return redirect(url_for("scan_page", path=folder_str))

    @app.route("/scan/status")
    def scan_status():
        return jsonify(jobs.get_status())

    @app.route("/scan/stop", methods=["POST"])
    def scan_stop():
        jobs.request_stop()
        return redirect(url_for("scan_page", path=request.form.get("folder", "")))

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
