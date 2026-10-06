# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Use the project venv (`.venv/`; the untracked `venv/` dir is not the one the macOS launcher expects).

```bash
pip install -e ".[dev]"                 # add ".[heic]" for iPhone HEIC support
.venv/bin/pytest                         # full suite
.venv/bin/pytest tests/test_scanner.py::test_name   # single test
photocatalog scan <folder> [--model M] [--no-tag] [--no-scan] [--retry-errors] [--prune]
photocatalog serve [--host --port --debug]           # viewer on http://127.0.0.1:5000
photocatalog stats | prune [--yes] | compact
scripts/build_macos_app.sh [dest]        # builds the Photocatalog.app launcher (needs .venv/bin/photocatalog)
```

No linter/formatter is configured. Tagging needs a running local Ollama with the vision model pulled (default `qwen3-vl:8b`); tests don't need it, and `tests/conftest.py` redirects thumbnails/logs to a temp dir so the suite never touches `~/.photocatalog`.

## Architecture

Single package `src/photocatalog/` with a CLI (`cli.py`, argparse subcommands) and a Flask viewer (`viewer/`) over one SQLite catalog. Runtime data lives outside the repo in `~/.photocatalog/` (`catalog.db`, `thumbnails/`, `logs/`); all paths and tunables (Ollama URL, model, timeouts, supported extensions, page size, log rotation) are in `config.py`.

### Two-stage scan (`scanner.py`)
- **Stage A** (`scan_stage_a`) walks the folder with no network: skips files whose size+mtime are unchanged, otherwise hashes (SHA-256) and classifies. A path with **no row yet** and known content is a *move* (a row with that hash whose old path is gone → repoint it) or an *extra copy* (all old paths still exist → new row cloned from the original, tags included). A path that **already has a row** with a new hash is an *update* (re-extracted, reset to `tags_status='pending'`) — never route that through the move logic, `path` is UNIQUE. `file_hash` is therefore **not unique**: identical copies share a hash and a thumbnail (named by hash), so use `db.get_images_by_hash` and only delete a thumbnail when no row references it. Extraction errors on a single file are logged and the file is skipped; they must not abort the scan.
- **Stage B** (`scan_stage_b`) tags every `pending` row (plus `error` rows with `retry_errors`) through Ollama (`vision.py`). It is scoped to the scanned `folder` by path (browser scans must pass `folder=` too). `vision.VisionUnavailable` (Ollama unreachable, or 404 for a missing model) aborts the stage and leaves rows `pending`; per-image failures raise plain `VisionError` and mark that row `error`. Each row is committed immediately, so a crash resumes where it left off; each attempt's duration is recorded in `tagging_events` (feeds the per-model speed stats).
- **Tagging speed (measured against the real catalog, ~40 s/image before):** nearly all time is the model's generated tokens, not image handling. `qwen3-vl:8b` is a *thinking* model, so `vision.PROMPT` ends by asking it not to reason (≈2x faster, similar tags). Things already tried that do **not** help: `think: false` (ignored by this model), a smaller `VISION_IMAGE_MAX_DIMENSION` (Ollama sends the same ~1147 prompt tokens regardless), and parallel requests (aggregate throughput stayed flat), so keep stage B sequential. Wide columns are still costly, so avoid `SELECT *` over many rows (`db.images_by_status` returns only `id, path`).
- Both stages accept a `threading.Event` for cancellation, checked at file boundaries, and return `False` if cancelled.
- RAW files (ARW/CR2/CR3/NEF/RAF) are never demosaiced: `raw_extract.py` pulls the embedded JPEG preview, and EXIF, color, thumbnail and vision input are all derived from it (true sensor size is still stored as width/height).

### Database (`db.py`)
EXIF passes through `exif_extract.slim_exif` before storage: `MakerNote` (opaque vendor binary, once ~84% of a 625 MB catalog) is dropped and XMP is stored as unpadded text. Catalogs written before that are cleaned with `photocatalog compact` (rewrite + `VACUUM`). The photos carry no usable unique ID in EXIF (no `ImageUniqueID`, serials or sub-seconds), so identity is the SHA-256 content hash.

`connect()` runs the `SCHEMA` script on every open (`CREATE TABLE IF NOT EXISTS`) — there is no migration system, so adding a column to an existing table needs explicit handling. Tables: `images` (with promoted EXIF columns plus raw `exif_json`), `tags`, `image_tags` (cascade deletes, `foreign_keys` is ON), `tagging_events`. Row access is via `sqlite3.Row`.

### Viewer (`viewer/`)
- `app.py`: `create_app(db_path)` factory; one connection per request via `flask.g`. Filter parsing (`_parse_filters`) is shared by the grid (`/`) and `/export.csv` so the export matches the current filters. EXIF dates are stored as `YYYY:MM:DD HH:MM:SS` while the UI takes `YYYY-MM-DD`, so the date filters compare normalized prefixes (`_date_clause`). A `before_request` hook rejects POSTs whose `Origin` isn't this host (local-server CSRF), and CSV cells are prefixed against spreadsheet formula injection. The grid selects only the columns the cards need and sorts via the composite `idx_images_sort`; `/export.csv` streams from its own DB connection (a full export of a ~10k-image catalog is ~600 MB, building it in memory took 5 GB). Other routes: `/image/<id>`, `/thumb/<id>.jpg`, `/original/<id>`, `/scan*`, `/lang/<code>`.
- `jobs.py`: module-level singleton for browser-triggered scans — one background thread, one `_state` dict guarded by `_lock`, one cancel event. Only one scan runs at a time, and CLI-run scans are a separate process and are not tracked in this state (so the global status badge only reflects browser-started scans).
- `i18n.py`: flat key → string dicts for `it` (the default) and `en`; templates call `t('key')`, language is a cookie. Add every new UI string to **both** languages.
- Templates in `viewer/templates/`, a single `static/style.css`.

### Logging
`logging_setup.setup_logging()` is idempotent (called by both `cli.main` and `create_app`) and writes to stderr plus a rotating file. The CLI's user-facing progress is plain `print`; the per-file trail goes to the logger.

## Notes
- README.md and README.it.md are parallel documents; keep them in sync when changing user-facing behavior.
- HEIC/HEIF is wired up in `photocatalog/__init__.py`: only if `pillow_heif` imports does it register the Pillow opener and add `.heic`/`.heif` to `config.SUPPORTED_EXTENSIONS` (the extension list is therefore not a constant).
- Ollama tagging is deliberately sequential (single local model instance).
