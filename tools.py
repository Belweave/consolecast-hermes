"""Tool handlers. Each returns a JSON string and never raises (Hermes plugin contract)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from . import client, render, runtime, safety, store

logger = logging.getLogger("consolecast")

# Plugin tool -> Console Cast tool, and how its arguments map.
APP_TOOLS: dict[str, tuple[str, Callable[[dict], dict], float]] = {
    "consolecast_start": ("engine_start", lambda a: {"armed": a.get("armed", True)}, 90.0),
    "consolecast_stop": ("engine_stop", lambda a: {}, 30.0),
    "consolecast_arm": ("arm", lambda a: {}, 30.0),
    "consolecast_disarm": ("disarm", lambda a: {}, 30.0),
    "consolecast_console_setup": ("console_setup_guide", lambda a: {"console": a.get("console")}, 20.0),
    "consolecast_obs_add_source": ("obs_add_source", lambda a: _pick(a, "mode"), 30.0),
    "consolecast_obs_setup_scene": ("obs_setup_scene", lambda a: _pick(a, "scene", "mode", "overlay"), 45.0),
    "consolecast_obs_output_start": ("obs_program_start", lambda a: _pick(a, "via"), 45.0),
    "consolecast_obs_output_stop": ("obs_program_stop", lambda a: {}, 30.0),
    "consolecast_destinations": ("destinations_list", lambda a: {}, 20.0),
    "consolecast_destination_start": ("destination_start", lambda a: _pick(a, "id"), 45.0),
    "consolecast_destination_stop": ("destination_stop", lambda a: _pick(a, "id"), 30.0),
    "consolecast_wait_for_live": ("wait_for_live", lambda a: {"timeout_seconds": _clamp(a.get("timeout_seconds"),
                                                                                         5, 600, 120)}, 0.0),
    "consolecast_diagnose": ("diagnose", lambda a: _pick(a, "dns_self_test"), 60.0),
    "consolecast_viewer": ("viewer_open", lambda a: _pick(a, "browser"), 20.0),
    "consolecast_logs": ("logs_tail", lambda a: {**_pick(a, "tag", "contains"),
                                                 "lines": _clamp(a.get("lines"), 1, 300, 60)}, 20.0),
}


def _pick(args: dict, *names: str) -> dict:
    return {n: args[n] for n in names if args.get(n) not in (None, "")}


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _err(message: str, **extra: Any) -> str:
    return _json({"ok": False, "error": message, **extra})


def resolve_app_call(tool_name: str, args: dict) -> Optional[tuple[str, dict]]:
    """Which Console Cast tool a plugin tool call reaches, and with which arguments."""
    if tool_name == "consolecast_app_call":
        name = str((args or {}).get("tool") or "")
        inner = (args or {}).get("arguments") or {}
        return (name, inner if isinstance(inner, dict) else {}) if name else None
    spec = APP_TOOLS.get(tool_name)
    if spec is None:
        return None
    return spec[0], spec[1](args or {})


# ---------------------------------------------------------------------------------------- core


def _unavailable() -> Optional[str]:
    plat = client.detect_platform()
    if not plat.supported:
        return _err(plat.note, platform=plat.label)
    if not runtime.binary():
        return _err(f"Console Cast is not installed. It is at {client.DOWNLOAD_URL} (free for 7 days, no account). "
                    "Ask the user before downloading or installing anything.", download=client.DOWNLOAD_URL)
    return None


def level_message(app_tool: str) -> str:
    """Why the app does not offer a tool, in the user's terms."""
    try:
        res = client.call_tool(runtime.binary() or "", "permissions", timeout=15)
        perm = res.data if res.ok and isinstance(res.data, dict) else {}
    except client.ConsoleCastError:
        perm = {}
    level = render.level_title(perm.get("level", ""))
    need = next((t.split("(")[-1].rstrip(")") for t in perm.get("tools_needing_higher_level") or []
                 if t.split(" ")[0] == app_tool), "")
    if need:
        return (f"Console Cast's AI Agents permission is {level}; '{app_tool}' needs {need}. The user can change it "
                "in Console Cast → Consoles & Destinations… → AI Agents (this plugin never changes it).")
    return (f"Console Cast does not offer '{app_tool}' to agents right now (permission {level}). "
            "consolecast_app_tools lists what is available.")


