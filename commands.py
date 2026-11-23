"""/stream (alias /consolecast): Console Cast from any Hermes chat, terminal or messaging app.

Handlers run in the Hermes gateway and return text; they never print.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from . import client, render, runtime, store, tools, watch

logger = logging.getLogger("consolecast")

HELP = """Console Cast for Hermes
/stream                status at a glance
/stream setup [ps5|xbox]   guided setup; safe to run again
/stream doctor         am I ready? what is wrong and what to do
/stream live [ID]      go live on a destination (asks you first)
/stream stop [ID]      end the stream, or stop one destination
/stream destinations   saved destinations
/stream add ID         how to save a destination without pasting its key here
/stream watch on|off [minutes] [telegram|discord|...]   notifications when you go live, a destination drops, or the free week ends
/stream recap          after-stream summary"""

YES = [{"value": "yes", "label": "Go live", "description": "Start sending now"},
       {"value": "no", "label": "Cancel", "description": "Change nothing"}]


def _ask(question: str, choices: list) -> Optional[str]:
    ctx = runtime.CTX
    if ctx is None or not hasattr(ctx, "ask_choice"):
        return None
    try:
        return ctx.ask_choice(question, choices)
    except Exception as exc:
        logger.debug("consolecast ask_choice failed: %s", exc)
        return None


def _confirmed(_message: str, _schema: dict) -> bool:
    """Elicitation answer after the person confirmed in this command."""
    return True


def handle(raw_args: str = "", **_: Any) -> str:
    try:
        parts = (raw_args or "").split()
        sub = parts[0].lower() if parts else "status"
        rest = parts[1:]
        if sub in ("help", "-h", "--help", "?"):
            return HELP
        if sub in ("status", "st"):
            return render.status_card(runtime.info())
        if sub == "setup":
            return setup(rest[0].lower() if rest else "")
        if sub in ("doctor", "check", "ready", "preflight"):
            return doctor()
        if sub in ("live", "golive", "go-live", "start"):
            return go_live(rest[0] if rest else "")
        if sub in ("stop", "end"):
            return stop(rest[0] if rest else "")
        if sub in ("destinations", "dest", "dests", "outputs"):
            res = tools.run_app("destinations_list", {}, timeout=20)
            if not res.get("ok"):
                return f"{render.BAD} {res.get('error')}"
            return render.destinations_text((res.get("result") or {}).get("destinations") or [])
        if sub == "add":
            return add_help(rest[0] if rest else "ID")
        if sub in ("watch", "notify", "notifications"):
            action = rest[0].lower() if rest else "status"
            minutes = next((r for r in rest[1:] if r.isdigit()), None)
            deliver = next((r for r in rest[1:] if not r.isdigit()), None)
            res = watch.manage(action, every_minutes=minutes, deliver=deliver)
            return res.get("summary") or res.get("error") or "Done."
        if sub in ("recap", "summary"):
            return tools.summary_result()["summary"]
        return f"Unknown: /stream {sub}\n\n{HELP}"
    except Exception as exc:
        logger.warning("/stream failed: %s", exc)
        return f"{render.BAD} /stream failed: {exc}"


def _unsupported() -> Optional[str]:
    plat = client.detect_platform()
    if not plat.supported:
        return plat.note
    if not runtime.binary():
        return (f"Console Cast is not installed. Get it at {client.DOWNLOAD_URL} (free for 7 days, no account), "
                "then run /stream setup again. Hermes never downloads or installs it for you.")
    return None


def setup(console: str = "") -> str:
    done, now, left = [], [], []
    plat = client.detect_platform()
    if not plat.supported:
        return plat.note
    data = runtime.info()
    if not data.get("binary"):
        left.append(f"Install Console Cast from {client.DOWNLOAD_URL}, open it once, then run /stream setup again.")
        return _three(done, now, left)
    if data.get("error"):
        left.append(f"Console Cast did not answer: {data['error']}")
        return _three(done, now, left)
    snap = data.get("snapshot") or {}
    done.append(f"Console Cast {data.get('version') or ''} installed ({plat.label})".replace("  ", " "))
    lic = render.licence_summary(snap.get("license_status"))
    if lic["kind"] == "free_week_ended":
        left.append(f"Subscribe at {client.PRICING_URL}, then enter the licence key in Console Cast's own window.")
    elif lic["kind"] != "unknown":
        done.append(f"Licence: {lic['text']}")
    level = str((snap.get("permissions") or {}).get("level") or "read")
    status = snap.get("status") or {}

    def act(app_tool: str, args: dict, label: str) -> bool:
        res = tools.run_app(app_tool, args, timeout=90)
        if res.get("ok"):
            now.append(label)
            return True
        left.append(f"{label}: {res.get('error')}")
        return False

    if not status.get("running"):
        if act("engine_start", {"armed": True}, "Started and armed Console Cast"):
            status = (runtime.info(include=("status",)).get("snapshot") or {}).get("status") or status
    elif status.get("state") == "passthrough":
        if act("arm", {}, "Armed Console Cast"):
            status = (runtime.info(include=("status",)).get("snapshot") or {}).get("status") or status
    else:
        done.append(f"Running: {status.get('state_title') or status.get('state')}")

    obs = status.get("obs") or {}
    if status.get("running"):
        if not obs.get("websocket_enabled"):
            left.append("In OBS Studio: Tools → WebSocket Server Settings → Enable WebSocket server, then run "
                        "/stream setup again. (No OBS yet? It is free at https://obsproject.com.)")
        elif obs.get("source_added"):
            done.append("OBS source 'Console Cast' is in your scene")
        else:
            act("obs_add_source", {"mode": "media"}, "Added the 'Console Cast' source to OBS")

    if (status.get("console") or {}).get("seen"):
        done.append(f"Console found at {(status.get('console') or {}).get('ip', 'your network')}")
    else:
        console = console or str(store.get_value("console") or "")
        if console not in ("ps5", "xbox"):
            console = _ask("Which console do you stream from?", [
                {"value": "ps5", "label": "PS5"}, {"value": "xbox", "label": "Xbox Series X|S"}]) or ""
        if console in ("ps5", "xbox"):
            store.set_flag("console", console)
            guide = tools.run_app("console_setup_guide", {"console": console}, timeout=20)
            g = guide.get("result") or {}
            if guide.get("ok") and g:
                left.append(f"On your {g.get('name', console)}: {g.get('dns_menu')} → Manual DNS. Primary "
                            f"{g.get('primary_dns')}, Secondary {g.get('secondary_dns')}. Then start a broadcast: "
                            f"{g.get('broadcast_menu')}.")
                left.extend(f"Note: {n}" for n in (g.get("notes") or [])[:2])
            else:
                left.append(f"Console values: {guide.get('error')}")
        else:
            dns = status.get("console_dns") or {}
            left.append(f"Set your console's DNS to Primary {dns.get('primary', '?')}, Secondary "
                        f"{dns.get('secondary', '0.0.0.0')} (/stream setup ps5 or /stream setup xbox shows the menus).")
    if (status.get("stream") or {}).get("live"):
        done.append("The console's picture is arriving")
    elif (status.get("console") or {}).get("seen"):
        left.append("Start a Twitch broadcast on the console; /stream shows LIVE when the picture arrives.")
    if level == "read":
        left.append("Optional: Console Cast's AI Agents permission is Read only, so Hermes can look but not start, "
                    "arm or add the OBS source. Change it in Console Cast → Consoles & Destinations… → AI Agents.")
    else:
        done.append(f"AI Agents permission: {render.level_title(level)}")
    return _three(done, now, left)


def _three(done: list, now: list, left: list) -> str:
    out = []
    for title, items in (("Already done", done), ("Done now", now), ("Left for you", left)):
        if items:
            out.append(title + "\n" + "\n".join(f"{render.INFO} {i}" for i in items))
    if not left:
        out.append("All set. /stream live when you want to send OBS's output to a destination.")
    return "\n\n".join(out)


def doctor() -> str:
    blocked = _unsupported()
    pf = tools.preflight_result(diagnose=not blocked)
    text = pf["summary"]
    diag = pf.get("diagnosis") or {}
    if diag.get("summary"):
        text += f"\n\nConsole Cast says: {diag['summary']}"
        for f in (diag.get("findings") or [])[:4]:
            text += f"\n{render.WARN} {f.get('problem', '')}\n   → {f.get('fix', '')}"
    return text


def go_live(dest_id: str = "") -> str:
    blocked = _unsupported()
    if blocked:
        return blocked
    listed = tools.run_app("destinations_list", {}, timeout=20)
    if not listed.get("ok"):
        return f"{render.BAD} {listed.get('error')}"
    result = listed.get("result") or {}
    dests = result.get("destinations") or []
    if not dests:
        return ("No destinations are saved yet.\n" + add_help("youtube"))
    if not dest_id:
        if len(dests) == 1:
            dest_id = dests[0].get("id", "")
        else:
            dest_id = _ask("Go live on which destination?", [
                {"value": d.get("id"), "label": d.get("id"), "description": d.get("host", "")} for d in dests]) or ""
    dest = next((d for d in dests if d.get("id") == dest_id), None)
    if not dest:
        return f"No destination '{dest_id}'. Saved: {', '.join(d.get('id', '') for d in dests)}."
    if dest.get("state") in ("connecting", "streaming"):
        return f"{dest_id} is already {dest.get('state')}."
    status = (runtime.info(include=("status",)).get("snapshot") or {}).get("status") or {}
    picture = "" if (status.get("stream") or {}).get("live") else (
        " Note: no picture is arriving from the console yet.")
    steps = "start OBS program output and send it to" if not result.get("obs_program_live") else "send OBS's output to"
    question = (f"Go live on {dest_id} ({dest.get('host', '')})? This will {steps} {dest_id}; that service may go "
                f"live as soon as OBS sends video.{picture}")
    if _ask(question, YES) != "yes":
        return "Not confirmed, so nothing was changed."
    out = []
    if not result.get("obs_program_live"):
        res = tools.run_app("obs_program_start", {}, timeout=45, elicit=_confirmed)
        if not res.get("ok"):
            return f"{render.BAD} OBS program output: {res.get('error')}"
        out.append(f"{render.OK} OBS program output started")
    res = tools.run_app("destination_start", {"id": dest_id}, timeout=45, elicit=_confirmed)
    if not res.get("ok"):
        out.append(f"{render.BAD} {dest_id}: {res.get('error')}")
        return "\n".join(out)
    state = ((res.get("result") or {}).get("destination") or {}).get("state", "connecting")
    out.append(f"{render.OK} {dest_id}: {state}. /stream shows when it is streaming; /stream stop ends it.")
    return "\n".join(out)


def stop(dest_id: str = "") -> str:
    blocked = _unsupported()
    if blocked:
        return blocked
    if dest_id and dest_id.lower() != "all":
        res = tools.run_app("destination_stop", {"id": dest_id}, timeout=30)
        return f"{render.OK} {dest_id} stopped." if res.get("ok") else f"{render.BAD} {res.get('error')}"
    listed = tools.run_app("destinations_list", {}, timeout=20)
    result = listed.get("result") or {}
    running = [d.get("id") for d in result.get("destinations") or []
               if d.get("state") in ("connecting", "streaming", "retrying")]
    if not running and not result.get("obs_program_live"):
        return "Nothing is being sent: no destination is on and OBS program output is off."
    what = ", ".join(running) if running else "OBS program output"
    if _ask(f"End the stream? This stops {what}.", [{"value": "yes", "label": "End stream"},
                                                     {"value": "no", "label": "Keep streaming"}]) != "yes":
        return "Still streaming. Nothing was changed."
    import json

    data = json.loads(tools.handle_end_stream({}))
    lines = [f"{render.OK} Stopped: {', '.join(data.get('destinations_stopped') or []) or 'no destinations'}",
             f"{render.OK} OBS program output: {data.get('obs_program_output')}"]
    lines += [f"{render.BAD} {e}" for e in data.get("errors") or []]
    lines.append("Console Cast stays running and armed. /stream recap for the summary.")
    return "\n".join(lines)


def add_help(dest_id: str) -> str:
    return (f"To save '{dest_id}' without its stream key passing through this chat:\n"
            f"{render.INFO} In Console Cast: Consoles & Destinations… → Local Outputs → Save Destination\n"
            f"{render.INFO} Or in your own terminal: consolecast output save {dest_id} (paste the full URL, then "
            "press Ctrl-D)\n"
            "Please don't paste stream keys here.")
