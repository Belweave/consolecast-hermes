"""Stream notifications through Hermes's own scheduler: a no-agent cron job (no model, no tokens).

`/stream watch on` writes a small launcher to <HERMES_HOME>/scripts/ (Hermes only runs cron scripts
from there) and creates the job with the `cronjob_manage` tool, so it gets Hermes's normal delivery:
this chat, Telegram, Discord, Slack, ... The watcher itself only reads Console Cast's status.

Two entry points, one per caller:

* :func:`manage` is what the model reaches (the ``consolecast_notifications`` tool). Going through
  ``ctx.dispatch_tool`` skips the cron run's removal of the ``cronjob`` toolset, so inside a Hermes
  cron run it refuses ``on`` and ``off`` unless ``cron.allow_agent_scheduling`` is true, exactly as
  Hermes would for its own cron tool. ``status`` is always allowed.
* :func:`manage_for_person` is only for ``/stream watch``, which a person types. No tool calls it.
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


_FALSE_WORDS = ("", "0", "false", "no", "off")
_TRUE_WORDS = ("1", "true", "yes", "on")


def in_cron_session() -> Optional[bool]:
    """True inside a Hermes cron run, False outside one, None when this Hermes cannot say.

    Reads ``HERMES_CRON_SESSION`` through ``gateway.session_context.get_session_env`` (public plugin
    API): the cron scheduler binds it per run, so ``os.environ`` alone would miss it."""
    try:
        from gateway.session_context import get_session_env
    except Exception:
        return None
    try:
        value = get_session_env("HERMES_CRON_SESSION", "")
    except Exception:
        return None
    return str(value or "").strip().lower() not in _FALSE_WORDS


def agent_scheduling_allowed() -> bool:
    """Hermes's ``cron.allow_agent_scheduling`` (default false). False when it cannot be read."""
    try:
        try:
            from hermes_cli.config import load_config_readonly as load
        except ImportError:
            from hermes_cli.config import load_config as load
        cfg = load()
    except Exception:
        return False
    cron = cfg.get("cron") if isinstance(cfg, dict) else None
    value = cron.get("allow_agent_scheduling") if isinstance(cron, dict) else None
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_WORDS
    if isinstance(value, (bool, int, float)):
        return bool(value)
    return False


def cron_refusal(action: str) -> Optional[str]:
    """Why an agent may not turn notifications on or off here, or None when it may.

    Refuses when this is a cron run, and also when this Hermes cannot say whether it is one (no
    ``get_session_env``): refusing costs the user one typed command, allowing could let a scheduled
    run create jobs with ``cron.allow_agent_scheduling`` off."""
    if action not in ("on", "off"):
        return None
    cron = in_cron_session()
    if cron is False or agent_scheduling_allowed():
        return None
    where = "from a scheduled Hermes run" if cron else "here (this Hermes cannot say whether this is a scheduled run)"
    return (f"Stream notifications cannot be turned {action} by an agent {where}, and Hermes's "
            "cron.allow_agent_scheduling setting is off. Nothing was changed. Ask the user to run "
            f"/stream watch {action} themselves.")


def manage(action: str, *, every_minutes: Any = None, deliver: Any = None,
           dispatch: Optional[Dispatch] = None) -> dict[str, Any]:
    """The model's path (``consolecast_notifications``). Checks :func:`cron_refusal` before anything
    is written or dispatched."""
    action = (action or "status").strip().lower()
    refusal = cron_refusal(action)
    if refusal:
        return {"ok": False, "error": refusal, "run_yourself": f"/stream watch {action}"}
    return _manage(action, every_minutes=every_minutes, deliver=deliver, dispatch=dispatch)


def manage_for_person(action: str, *, every_minutes: Any = None, deliver: Any = None,
                      dispatch: Optional[Dispatch] = None) -> dict[str, Any]:
    """``/stream watch`` only: a person typed it, so Hermes's agent-scheduling rule does not apply."""
    return _manage((action or "status").strip().lower(), every_minutes=every_minutes, deliver=deliver,
                   dispatch=dispatch)


def _manage(action: str, *, every_minutes: Any = None, deliver: Any = None,
            dispatch: Optional[Dispatch] = None) -> dict[str, Any]:
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
