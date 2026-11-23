"""`hermes consolecast ...`: the same checks as /stream, from a terminal.

There is deliberately no command here that takes a key. Stream keys and the licence key go into
Console Cast's own window (or its own CLI), never through Hermes.
"""

from __future__ import annotations

import argparse
from typing import Any

from . import commands, render, runtime


def setup_parser(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="consolecast_command")
    subs.add_parser("status", help="Console Cast status at a glance")
    subs.add_parser("doctor", help="Am I ready to stream? What is wrong and what to do")
    p = subs.add_parser("setup", help="Guided setup (safe to run again)")
    p.add_argument("console", nargs="?", choices=["ps5", "xbox"], help="Your console")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cmd = getattr(args, "consolecast_command", None) or "status"
    if cmd == "status":
        print(render.status_card(runtime.info()))
    elif cmd == "doctor":
        print(commands.doctor())
    elif cmd == "setup":
        print(commands.setup(getattr(args, "console", "") or ""))
    return 0


def register(ctx: Any) -> None:
    ctx.register_cli_command(
        name="consolecast",
        help="Console Cast: status, readiness check and guided setup",
        setup_fn=setup_parser,
        handler_fn=run,
        description="Console Cast for Hermes. Keys are entered in Console Cast itself, never here.",
    )