def run_app(app_tool: str, app_args: dict, *, call_key: str = "", timeout: float = 30.0,
            elicit: Optional[client.Elicit] = None) -> dict[str, Any]:
    """Call one Console Cast tool and return a JSON-safe dict. ``call_key`` links the app's own
    confirmation question to a person's answer in Hermes (see safety.py)."""
    if safety.is_cloud_tool(app_tool):
        return {"ok": False, "error": safety.CLOUD_MESSAGE}
    path = runtime.binary()
    if not path:
        return {"ok": False, "error": "Console Cast is not installed."}
    if elicit is None:
        def elicit(_message: str, _schema: dict) -> bool:
            return bool(call_key) and safety.LEDGER.consume(call_key)
    try:
        res = client.call_tool(path, app_tool, app_args, elicit=elicit, timeout=timeout or 30.0)
    except client.ToolNotListed:
        return {"ok": False, "error": level_message(app_tool)}
    except client.ConsoleCastError as exc:
        return {"ok": False, "error": str(exc)}
    out = client.scrub(res.as_dict())
    if not res.ok and res.asked and "declined" in res.text:
        out["error"] = safety.NOT_CONFIRMED
    data = res.data
    if res.ok and isinstance(data, dict):
        status = data.get("status") if isinstance(data.get("status"), dict) else data
        if "running" in status and "state" in status:
            try:
                store.observe(status)
            except Exception as exc:
                logger.debug("consolecast journal update failed: %s", exc)
    runtime.clear_cache()
    return out


def make_app_handler(tool_name: str) -> Callable[..., str]:
    app_tool, mapper, timeout = APP_TOOLS[tool_name]

    def handler(args: dict, task_id: str = "", session_id: str = "", **_: Any) -> str:
        try:
            args = args or {}
            blocked = _unavailable()
            if blocked:
                return blocked
            app_args = mapper(args)
            if app_tool == "wait_for_live":
                call_timeout = float(app_args["timeout_seconds"]) + 20.0
            else:
                call_timeout = timeout
            key = safety.call_key(tool_name, args, task_id, session_id)
            return _json(run_app(app_tool, app_args, call_key=key, timeout=call_timeout))
        except Exception as exc:  # never raise into the agent loop
            logger.warning("consolecast %s failed: %s", tool_name, exc)
            return _err(f"{tool_name} failed: {exc}")

    handler.__name__ = f"handle_{tool_name}"
    return handler


# ---------------------------------------------------------------------------------------- local tools


def handle_status(args: dict, **_: Any) -> str:
    try:
        data = runtime.info()
        out = runtime.public_info(data)
        out["summary"] = render.status_card(data)
        return _json(out)
    except Exception as exc:
        return _err(f"status failed: {exc}")


def preflight_result(*, diagnose: bool = True) -> dict[str, Any]:
    data = runtime.info(include=("status", "license_status", "permissions", "updates_check"))
    diagnosis = None
    if diagnose and data.get("binary") and not data.get("error"):
        status = (data.get("snapshot") or {}).get("status") or {}
        if status.get("running"):
            res = run_app("diagnose", {"dns_self_test": True}, timeout=60)
            diagnosis = res.get("result") if res.get("ok") else None
    pf = render.preflight(data, diagnosis)
    out: dict[str, Any] = {"ready": pf["ready"], "left": pf["left"], "next": pf["next"],
                           "checks": pf["checks"], "summary": render.preflight_text(pf)}
    if diagnosis:
        out["diagnosis"] = diagnosis
    return out


def handle_preflight(args: dict, **_: Any) -> str:
    try:
        args = args or {}
        return _json(preflight_result(diagnose=args.get("diagnose", True) is not False))
    except Exception as exc:
        return _err(f"preflight failed: {exc}")


