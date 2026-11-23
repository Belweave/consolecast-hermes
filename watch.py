"""Stream notifications through Hermes's own scheduler: a no-agent cron job (no model, no tokens).

`/stream watch on` writes a small launcher to <HERMES_HOME>/scripts/ (Hermes only runs cron scripts
from there) and creates the job with the `cronjob_manage` tool, so it gets Hermes's normal delivery:
this chat, Telegram, Discord, Slack, ... The watcher itself only reads Console Cast's status.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

from . import client, runtime, store

JOB_NAME = "consolecast-watch"
SCRIPT_NAME = "consolecast-watch.py"
_PLUGIN_DIR = Path(__file__).resolve().parent

Dispatch = Callable[[str, dict], str]

LAUNCHER = '''# Console Cast stream notifications, installed by the consolecast Hermes plugin (/stream watch on).
# Prints only when something changed (empty output = silent tick). Remove with /stream watch off.
import os
import runpy
import sys

os.environ.setdefault("HERMES_HOME", {home!r})
os.environ.setdefault("CONSOLECAST_HERMES_DATA_DIR", {data!r})
os.environ.setdefault("CONSOLECAST_BINARY", {binary!r})
os.environ.setdefault("CONSOLECAST_WARN_DAYS", {warn!r})
WATCHER = {watcher!r}
if not os.path.exists(WATCHER):
    print("Console Cast notifications: the consolecast plugin is not installed any more. "
          "Remove this job with `hermes cron remove {job}` or /cron.")
    sys.exit(0)
sys.argv = [WATCHER]
runpy.run_path(WATCHER, run_name="__main__")
'''


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _dispatch() -> Dispatch:
    ctx = runtime.CTX
    if ctx is None:
        raise RuntimeError("Hermes is not available to schedule the job.")
    return ctx.dispatch_tool


def _call(dispatch: Dispatch, args: dict) -> dict[str, Any]:
    raw = dispatch("cronjob_manage", args)
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except ValueError:
        return {"success": False, "error": str(raw)[:300]}


def _find_job(dispatch: Dispatch) -> Optional[dict[str, Any]]:
    listed = _call(dispatch, {"action": "list"})
    for job in listed.get("jobs") or []:
        if job.get("name") == JOB_NAME:
            return job
    return None


def write_launcher(every_warn_days: int) -> Path:
    scripts = _home() / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / SCRIPT_NAME
    path.write_text(LAUNCHER.format(
        home=str(_home()), data=str(store.data_dir()), binary=str(runtime.setting("binary") or ""),
        warn=str(every_warn_days), watcher=str(_PLUGIN_DIR / "watcher.py"), job=JOB_NAME), encoding="utf-8")
    return path


def manage(action: str, *, every_minutes: Any = None, deliver: Any = None,
           dispatch: Optional[Dispatch] = None) -> dict[str, Any]:
    action = (action or "status").strip().lower()
    plat = client.detect_platform()
    if action == "on" and not plat.supported:
        return {"ok": False, "error": plat.note}
    dispatch = dispatch or _dispatch()
    job = _find_job(dispatch)
    if action == "status":
        if not job:
            return {"ok": True, "on": False, "summary": "Stream notifications are off. Turn them on with /stream watch on."}
        return {"ok": True, "on": job.get("enabled", True) is not False, "job": job,
                "summary": f"Stream notifications are on: {job.get('schedule') or job.get('schedule_display')}, "
                           f"delivered to {job.get('deliver', 'local')}."}
    if action == "off":
        if not job:
            return {"ok": True, "summary": "Stream notifications were already off."}
        res = _call(dispatch, {"action": "remove", "job_id": job.get("id") or job.get("job_id")})
        try:
            (_home() / "scripts" / SCRIPT_NAME).unlink()
        except OSError:
            pass
        return {"ok": bool(res.get("success", True)), "summary": "Stream notifications are off.", "result": res}
    if action != "on":
        return {"ok": False, "error": "action must be on, off or status"}
    try:
        minutes = max(1, min(60, int(every_minutes or runtime.setting("watch_interval_minutes") or 2)))
    except (TypeError, ValueError):
        minutes = 2
    warn = int(runtime.setting("free_week_warn_days") or 2)
    write_launcher(warn)
    schedule = f"every {minutes}m"
    if job:
        args = {"action": "update", "job_id": job.get("id") or job.get("job_id"), "schedule": schedule,
                "script": SCRIPT_NAME, "no_agent": True}
        if deliver:
            args["deliver"] = str(deliver)
        res = _call(dispatch, args)
    else:
        args = {"action": "create", "name": JOB_NAME, "schedule": schedule, "script": SCRIPT_NAME,
                "no_agent": True}
        if deliver:
            args["deliver"] = str(deliver)
        res = _call(dispatch, args)
    if res.get("success") is False or res.get("error"):
        return {"ok": False, "error": res.get("error") or "Hermes could not schedule the job.", "result": res}
    where = str(res.get("deliver") or deliver or "origin")
    where = "this chat" if where == "origin" else where
    return {"ok": True, "summary": (f"Stream notifications are on: every {minutes} min, to {where}. You will hear when "
                                     "the console goes live or ends, a destination drops or recovers, or the free "
                                     "week is about to end. Nothing is sent when nothing changes. To get them somewhere else, "
                                     "add a target: /stream watch on telegram."),
            "job_id": res.get("job_id") or (job or {}).get("id")}
