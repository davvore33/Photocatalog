import dataclasses
import threading
from datetime import datetime, timezone
from pathlib import Path

from .. import config, db, scanner

_lock = threading.Lock()
_cancel_event = threading.Event()
_state = {
    "status": "idle",  # idle | running | done | cancelled | error
    "phase": None,  # scanning | tagging | stopping | done | cancelled | error
    "folder": None,
    "model": None,
    "started_at": None,
    "finished_at": None,
    "summary": None,  # live scanner.ScanSummary instance while running
    "error": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_status() -> dict:
    with _lock:
        summary = _state["summary"]
        return {
            "status": _state["status"],
            "phase": _state["phase"],
            "folder": _state["folder"],
            "model": _state["model"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
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
            summary=None,
            error=None,
        )

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
                    _state.update(status="done", phase="done", finished_at=_now())
                else:
                    _state.update(status="cancelled", phase="cancelled", finished_at=_now())
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            with _lock:
                _state.update(status="error", phase="error", finished_at=_now(), error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return True


def request_stop() -> bool:
    """Signal the running scan to stop at the next safe checkpoint. Returns False if none running."""
    with _lock:
        if _state["status"] != "running":
            return False
        _state["phase"] = "stopping"
    _cancel_event.set()
    return True


def default_model() -> str:
    return config.DEFAULT_VISION_MODEL
