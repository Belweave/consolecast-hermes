#!/usr/bin/env python3
"""A stand-in for the `consolecast` binary, for tests: `fake_consolecast.py mcp` speaks MCP over stdio
like the real `consolecast mcp` (permission levels, unlisted tools, confirmation through elicitation),
and `fake_consolecast.py version` prints a version.

State lives in the JSON file named by FAKE_CC_STATE; every tool call is appended to FAKE_CC_LOG.
"""

from __future__ import annotations

import json
import os
import sys

LEVELS = {"read": 0, "control": 1, "full": 2}
TOOLS = {  # name: (level, readOnly, destructive, openWorld)
    "status": ("read", True, False, False), "diagnose": ("read", True, False, False),
    "console_setup_guide": ("read", True, False, False), "wait_for_live": ("read", True, False, False),
    "destinations_list": ("read", True, False, False), "license_status": ("read", True, False, False),
    "updates_check": ("read", True, False, True), "logs_tail": ("read", True, False, False),
    "permissions": ("read", True, False, False),
    "engine_start": ("control", False, False, False), "engine_stop": ("control", False, True, False),
    "arm": ("control", False, False, False), "disarm": ("control", False, False, True),
    "obs_add_source": ("control", False, False, False), "obs_program_start": ("control", False, False, False),
    "obs_program_stop": ("control", False, False, False), "destination_start": ("control", False, False, True),
    "destination_stop": ("control", False, False, True), "viewer_open": ("control", False, False, False),
    "destination_add": ("full", False, False, False), "destination_remove": ("full", False, True, False),
    "future_publish": ("control", False, False, True),
    "account_status": ("read", True, False, True), "account_sign_in": ("full", False, False, True),
    "cloud_session_start": ("control", False, False, True), "cloud_destinations_list": ("read", True, False, True),
    "future_cloud_recap": ("read", True, False, True),
}
SCHEMAS = {"destination_add": {"type": "object", "properties": {"id": {"type": "string"},
                                                                  "stream_key": {"type": "string"}}}}

STATE_PATH = os.environ.get("FAKE_CC_STATE", "")
LOG_PATH = os.environ.get("FAKE_CC_LOG", "")


