"""Console Cast for Hermes Agent.

Console Cast (by Belweave, https://consolecast.app) brings a PS5 or Xbox Series X|S console's built-in
broadcast into OBS Studio on a Mac or Linux computer with no capture card, and sends OBS's output to
several destinations at once. This plugin makes Hermes a stream producer for it: typed tools that wrap
the app's own agent server, /stream in every chat, skills, safety hooks, notifications through Hermes
cron, and `hermes consolecast` for the steps that involve a key.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import cli, commands, hooks, runtime, schemas, tools

logger = logging.getLogger("consolecast")

TOOLSET = "consolecast"
SKILLS_DIR = Path(__file__).resolve().parent / "skills"
TWITCH_KEY_PATTERN = r"live_[0-9]{5,12}_[A-Za-z0-9]{20,40}"


def _supported() -> bool:
    from . import client

    return client.detect_platform().supported


def register(ctx: Any) -> None:
    runtime.CTX = ctx
    runtime.bind_config(lambda name, default=None: ctx.get_config(name, default=default))

    for name in schemas.NAMES:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schemas.SCHEMAS[name],
            handler=tools.handler_for(name),
            check_fn=None if name in tools.ALWAYS_AVAILABLE else _supported,
            emoji="🎮",
        )

    ctx.register_hook("pre_tool_call", hooks.pre_tool_call)
    ctx.register_hook("post_approval_response", hooks.post_approval_response)
    ctx.register_hook("pre_llm_call", hooks.pre_llm_call)

    for command in ("stream", "consolecast"):
        ctx.register_command(command, commands.handle,
                             description="Console Cast: status, setup, go live, stop, doctor, watch, recap",
                             args_hint="[status|setup|doctor|live|stop|destinations|add|watch|recap]")

    cli.register(ctx)

    for child in sorted(SKILLS_DIR.iterdir()):
        if (child / "SKILL.md").is_file():
            ctx.register_skill(child.name, child / "SKILL.md")

    ctx.register_system_prompt_section("consolecast.guide", hooks.system_prompt_section, max_chars=1600)
    ctx.register_context_reference(hooks.make_reference_provider())
    ctx.register_redaction_patterns([TWITCH_KEY_PATTERN])
    ctx.register_automation_blueprint(
        "stream-check",
        title="Stream night check",
        description="Before you stream, Hermes checks Console Cast, the console, OBS and your destinations and "
                    "tells you what is left. It never starts or stops anything.",
        category="general",
        schedule_template="{minute} {hour} * * {dow}",
        prompt_template=("Use the consolecast tools to check whether I am ready to stream tonight "
                         "(consolecast_preflight). Tell me in a few short lines what is ready and what I still need "
                         "to do. Do not start, stop, arm or send anything."),
        slots=[
            {"name": "time", "type": "time", "label": "What time?", "default": "18:30"},
            {"name": "recurrence", "type": "weekdays", "label": "Which days?", "default": "weekends",
             "options": ["everyday", "weekdays", "weekends"]},
            {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
             "options": ["origin", "local"], "strict": False},
        ],
        skills=["consolecast:go-live"],
        tags=["streaming", "console", "obs"],
    )
