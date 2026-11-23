"""Who decides what: Hermes's approval gate, Console Cast's own settings, and secrets that never pass a model.

The layering, for anything that puts the user on air (a destination, OBS program output) or removes
something:

1. ``pre_tool_call`` returns ``{"action": "approve"}``, so Hermes asks a person through its normal
   approval prompt (CLI, TUI, Desktop, or a /approve button in Telegram, Discord, Slack...). Each
   request gets its own rule key, so an "always" answer never pre-approves the next go-live.
2. Console Cast asks again through MCP elicitation unless the user turned on "Go live without asking"
   in the app. The plugin answers that question "yes" only when step 1 was answered by a person for
   this exact call (``post_approval_response`` with once/session/always). When Hermes skipped its
   prompt (YOLO, approvals off, cron in approve mode) nobody answered, so the plugin declines and the
   app's own setting decides. The plugin never answers for the user.
3. Tools that take a stream key or licence key are not offered to the model at all, and
   ``terminal``/``execute_code`` commands that would print the agent token or carry a key are blocked.
4. Console Cast Cloud and account actions are not reachable through this plugin at all.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    from . import client
except ImportError:  # pragma: no cover
    import client  # type: ignore[no-redef]

# App tools that put the user on air: always ask.
ON_AIR = {"destination_start", "obs_program_start"}
# Ask only while the console is live (disarm sends it straight to Twitch; quitting cuts the stream).
ASK_WHEN_LIVE = {"disarm", "engine_stop"}
# Remove or revoke something.
DESTRUCTIVE = {"destination_remove", "license_deactivate"}
# Take a secret as input: never through a model.
SECRET_INPUT = {"destination_add", "destination_update", "license_activate"}

# Console Cast Cloud and the Console Cast account (sign-in, sign-out, plan) are not part of this plugin.
# Matched on the tool name, so Cloud or account tools the app adds later are refused too: any name with a
# "cloud" or "account" segment, or a sign-in/sign-out/login/logout verb.
_CLOUD_NAME = re.compile(r"(^|_)(cloud|account|accounts|sign_?in|sign_?out|log_?in|log_?out)(_|$)", re.IGNORECASE)
CLOUD_MESSAGE = ("Console Cast Cloud and Console Cast account actions are not available through this plugin. "
                 "It works with Console Cast on this computer only.")

KEY_ENTRY_HELP = ("Keys never go through Hermes. The user enters them in Console Cast's own window (on a Mac: "
                  "Consoles & Destinations… → Local Outputs → Save Destination for a stream key, and the licence "
                  "window for a licence key), or in their own terminal with Console Cast's CLI "
                  "(`consolecast output save ID` or `consolecast license activate`, which read the value on "
                  "standard input). Never ask the user to paste a key into this chat.")

APPROVAL_TTL_S = 600.0
ACCEPTED_CHOICES = {"once", "session", "always", "approve", "approved", "allow"}


@dataclass(frozen=True)
class Decision:
    action: str  # allow | ask | block
    message: str = ""


def is_cloud_tool(app_tool: str) -> bool:
    return bool(_CLOUD_NAME.search(app_tool or ""))


def secret_tool_message(app_tool: str) -> str:
    return f"'{app_tool}' takes a stream key or licence key. {KEY_ENTRY_HELP}"


def classify(app_tool: str, args: dict[str, Any], *, live: Optional[Callable[[], Optional[bool]]] = None,
             annotations: Optional[dict] = None, input_schema: Optional[dict] = None) -> Decision:
    args = args or {}
    if is_cloud_tool(app_tool):
        return Decision("block", CLOUD_MESSAGE)
    if app_tool in SECRET_INPUT or _schema_takes_secret(input_schema):
        return Decision("block", secret_tool_message(app_tool))
    if client.looks_like_secret_argument(args):
        return Decision("block", "That request carries something that looks like a stream key or credential. "
                                 + KEY_ENTRY_HELP)
    if app_tool in ON_AIR:
        return Decision("ask", go_live_question(app_tool, args))
    if app_tool in ASK_WHEN_LIVE:
        is_live = live() if live else None
        if is_live or is_live is None:
            what = ("Disarm Console Cast while the console is live: its broadcast then goes straight to Twitch"
                    if app_tool == "disarm" else "Quit Console Cast while the console is live: the stream stops")
            return Decision("ask", f"Console Cast: {what}.")
        return Decision("allow")
    if app_tool in DESTRUCTIVE:
        return Decision("ask", f"Console Cast: {app_tool.replace('_', ' ')} {_target(args)}. This cannot be undone.")
    ann = annotations or {}
    if ann and not ann.get("readOnlyHint") and (ann.get("destructiveHint") or ann.get("openWorldHint")):
        # A tool newer than this plugin that changes something outside this computer: ask.
        return Decision("ask", f"Console Cast: run '{app_tool}' {_target(args)}".rstrip() + ".")
    return Decision("allow")


def go_live_question(app_tool: str, args: dict[str, Any]) -> str:
    if app_tool == "destination_start":
        return (f"Console Cast: start sending your stream to the destination '{args.get('id', '?')}'. "
                "That service may go live as soon as OBS sends video.")
    if app_tool == "obs_program_start":
        return "Console Cast: start OBS program output. Any destination that is on will go live with it."
    return f"Console Cast: {app_tool.replace('_', ' ')}."


def _target(args: dict[str, Any]) -> str:
    for key in ("id", "name"):
        if args.get(key):
            return f"'{args[key]}'"
    return ""


def _schema_takes_secret(schema: Optional[dict]) -> bool:
    props = (schema or {}).get("properties") or {}
    return any(re.search(r"(key|token|secret|password|credential)", str(name), re.IGNORECASE) for name in props)


# ---------------------------------------------------------------------------------------- approvals


def call_key(tool_name: str, args: Any, task_id: str = "", session_id: str = "") -> str:
    blob = json.dumps(args or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{task_id}\x00{session_id}\x00{tool_name}\x00{blob}".encode()).hexdigest()


class ApprovalLedger:
    """Remembers which go-live requests a person approved in Hermes, so the app's own question can be
    answered with that person's answer. Single use, short-lived, in memory only."""

    def __init__(self, ttl: float = APPROVAL_TTL_S):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[str, float]] = {}  # rule_key -> (call key, created)
        self._approved: dict[str, float] = {}  # call key -> approved at

    def expect(self, call: str) -> str:
        rule_key = f"consolecast:{uuid.uuid4().hex[:16]}"
        with self._lock:
            self._gc()
            self._pending[rule_key] = (call, time.monotonic())
        return rule_key

    def resolve(self, pattern_key: str, choice: Any, decided_by: Any = None) -> None:
        rule_key = pattern_key.removeprefix("plugin_rule:")
        with self._lock:
            pending = self._pending.pop(rule_key, None)
            if pending is None:
                return
            human = isinstance(choice, str) and choice.strip().lower() in ACCEPTED_CHOICES and not decided_by
            if human:
                self._approved[pending[0]] = time.monotonic()

    def grant(self, call: str) -> None:
        """A person confirmed in a slash command (ctx.ask_choice)."""
        with self._lock:
            self._approved[call] = time.monotonic()

    def consume(self, call: str) -> bool:
        with self._lock:
            self._gc()
            return self._approved.pop(call, None) is not None

    def _gc(self) -> None:
        cutoff = time.monotonic() - self.ttl
        for key in [k for k, (_c, t) in self._pending.items() if t < cutoff]:
            del self._pending[key]
        for key in [k for k, t in self._approved.items() if t < cutoff]:
            del self._approved[key]


