"""Plugin-wide state: settings, where Console Cast is, and a short-lived status cache."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from . import client, store

logger = logging.getLogger("consolecast")

DEFAULTS: dict[str, Any] = {
    "binary": "",
    "context_injection": True,
    "watch_interval_minutes": 2,
    "free_week_warn_days": 2,
    "terminal_guard": True,
}

_config_getter: Optional[Callable[[str, Any], Any]] = None
CTX: Any = None  # the PluginContext, set by register()
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def bind_config(getter: Optional[Callable[[str, Any], Any]]) -> None:
    global _config_getter
    _config_getter = getter


def setting(name: str) -> Any:
    default = DEFAULTS.get(name)
    if _config_getter is None:
        return default
    try:
        value = _config_getter(name, default)
    except Exception:
        return default
    return default if value is None else value


def binary() -> Optional[str]:
    return client.find_binary(str(setting("binary") or ""))


def info(*, include: tuple[str, ...] = ("status", "license_status", "permissions"), timeout: float = 20.0,
         max_age: float = 0.0) -> dict[str, Any]:
    """Platform, binary, version and a snapshot of the read-only tools. Never raises."""
    key = "info:" + ",".join(include)
    if max_age:
        with _cache_lock:
            hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < max_age:
            return hit[1]
    plat = client.detect_platform()
    out: dict[str, Any] = {"platform": plat, "binary": None, "version": "", "snapshot": None, "error": ""}
    if plat.supported:
        path = binary()
        out["binary"] = path
        if path:
            try:
                snap = client.snapshot(path, include=include, timeout=timeout)
                out["snapshot"] = snap
                out["version"] = snap.get("server_version") or ""
                status = snap.get("status")
                if isinstance(status, dict):
                    try:
                        store.observe(status)
                    except Exception as exc:  # the journal is a convenience; never fail a status call on it
                        logger.debug("consolecast journal update failed: %s", exc)
            except client.ConsoleCastError as exc:
                out["error"] = str(exc)
    with _cache_lock:
        _cache[key] = (time.monotonic(), out)
    return out


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def public_info(data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe view of :func:`info` for tool results."""
    plat: client.PlatformInfo = data["platform"]
    out: dict[str, Any] = {
        "platform": plat.label,
        "supported": plat.supported,
        "installed": bool(data.get("binary")),
        "version": data.get("version") or "",
    }
    if plat.note:
        out["platform_note"] = plat.note
    if not data.get("binary") and plat.supported:
        out["download"] = client.DOWNLOAD_URL
        out["install_note"] = "Do not download or install anything without asking the user first."
    if data.get("error"):
        out["error"] = data["error"]
    snap = data.get("snapshot") or {}
    for name in ("status", "license_status", "permissions", "diagnose"):
        if name in snap:
            out[name] = snap[name]
    if snap.get("errors"):
        out["unavailable"] = snap["errors"]
    return out