def handle_destination_add_guide(args: dict, **_: Any) -> str:
    dest = str((args or {}).get("id") or "ID").strip() or "ID"
    service = str((args or {}).get("service") or "the service").strip()
    return _json({
        "ok": True,
        "never": "Do not ask the user to paste a stream key into this chat. Keys never pass through a model.",
        "options": [
            f"In Console Cast's own window: Consoles & Destinations… → Local Outputs → Save Destination, with the ID "
            f"'{dest}' and the server URL and stream key from the service.",
            f"Or in the user's own terminal (not through Hermes): `consolecast output save {dest}`, then paste the "
            "full URL including the key on standard input.",
        ],
        "where_to_find_the_key": f"The server URL and stream key are in {service}'s streaming dashboard.",
        "then": f"Once it is saved, consolecast_destinations lists '{dest}', and consolecast_destination_start "
                "sends to it (after the user confirms).",
    })


def handle_end_stream(args: dict, **_: Any) -> str:
    try:
        blocked = _unavailable()
        if blocked:
            return blocked
        listed = run_app("destinations_list", {}, timeout=20)
        if not listed.get("ok"):
            return _json(listed)
        result = listed.get("result") or {}
        stopped, errors = [], []
        for d in result.get("destinations") or []:
            if d.get("state") in ("connecting", "streaming", "retrying"):
                res = run_app("destination_stop", {"id": d.get("id")}, timeout=30)
                if res.get("ok"):
                    stopped.append(d.get("id"))
                else:
                    errors.append(f"{d.get('id')}: {res.get('error')}")
        program = None
        if result.get("obs_program_live"):
            res = run_app("obs_program_stop", {}, timeout=30)
            program = "stopped" if res.get("ok") else res.get("error")
        summary = store.last_session()
        return _json({"ok": not errors, "destinations_stopped": stopped, "errors": errors,
                      "obs_program_output": program or "was not on",
                      "note": "Console Cast is still running and armed. consolecast_stream_summary has the recap.",
                      "session": summary})
    except Exception as exc:
        return _err(f"end stream failed: {exc}")


def handle_license(args: dict, **_: Any) -> str:
    try:
        blocked = _unavailable()
        if blocked:
            return blocked
        res = run_app("license_status", {}, timeout=20)
        if not res.get("ok"):
            return _json(res)
        lic = render.licence_summary(res.get("result"))
        out = {"ok": True, "licence": res.get("result"), "summary": lic["text"], "days_left": lic["days_left"]}
        if not lic["purchased"]:
            out["plans"] = client.PRICING_URL
            out["how_to_activate"] = safety.KEY_ENTRY_HELP
        return _json(out)
    except Exception as exc:
        return _err(f"licence check failed: {exc}")


def summary_result() -> dict[str, Any]:
    session = store.last_session()
    out: dict[str, Any] = {"ok": True}
    if not session:
        out["summary"] = ("No stream recorded yet. Hermes notes a stream when it checks Console Cast while the "
                          "console is live (any consolecast tool, /stream, or /stream watch notifications).")
        return out
    start = session.get("started_at") or 0
    end = session.get("ended_at") or session.get("last_seen_at") or start
    lines = [("Stream in progress" if session.get("in_progress") else "Last stream") +
             f": started {time.strftime('%a %d %b %H:%M', time.localtime(start))}, "
             f"{'live for' if session.get('in_progress') else 'ran'} about {store.duration_text(end - start)}"
             + ("" if session.get("in_progress") else f" ({session.get('ended_because', 'ended')})") + "."]
    if session.get("peak_kbps"):
        lines.append(f"Peak bitrate from the console: {int(session['peak_kbps']):,} kbps.")
    for did, d in (session.get("destinations") or {}).items():
        bits = [f"{did} → {d.get('host', '')}"]
        bits.append("streamed" if d.get("streamed") else f"never reached streaming (last {d.get('last_state')})")
        if d.get("drops"):
            bits.append(f"dropped {d['drops']}×")
        if int(d.get("max_attempts") or 0) > 1:
            bits.append(f"{d['max_attempts']} connection attempts")
        lines.append("• " + ", ".join(bits))
    for w in session.get("warnings") or []:
        lines.append(f"! {w}")
    errors = run_app("logs_tail", {"tag": "err", "lines": 15}, timeout=20) if runtime.binary() else {}
    err_lines = (errors.get("result") or {}).get("lines") if errors.get("ok") else None
    if err_lines:
        out["recent_errors"] = err_lines[-15:]
    out["session"] = session
    out["summary"] = "\n".join(lines)
    out["note"] = "Times are when Hermes noticed the change, so they can be a few minutes off."
    return out