LEDGER = ApprovalLedger()

NOT_CONFIRMED = ("Console Cast asks before this goes live, and nobody confirmed it here (Hermes approvals are off "
                 "or were answered automatically for this chat). Nothing was changed. The user can run "
                 "/stream live themselves, or turn on \"Go live without asking\" in Console Cast → Consoles & "
                 "Destinations… → AI Agents.")


# ---------------------------------------------------------------------------------------- terminal guard

_TOKEN_COMMANDS = re.compile(r"consolecast\S*['\"]?\s+agents\s+(token|rotate-token)\b", re.IGNORECASE)
_SETTING_COMMANDS = re.compile(r"consolecast\S*['\"]?\s+agents\s+(on|off|level|live-without-asking)\b", re.IGNORECASE)
_SECRET_FILES = re.compile(r"(agents-token|license\.key|Console Cast/[^\s'\"]*key|\.config/consolecast[^\s'\"]*/"
                           r"(agents-token|license|cloud))", re.IGNORECASE)
_KEY_COMMANDS = re.compile(r"consolecast\S*['\"]?\s+(license\s+activate|output\s+save)\b", re.IGNORECASE)
_CLOUD_COMMANDS = re.compile(r"consolecast\S*['\"]?\s+(cloud|account)\b", re.IGNORECASE)
_TOOL_COMMANDS = re.compile(r"consolecast\S*['\"]?\s+tool\b", re.IGNORECASE)


def terminal_guard(command: str) -> Optional[str]:
    """A block message when a shell command run by the agent would expose a Console Cast secret, change the
    app's AI Agents setting, or get around it; else None. People typing in their own terminal are unaffected."""
    lowered = (command or "").lower()
    if not any(word in lowered for word in ("consolecast", "console cast", "agents-token")):
        return None
    if _TOKEN_COMMANDS.search(command):
        return ("Blocked by the Console Cast plugin: that prints the AI agent token, which must never reach a chat "
                "or a model. The user can copy it from Console Cast → AI Agents themselves if a client needs it.")
    if _SETTING_COMMANDS.search(command):
        return ("Blocked by the Console Cast plugin: what an agent may do is the user's choice in Console Cast → "
                "Consoles & Destinations… → AI Agents. Agents never change it.")
    if _SECRET_FILES.search(command):
        return ("Blocked by the Console Cast plugin: that reads a file holding a Console Cast secret. Nothing here "
                "needs it.")
    if _KEY_COMMANDS.search(command) or client.looks_like_secret_argument(command):
        return "Blocked by the Console Cast plugin: that command carries a stream key or licence key. " + KEY_ENTRY_HELP
    if _CLOUD_COMMANDS.search(command):
        return "Blocked by the Console Cast plugin. " + CLOUD_MESSAGE
    if _TOOL_COMMANDS.search(command):
        return ("Blocked by the Console Cast plugin: `consolecast tool` runs with the permission of the person at the "
                "terminal, not the AI Agents level the user chose. Use the consolecast_* tools instead; they follow "
                "that setting.")
    return None
