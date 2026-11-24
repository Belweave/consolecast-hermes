"""Tool schemas: what the model reads. Every tool is in the `consolecast` toolset."""

from __future__ import annotations

from typing import Any

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def _schema(name: str, description: str, properties: dict[str, Any] | None = None,
            required: list[str] | None = None) -> dict[str, Any]:
    params = {"type": "object", "properties": properties or {}, "required": required or []}
    return {"name": name, "description": description, "parameters": params}


DEST_ID = {"type": "string", "description": "Destination ID as shown by consolecast_destinations (e.g. 'youtube')."}

SCHEMAS: dict[str, dict[str, Any]] = {s["name"]: s for s in [
    _schema(
        "consolecast_status",
        "Console Cast (PS5/Xbox broadcast into OBS, no capture card) at a glance: whether it is installed and "
        "running, its version, the stream state (LIVE, armed and waiting, pass-through), console, OBS source and "
        "program output, destinations, the AI Agents permission level and the licence or free week. Use this first "
        "whenever the user asks about their stream or Console Cast. Read only."),
    _schema(
        "consolecast_preflight",
        "Am I ready to stream? A checklist (installed, licence, running, armed, console found, picture arriving, OBS "
        "WebSocket and source, destinations, permission) with the one next step. Read only.",
        {"diagnose": {"type": "boolean", "description": "Also run Console Cast's diagnosis (adds a DNS self "
                                                         "test; a few seconds slower). Default true."}}),
    _schema(
        "consolecast_start",
        "Start Console Cast's engine (and arm it by default so the console's broadcast comes to this computer). Not "
        "on air: nothing is sent anywhere. Needs the Control permission in Console Cast → AI Agents.",
        {"armed": {"type": "boolean", "description": "Arm after starting (default true)."}}),
    _schema(
        "consolecast_stop",
        "Quit Console Cast. The console loses its DNS until Console Cast runs again. Hermes asks the user first "
        "when the console is live."),
    _schema(
        "consolecast_arm",
        "Arm Console Cast: redirect the console's Twitch broadcast to this computer (into OBS and the Viewer) "
        "instead of Twitch. Not on air."),
    _schema(
        "consolecast_disarm",
        "Disarm (pass-through): the console streams straight to Twitch again. If the console is live this puts "
        "it on Twitch, so Hermes asks the user first."),
    _schema(
        "consolecast_console_setup",
        "The exact DNS values and console menus for a PS5 or Xbox Series X|S, from Console Cast. Give the user "
        "the menu path and both DNS values exactly as returned. Read only.",
        {"console": {"type": "string", "enum": ["ps5", "xbox"], "description": "Which console."}}, ["console"]),
    _schema(
        "consolecast_obs_add_source",
        "Add or refresh the 'Console Cast' source in OBS's current scene. OBS must be open with its WebSocket "
        "server on. Not on air.",
        {"mode": {"type": "string", "enum": ["media", "webrtc"],
                  "description": "media (default, Media Source) or webrtc (Browser Source, lowest latency)."}}),
    _schema(
        "consolecast_obs_setup_scene",
        "Build an OBS scene with the console feed and an overlay on top, mute local audio and put it in Program. "
        "Not on air by itself.",
        {"scene": {"type": "string", "description": "Scene name (default 'Console Cast Live')."},
         "mode": {"type": "string", "enum": ["media", "webrtc"]},
         "overlay": {"type": "string", "description": "Absolute path of a PNG overlay, empty for the bundled one, "
                                                      "or 'none'."}}),
    _schema(
        "consolecast_obs_output_start",
        "Start OBS program output into Console Cast so destinations receive it. ON AIR: any destination that is on "
        "goes live. Hermes always asks the user first.",
        {"via": {"type": "string", "enum": ["rtmp", "whip"], "description": "Default rtmp."}}),
    _schema(
        "consolecast_obs_output_stop",
        "Stop OBS program output and restore OBS's own stream settings. Safe; never asks."),
    _schema(
        "consolecast_destinations",
        "List saved destinations (other streaming services that receive OBS's output) with their host and state "
        "(stopped, connecting, streaming, retrying). Stream keys are never shown. Read only."),
    _schema(
        "consolecast_destination_add_guide",
        "How the user saves a new destination (YouTube, Kick, Twitch, any RTMP/RTMPS/SRT service) without a stream "
        "key ever passing through this chat. Never ask the user to paste a stream key; call this instead.",
        {"id": {"type": "string", "description": "Short ID for the destination, e.g. 'youtube'."},
         "service": {"type": "string", "description": "Service name if known, e.g. 'YouTube'."}}),
    _schema(
        "consolecast_destination_start",
        "Start sending OBS's program output to one saved destination. ON AIR: the service may go live. Hermes "
        "always asks the user first, and Console Cast may ask too.",
        {"id": DEST_ID}, ["id"]),
    _schema(
        "consolecast_destination_stop",
        "Stop sending to one destination. Safe; never asks.", {"id": DEST_ID}, ["id"]),
    _schema(
        "consolecast_end_stream",
        "End the stream: stop every running destination, then OBS program output. Leaves Console Cast running and "
        "armed. Safe; never asks."),
    _schema(
        "consolecast_wait_for_live",
        "Wait until the console's picture arrives (the user has started a Twitch broadcast on the console). Read "
        "only.",
        {"timeout_seconds": {"type": "integer", "minimum": 5, "maximum": 600,
                             "description": "How long to wait (default 120)."}}),
    _schema(
        "consolecast_diagnose",
        "What is wrong and what to do, from Console Cast itself (DNS, console, OBS, network). Follow its fixes "
        "before changing anything. Read only.",
        {"dns_self_test": {"type": "boolean", "description": "Run the DNS self test (default true)."}}),
    _schema(
        "consolecast_license",
        "Licence status: active subscription, or the free week with the days left. Never asks for or shows a key. "
        "Read only."),
    _schema(
        "consolecast_viewer",
        "Open the Console Cast Viewer (the live picture with audio, for Discord screen share or window capture).",
        {"browser": {"type": "boolean", "description": "Open in the browser instead of the app window."}}),
    _schema(
        "consolecast_logs",
        "Newest Console Cast log lines, for troubleshooting. Read only.",
        {"lines": {"type": "integer", "minimum": 1, "maximum": 300, "description": "Default 60."},
         "tag": {"type": "string", "enum": ["cc", "dns", "obs", "err", "mtx"]},
         "contains": {"type": "string", "description": "Only lines containing this text."}}),
    _schema(
        "consolecast_stream_summary",
        "After-stream summary: when the last stream went live and ended (as Hermes noticed it), how long it ran, "
        "destinations used, drops and reconnects, peak bitrate, warnings and recent errors. Read only."),
    _schema(
        "consolecast_app_tools",
        "Every action Console Cast offers agents right now at the user's permission level, including ones newer "
        "than this plugin (Console Cast Cloud and account actions excluded). Use with consolecast_app_call. Read "
        "only."),
    _schema(
        "consolecast_app_call",
        "Run one Console Cast action by name (from consolecast_app_tools) with JSON arguments, for anything the "
        "other consolecast_* tools do not cover. The same rules apply: going live asks the user first, and actions "
        "that take a stream key or licence key are refused (the user enters keys in Console Cast itself), and "
        "Console Cast Cloud and account actions are not available.",
        {"tool": {"type": "string", "description": "Console Cast tool name, e.g. 'updates_check'."},
         "arguments": {"type": "object", "description": "Arguments for that tool.", "additionalProperties": True}},
        ["tool"]),
    _schema(
        "consolecast_notifications",
        "Turn on, turn off or check stream notifications: a no-LLM Hermes cron job that checks Console Cast every "
        "few minutes and messages the user (in this chat, or Telegram/Discord/... via 'deliver') when the console "
        "goes live or ends, a destination drops or recovers, or the free week is about to end. Only on the user's "
        "request. In a scheduled (cron) run, on and off are refused unless Hermes's cron.allow_agent_scheduling "
        "is on; the user runs /stream watch on|off instead.",
        {"action": {"type": "string", "enum": ["on", "off", "status"]},
         "every_minutes": {"type": "integer", "minimum": 1, "maximum": 60, "description": "Default 2."},
         "deliver": {"type": "string", "description": "Hermes cron delivery target, e.g. 'origin' (default, this "
                                                      "chat), 'telegram', 'discord:#streams', 'all'."}},
        ["action"]),
]}

NAMES = list(SCHEMAS)