def handle_stream_summary(args: dict, **_: Any) -> str:
    try:
        return _json(summary_result())
    except Exception as exc:
        return _err(f"summary failed: {exc}")


_TOOLS_CACHE: dict[str, Any] = {"at": 0.0, "tools": None}


def app_tool_list(max_age: float = 60.0, timeout: float = 10.0) -> list[dict[str, Any]]:
    if _TOOLS_CACHE["tools"] is not None and time.monotonic() - _TOOLS_CACHE["at"] < max_age:
        return _TOOLS_CACHE["tools"]
    path = runtime.binary()
    if not path:
        return []
    with client.McpSession(path, timeout=timeout) as s:
        tools = s.list_tools()
    _TOOLS_CACHE.update(at=time.monotonic(), tools=tools)
    return tools


def handle_app_tools(args: dict, **_: Any) -> str:
    try:
        blocked = _unavailable()
        if blocked:
            return blocked
        rows = []
        for t in app_tool_list(max_age=0):
            name = t.get("name", "")
            if safety.is_cloud_tool(name):
                continue  # Console Cast Cloud and account actions are not part of this plugin
            ann = t.get("annotations") or {}
            decision = safety.classify(name, {}, live=lambda: False, annotations=ann,
                                       input_schema=t.get("inputSchema"))
            rows.append({
                "name": name,
                "title": t.get("title") or ann.get("title") or "",
                "about": (t.get("description") or "").split(". ")[0][:200],
                "read_only": bool(ann.get("readOnlyHint")),
                "arguments": sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys()),
                "through_hermes": {"allow": "yes", "ask": "asks the user first",
                                   "block": "no: takes a key; the user does it in Console Cast or a terminal"}[
                    decision.action],
            })
        return _json({"ok": True, "tools": rows, "note": "Console Cast lists only what its AI Agents permission "
                      "allows. consolecast_app_call runs any of these. Console Cast Cloud and account actions are "
                      "not available through this plugin."})
    except client.ConsoleCastError as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"listing Console Cast tools failed: {exc}")


def handle_app_call(args: dict, task_id: str = "", session_id: str = "", **_: Any) -> str:
    try:
        blocked = _unavailable()
        if blocked:
            return blocked
        resolved = resolve_app_call("consolecast_app_call", args or {})
        if not resolved:
            return _err("Name a Console Cast tool in 'tool' (consolecast_app_tools lists them).")
        app_tool, app_args = resolved
        if safety.is_cloud_tool(app_tool):  # the pre_tool_call hook refuses these too
            return _err(safety.CLOUD_MESSAGE)
        if app_tool in safety.SECRET_INPUT:  # the pre_tool_call hook blocks these too
            return _err(safety.secret_tool_message(app_tool))
        timeout = 640.0 if app_tool == "wait_for_live" else 90.0
        key = safety.call_key("consolecast_app_call", args or {}, task_id, session_id)
        return _json(run_app(app_tool, app_args, call_key=key, timeout=timeout))
    except Exception as exc:
        return _err(f"Console Cast call failed: {exc}")


def handle_notifications(args: dict, **kw: Any) -> str:
    try:
        from . import watch

        return _json(watch.manage(str((args or {}).get("action") or "status"),
                                  every_minutes=(args or {}).get("every_minutes"),
                                  deliver=(args or {}).get("deliver")))
    except Exception as exc:
        return _err(f"notifications failed: {exc}")


LOCAL_HANDLERS: dict[str, Callable[..., str]] = {
    "consolecast_status": handle_status,
    "consolecast_preflight": handle_preflight,
    "consolecast_destination_add_guide": handle_destination_add_guide,
    "consolecast_end_stream": handle_end_stream,
    "consolecast_license": handle_license,
    "consolecast_stream_summary": handle_stream_summary,
    "consolecast_app_tools": handle_app_tools,
    "consolecast_app_call": handle_app_call,
    "consolecast_notifications": handle_notifications,
}

# Tools that still make sense on a computer Console Cast does not run on (they explain why).
ALWAYS_AVAILABLE = {"consolecast_status", "consolecast_preflight"}


def handler_for(name: str) -> Callable[..., str]:
    return LOCAL_HANDLERS.get(name) or make_app_handler(name)
