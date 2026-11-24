"""Lifecycle hooks, the system prompt section and the @stream: context references."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from . import client, render, runtime, safety, store, tools

logger = logging.getLogger("consolecast")

_STREAM_TALK = re.compile(
    r"\b(console ?cast|consolecast|stream(s|ing|er)?|go(ing)? live|on air|live ?stream|broadcast(ing)?|obs|ps5|"
    r"playstation|xbox|twitch|youtube|kick|destinations?|overlay|bitrate|viewer|free week|recap)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------------------- approvals


def _is_live() -> Optional[bool]:
    data = runtime.info(include=("status",), timeout=8, max_age=5)
    status = (data.get("snapshot") or {}).get("status")
    if not isinstance(status, dict):
        return None
    return store.is_live(status)


def _app_annotations(app_tool: str) -> tuple[dict, dict]:
    try:
        for t in tools.app_tool_list():
            if t.get("name") == app_tool:
                return t.get("annotations") or {}, t.get("inputSchema") or {}
    except Exception as exc:
        logger.debug("consolecast tools/list failed: %s", exc)
    return {}, {}


def pre_tool_call(tool_name: str = "", args: Optional[dict] = None, task_id: str = "", session_id: str = "",
                  **_: Any) -> Optional[dict[str, Any]]:
    """Ask before anything goes on air; refuse anything that would put a key through the model."""
    try:
        args = args if isinstance(args, dict) else {}
        if tool_name.startswith("consolecast_"):
            resolved = tools.resolve_app_call(tool_name, args)
            if resolved is None:
                return None
            app_tool, app_args = resolved
            ann, schema = ({}, {})
            known = (app_tool in safety.ON_AIR | safety.ASK_WHEN_LIVE | safety.DESTRUCTIVE | safety.SECRET_INPUT
                     or safety.is_cloud_tool(app_tool))
            if tool_name == "consolecast_app_call" and not known:
                ann, schema = _app_annotations(app_tool)
            decision = safety.classify(app_tool, app_args, live=_is_live, annotations=ann, input_schema=schema)
            if decision.action == "block":
                return {"action": "block", "message": decision.message}
            if decision.action == "ask":
                rule_key = safety.LEDGER.expect(safety.call_key(tool_name, args, task_id, session_id))
                return {"action": "approve", "message": decision.message + safety.ANSWER_ONCE, "rule_key": rule_key}
            return None
        if tool_name in ("terminal", "execute_code") and runtime.setting("terminal_guard"):
            command = str(args.get("command") or args.get("code") or "")
            message = safety.terminal_guard(command)
            if message:
                return {"action": "block", "message": message}
        return None
    except Exception as exc:  # a raising pre_tool_call blocks the tool; fail closed only for our own tools
        logger.warning("consolecast pre_tool_call failed: %s", exc)
        if tool_name.startswith("consolecast_"):
            return {"action": "block", "message": f"Console Cast safety check failed ({exc}); nothing was done."}
        return None


def post_approval_response(pattern_key: str = "", choice: Any = None, decided_by: Any = None, **_: Any) -> None:
    if isinstance(pattern_key, str) and pattern_key.startswith("plugin_rule:consolecast:"):
        safety.LEDGER.resolve(pattern_key, choice, decided_by)


# ---------------------------------------------------------------------------------------- context


def live_context() -> str:
    data = runtime.info(include=("status", "license_status", "permissions"), timeout=6, max_age=15)
    if not data.get("binary") or data.get("error") or not (data.get("snapshot") or {}).get("status"):
        return ""
    card = render.status_card(data).replace("\n", " | ")
    return f"[Console Cast status, read by the consolecast plugin just now] {card}"


def pre_llm_call(user_message: Any = "", **_: Any) -> Optional[dict[str, str]]:
    try:
        if not runtime.setting("context_injection"):
            return None
        text = user_message if isinstance(user_message, str) else " ".join(
            str(p.get("text", "")) for p in user_message or [] if isinstance(p, dict))
        if not text or not _STREAM_TALK.search(text):
            return None
        if not client.detect_platform().supported:
            return None
        context = live_context()
        return {"context": context} if context else None
    except Exception as exc:
        logger.debug("consolecast pre_llm_call failed: %s", exc)
        return None


GUIDE = """Console Cast plugin (consolecast_* tools, /stream command). Console Cast brings a PS5 or Xbox Series X|S console's built-in Twitch broadcast into OBS Studio on this Mac or Linux computer with no capture card, and can send OBS's output to other services (destinations).
Rules: start with consolecast_status or consolecast_preflight. Going live (consolecast_destination_start, consolecast_obs_output_start) always asks the user; never claim it is live until a tool says so. Never ask for, repeat or store a stream key, licence key or agent token: point the user to consolecast_destination_add_guide or Console Cast's own window. Never download or install Console Cast without asking. What you may do is the user's choice in Console Cast → Consoles & Destinations… → AI Agents; never try to change it. Console Cast Cloud and account actions are not available through this plugin.
Skills: consolecast:setup (first-time setup), consolecast:go-live, consolecast:troubleshoot, consolecast:recap."""


def system_prompt_section(_session: Any = None) -> str:
    try:
        plat = client.detect_platform()
        if not plat.supported:
            return GUIDE + f"\nThis computer: {plat.note}"
        path = runtime.binary()
        if not path:
            return GUIDE + f"\nAt session start: Console Cast is not installed ({client.DOWNLOAD_URL})."
        data = runtime.info(include=("status",), timeout=5, max_age=30)
        status = (data.get("snapshot") or {}).get("status") or {}
        version = data.get("version") or ""
        state = status.get("state_title") or status.get("state") or ("unreachable" if data.get("error") else "?")
        return GUIDE + f"\nAt session start: Console Cast {version} installed, {state}."
    except Exception as exc:
        logger.debug("consolecast prompt section failed: %s", exc)
        return GUIDE


# ---------------------------------------------------------------------------------------- @stream:

REFERENCE_TARGETS = {
    "status": "Live status card",
    "ready": "Am I ready to stream? checklist",
    "destinations": "Saved destinations and their state",
    "license": "Licence or free week",
    "recap": "Last stream summary",
    "log": "Newest log lines",
}


def expand_reference(target: str) -> Optional[str]:
    target = (target or "status").strip().lower()
    if target == "status":
        return render.status_card(runtime.info())
    if target == "ready":
        return tools.preflight_result(diagnose=False)["summary"]
    if target == "destinations":
        res = tools.run_app("destinations_list", {}, timeout=20)
        return (render.destinations_text((res.get("result") or {}).get("destinations") or [])
                if res.get("ok") else res.get("error"))
    if target in ("license", "licence"):
        data = runtime.info(include=("license_status",))
        return "Console Cast licence: " + render.licence_summary(
            (data.get("snapshot") or {}).get("license_status"))["text"]
    if target == "recap":
        return tools.summary_result()["summary"]
    if target == "log":
        res = tools.run_app("logs_tail", {"lines": 40}, timeout=20)
        return "\n".join((res.get("result") or {}).get("lines") or []) if res.get("ok") else res.get("error")
    return None


def make_reference_provider() -> Any:
    from agent.context_references import ContextCompletionItem, ContextReferenceProvider

    class StreamReferences(ContextReferenceProvider):
        prefix = "stream"
        description = "Console Cast: status, ready, destinations, license, recap, log"

        async def autocomplete(self, query: str, *, limit: int = 10) -> list:
            q = (query or "").lower()
            return [ContextCompletionItem(text=k, meta=v) for k, v in REFERENCE_TARGETS.items()
                    if k.startswith(q)][:limit]

        async def expand(self, target: str) -> Optional[str]:
            import asyncio

            return await asyncio.to_thread(expand_reference, target)

    return StreamReferences()
