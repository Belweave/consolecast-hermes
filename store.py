"""Small JSON files under <HERMES_HOME>/plugin-data/consolecast/: the stream journal, the watcher's
last-seen state and a few one-time flags. Standard library only (the cron watcher imports it too).

Nothing secret is ever written here: only states, host names, counts and times.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

PLUGIN_NAME = "consolecast"
MAX_SESSIONS = 20
_lock = threading.Lock()


def data_dir() -> Path:
    """The plugin's data folder; follows the active Hermes profile."""
    override = os.environ.get("CONSOLECAST_HERMES_DATA_DIR")
    if override:
        root = Path(override)
    else:
        try:
            from plugins.plugin_storage import plugin_data_dir  # public Hermes plugin API

            return plugin_data_dir(PLUGIN_NAME)
        except Exception:
            home = os.environ.get("HERMES_HOME") or os.path.join(os.path.expanduser("~"), ".hermes")
            root = Path(home) / "plugin-data" / PLUGIN_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def read(name: str, default: Any = None) -> Any:
    path = data_dir() / name
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(name: str, value: Any) -> None:
    folder = data_dir()
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=1, sort_keys=True)
        os.replace(tmp, folder / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def flag(name: str) -> bool:
    return bool((read("flags.json", {}) or {}).get(name))


def set_flag(name: str, value: Any = True) -> None:
    with _lock:
        flags = read("flags.json", {}) or {}
        flags[name] = value
        write("flags.json", flags)


def get_value(name: str, default: Any = None) -> Any:
    return (read("flags.json", {}) or {}).get(name, default)


# ---------------------------------------------------------------------------------------- journal


def _now() -> float:
    return time.time()


def is_live(status: Optional[dict]) -> bool:
    if not isinstance(status, dict):
        return False
    stream = status.get("stream") or {}
    return bool(stream.get("live")) or status.get("state") == "live"


def observe(status: Optional[dict], *, now: Optional[float] = None) -> list[dict[str, Any]]:
    """Fold one status snapshot into the journal. Returns the transitions it noticed.

    Times are when Hermes noticed, not exact: the journal is only as fine as how often it looks.
    """
    if not isinstance(status, dict):
        return []
    now = now or _now()
    events: list[dict[str, Any]] = []
    with _lock:
        journal = read("journal.json", {}) or {}
        sessions: list[dict] = journal.get("sessions") or []
        current: Optional[dict] = journal.get("current")
        live = is_live(status)
        running = bool(status.get("running"))
        if live and current is None:
            current = {"started_at": now, "destinations": {}, "peak_kbps": 0, "warnings": []}
            events.append({"kind": "live_started"})
        if current is not None:
            kbps = int((status.get("stream") or {}).get("bitrate_kbps") or 0)
            current["peak_kbps"] = max(int(current.get("peak_kbps") or 0), kbps)
            current["last_seen_at"] = now
            for warning in status.get("warnings") or []:
                text = str((warning or {}).get("message") or "")[:200]
                if text and text not in current["warnings"]:
                    current["warnings"] = (current["warnings"] + [text])[-10:]
            dests: dict = current.setdefault("destinations", {})
            for d in status.get("destinations") or []:
                did = str(d.get("id") or "")
                if not did:
                    continue
                state = str(d.get("state") or "")
                entry = dests.setdefault(did, {"host": d.get("host", ""), "first_state": state, "drops": 0,
                                               "max_attempts": 0, "streamed": False})
                prev = entry.get("last_state")
                if state == "streaming":
                    entry["streamed"] = True
                    entry.setdefault("started_at", now)
                if prev == "streaming" and state == "retrying":
                    entry["drops"] = int(entry.get("drops") or 0) + 1
                    events.append({"kind": "destination_dropped", "id": did, "host": entry.get("host", "")})
                if prev == "retrying" and state == "streaming":
                    events.append({"kind": "destination_recovered", "id": did, "host": entry.get("host", "")})
                if prev == "streaming" and state == "stopped":
                    entry["stopped_at"] = now
                    events.append({"kind": "destination_stopped", "id": did, "host": entry.get("host", "")})
                entry["max_attempts"] = max(int(entry.get("max_attempts") or 0), int(d.get("attempts") or 0))
                entry["last_state"] = state
            if not live:
                current["ended_at"] = now
                current["ended_because"] = "stream ended" if running else "Console Cast stopped"
                sessions = (sessions + [current])[-MAX_SESSIONS:]
                events.append({"kind": "live_ended", "started_at": current["started_at"],
                               "because": current["ended_because"]})
                current = None
        journal["sessions"], journal["current"] = sessions, current
        write("journal.json", journal)
    return events


def last_session() -> Optional[dict[str, Any]]:
    journal = read("journal.json", {}) or {}
    if journal.get("current"):
        return dict(journal["current"], in_progress=True)
    sessions = journal.get("sessions") or []
    return dict(sessions[-1], in_progress=False) if sessions else None


def duration_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min"
    return f"{seconds} s"