def load() -> dict:
    with open(STATE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def save(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def log(entry: dict) -> None:
    if LOG_PATH:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def status_of(s: dict) -> dict:
    return {"running": s["running"], "state": s["state"], "state_title": s["state"].replace("_", " ").title(),
            "console": {"seen": s.get("console_seen", False), "ip": "192.168.1.30"},
            "console_dns": {"primary": "192.168.1.20", "secondary": "0.0.0.0"},
            "stream": {"live": s.get("live", False), "bitrate_kbps": 6200 if s.get("live") else 0, "tracks": []},
            "obs": {"source_name": "Console Cast", "source_url": "rtmp://127.0.0.1:1935/console",
                    "websocket_enabled": s.get("obs_ws", True), "source_added": s.get("source_added", False),
                    "program_live": s.get("program_live", False), "program_server": "rtmp://127.0.0.1:1935",
                    "program_stream_key": "obsout"},
            "viewer": {"url": "http://127.0.0.1:8889/console-web", "state": "waiting", "live": False},
            "destinations": s.get("destinations", []), "warnings": [], "permission": s["level"],
            "allow_live_without_asking": s.get("allow_live_without_asking", False), "app_attached": True,
            "version": "0.3.2"}


def confirm(s: dict, question: str, caps: dict) -> str | None:
    """None when confirmed; else the refusal text (same wording as the real app)."""
    if s.get("allow_live_without_asking"):
        return None
    if "elicitation" not in caps:
        return question + " This needs the user's confirmation, and this MCP client cannot ask for it."
    send({"jsonrpc": "2.0", "id": "elicit-1", "method": "elicitation/create",
          "params": {"message": "Console Cast: " + question,
                     "requestedSchema": {"type": "object", "properties": {"confirm": {"type": "boolean"}}}}})
    while True:
        line = sys.stdin.readline()
        if not line:
            return "client went away"
        msg = json.loads(line)
        if msg.get("id") == "elicit-1":
            res = msg.get("result") or {}
            log({"elicitation_answer": res.get("action")})
            if res.get("action") == "accept" and (res.get("content") or {}).get("confirm") is True:
                return None
            return "the user declined; nothing was changed"


def call(name: str, args: dict, caps: dict) -> tuple[bool, object]:
    s = load()
    dest = next((d for d in s.get("destinations", []) if d["id"] == args.get("id")), None)
    if name == "status":
        return True, status_of(s)
    if name == "permissions":
        allowed = [t for t, spec in TOOLS.items() if LEVELS[spec[0]] <= LEVELS[s["level"]]]
        return True, {"level": s["level"], "allow_live_without_asking": s.get("allow_live_without_asking", False),
                      "allowed_tools": allowed,
                      "tools_needing_higher_level": [f"{t} ({spec[0].title()})" for t, spec in TOOLS.items()
                                                     if t not in allowed], "transport": "stdio"}
    if name == "license_status":
        return True, s.get("license", {"active": True, "required": True,
                                        "free_week": {"days_left": 3, "ended": False}})
    if name == "diagnose":
        return True, {"ready_to_stream": False, "summary": "No device has used Console Cast DNS.",
                      "findings": [{"code": "no_dns_queries", "severity": "blocker",
                                    "problem": "No device has used Console Cast DNS.",
                                    "fix": "Set the console's Primary DNS to 192.168.1.20."}]}
    if name == "console_setup_guide":
        return True, {"console": args.get("console"), "name": "PS5", "primary_dns": "192.168.1.20",
                      "secondary_dns": "0.0.0.0", "dns_menu": "Settings → Network", "broadcast_menu": "Create",
                      "steps": [], "notes": []}
    if name == "destinations_list":
        return True, {"destinations": s.get("destinations", []), "obs_program_live": s.get("program_live", False),
                      "max_destinations": 4}
    if name == "engine_start":
        s.update(running=True, state="armed_waiting" if args.get("armed", True) else "passthrough")
    elif name == "arm":
        s["state"] = "armed_waiting"
    elif name == "disarm":
        if s.get("live"):
            refusal = confirm(s, "Disarm while live: the broadcast goes straight to Twitch.", caps)
            if refusal:
                return False, refusal
        s["state"] = "passthrough"
    elif name == "obs_program_start":
        if any(d["state"] == "streaming" for d in s.get("destinations", [])):
            refusal = confirm(s, "Start OBS program output while a destination is running.", caps)
            if refusal:
                return False, refusal
        s["program_live"] = True
    elif name == "obs_program_stop":
        s["program_live"] = False
    elif name == "destination_start":
        if dest is None:
            return False, f"no destination {args.get('id')!r}"
        refusal = confirm(s, f"Start sending OBS program output to {dest['id']} ({dest['host']}).", caps)
        if refusal:
            return False, refusal
        dest.update(state="streaming", attempts=1)
    elif name == "destination_stop":
        if dest is None:
            return False, f"no destination {args.get('id')!r}"
        dest["state"] = "stopped"
    elif name == "wait_for_live":
        return True, {"live": s.get("live", False), "waited_seconds": 0.1, "status": status_of(s)}
    elif name == "logs_tail":
        return True, {"lines": ["20:01:29 err  example error line"]}
    elif name == "updates_check":
        return True, {"current_version": "0.3.2", "latest_version": "0.3.2", "update_available": False}
    elif name == "obs_add_source":
        s["source_added"] = True
        save(s)
        return True, {"ok": True, "scene": "Scene", "mode": args.get("mode", "media")}
    elif name == "viewer_open":
        return True, {"opened": "window", "url": "http://127.0.0.1:8889/console-web", "state": "waiting"}
    elif name == "future_publish":
        return True, {"ok": True}
    else:
        return False, f"{name} is not implemented in the fake"
    save(s)
    if name in ("destination_start", "destination_stop"):
        return True, {"ok": True, "destination": dest}
    return True, status_of(s)


def serve() -> int:
    caps: dict = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        method, rid = msg.get("method"), msg.get("id")
        if rid is None:
            continue
        if method == "initialize":
            caps = (msg.get("params") or {}).get("capabilities") or {}
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                "serverInfo": {"name": "console-cast", "version": "0.3.2"}}})
        elif method == "tools/list":
            level = load()["level"]
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": n, "title": n.replace("_", " "), "description": f"Fake {n}. More.",
                 "inputSchema": SCHEMAS.get(n, {"type": "object", "properties": {}}),
                 "annotations": {"readOnlyHint": ro, "destructiveHint": de, "openWorldHint": ow},
                 "_meta": {"app.consolecast/permission": lvl}}
                for n, (lvl, ro, de, ow) in TOOLS.items() if LEVELS[lvl] <= LEVELS[level]]}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            name, args = p.get("name"), p.get("arguments") or {}
            spec = TOOLS.get(name)
            log({"call": name, "arguments": args})
            if spec is None or LEVELS[spec[0]] > LEVELS[load()["level"]]:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f'unknown tool "{name}"'}})
                continue
            ok, out = call(name, args, caps)
            if ok:
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out}})
            else:
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": str(out)}], "isError": True}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no"}})
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "version":
        print("0.3.2")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        sys.exit(serve())
    print("usage: fake_consolecast.py mcp|version", file=sys.stderr)
    sys.exit(2)
