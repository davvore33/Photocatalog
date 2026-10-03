import dataclasses
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import config, db, scanner

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cancel_event = threading.Event()
_state = {
    "status": "idle",  # idle | running | done | cancelled | error
    "phase": None,  # scanning | tagging | stopping | done | cancelled | error
    "folder": None,
    "model": None,
    "started_at": None,
    "finished_at": None,
    "started_monotonic": None,
    "finished_monotonic": None,
    "summary": None,  # live scanner.ScanSummary instance while running
    "error": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_status() -> dict:
    with _lock:
        summary = _state["summary"]
        elapsed = None
        if _state["started_monotonic"] is not None:
            end = _state["finished_monotonic"] or time.monotonic()
            elapsed = round(end - _state["started_monotonic"], 1)
        return {
            "status": _state["status"],
            "phase": _state["phase"],
            "folder": _state["folder"],
            "model": _state["model"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "elapsed_seconds": elapsed,
            "error": _state["error"],
            "counts": dataclasses.asdict(summary) if summary is not None else None,
        }


def start_scan(db_path: Path, folder: Path, model: str) -> bool:
    """Kick off a scan in a background thread. Returns False if one is already running."""
    with _lock:
        if _state["status"] == "running":
            return False
        _cancel_event.clear()
        _state.update(
            status="running",
            phase="scanning",
            folder=str(folder),
            model=model,
            started_at=_now(),
            finished_at=None,
            started_monotonic=time.monotonic(),
            finished_monotonic=None,
            summary=None,
            error=None,
        )
    logger.info("browser-triggered scan started: folder=%s model=%s", folder, model)

    def run() -> None:
        try:
            summary = scanner.ScanSummary()
            with _lock:
                _state["summary"] = summary

            with db.open_db(db_path) as conn:
                completed = scanner.scan_stage_a(conn, folder, summary, cancel_event=_cancel_event)
                if completed:
                    with _lock:
                        _state["phase"] = "tagging"
                    completed = scanner.scan_stage_b(
                        conn, summary, model=model, cancel_event=_cancel_event
                    )

            with _lock:
                if completed:
                    _state.update(
                        status="done", phase="done", finished_at=_now(), finished_monotonic=time.monotonic()
                    )
                    logger.info(
                        "browser-triggered scan done: folder=%s tagged=%d errors=%d",
                        folder, summary.tagged, summary.tag_errors,
                    )
                else:
                    _state.update(
                        status="cancelled",
                        phase="cancelled",
                        finished_at=_now(),
                        finished_monotonic=time.monotonic(),
                    )
                    logger.info("browser-triggered scan cancelled: folder=%s", folder)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            with _lock:
                _state.update(
                    status="error",
                    phase="error",
                    finished_at=_now(),
                    finished_monotonic=time.monotonic(),
                    error=str(exc),
                )
            logger.exception("browser-triggered scan failed: folder=%s", folder)

    threading.Thread(target=run, daemon=True).start()
    return True


def request_stop() -> bool:
    """Signal the running scan to stop at the next safe checkpoint. Returns False if none running."""
    with _lock:
        if _state["status"] != "running":
            return False
        _state["phase"] = "stopping"
    logger.info("scan stop requested")
    _cancel_event.set()
    return True


def default_model() -> str:
    return config.DEFAULT_VISION_MODEL
