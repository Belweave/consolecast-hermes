"""Test fixtures. The plugin is loaded as the package `consolecast_plugin` (its folder name, `hermes`,
would clash with Hermes itself). Nothing here needs Hermes or the real Console Cast."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
FAKE = Path(__file__).resolve().parent / "fake_consolecast.py"


def _stub_hermes_context_references() -> None:
    """register() builds an @stream: provider on Hermes's ContextReferenceProvider; outside Hermes, stub it."""
    try:
        import agent.context_references
        return
    except ImportError:
        pass
    import types

    class ContextCompletionItem:
        def __init__(self, text, display="", meta=""):
            self.text, self.display, self.meta = text, display or text, meta

    class ContextReferenceProvider:
        prefix = ""

    agent = types.ModuleType("agent")
    refs = types.ModuleType("agent.context_references")
    refs.ContextCompletionItem, refs.ContextReferenceProvider = ContextCompletionItem, ContextReferenceProvider
    agent.context_references = refs
    sys.modules.setdefault("agent", agent)
    sys.modules.setdefault("agent.context_references", refs)


_stub_hermes_context_references()


def _load_package():
    if "consolecast_plugin" in sys.modules:
        return sys.modules["consolecast_plugin"]
    spec = importlib.util.spec_from_file_location("consolecast_plugin", PLUGIN_DIR / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["consolecast_plugin"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def pkg():
    return _load_package()


DEFAULT_STATE: dict[str, Any] = {
    "level": "control", "running": True, "state": "armed_waiting", "live": False, "console_seen": True,
    "source_added": True, "obs_ws": True, "program_live": False, "allow_live_without_asking": False,
    "destinations": [{"id": "youtube", "host": "a.rtmps.youtube.com", "state": "stopped", "attempts": 0}],
    "license": {"active": True, "required": True,
                "free_week": {"days_left": 3, "ended": False, "started_at": "x", "ends_at": "y"}},
}


class FakeApp:
    def __init__(self, root: Path):
        self.state_path = root / "state.json"
        self.log_path = root / "calls.jsonl"
        self.binary = str(root / "consolecast")
        self.set(**DEFAULT_STATE)

    def set(self, **changes: Any) -> None:
        state = self.state() if self.state_path.exists() else {}
        state.update(json.loads(json.dumps(changes)))
        self.state_path.write_text(json.dumps(state))

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def calls(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line.strip()]

    def called(self, name: str) -> bool:
        return any(c.get("call") == name for c in self.calls())


class FakeCtx:
    """Records what register(ctx) asks Hermes to do."""

    def __init__(self, settings: dict | None = None, choice: Any = None):
        self.settings = settings or {}
        self.choice = choice
        self.asked: list[str] = []
        self.tools: dict[str, dict] = {}
        self.hooks: dict[str, list] = {}
        self.commands: dict[str, dict] = {}
        self.cli: dict[str, dict] = {}
        self.skills: dict[str, Path] = {}
        self.sections: dict[str, Any] = {}
        self.references: list = []
        self.patterns: list = []
        self.blueprints: dict[str, dict] = {}
        self.dispatched: list[tuple[str, dict]] = []
        self.cron_jobs: list[dict] = []

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_tool(self, name, toolset, schema, handler, check_fn=None, **kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, "check_fn": check_fn}

    def register_hook(self, name, cb, **kw):
        self.hooks.setdefault(name, []).append(cb)

    def register_command(self, name, handler, description="", args_hint="", **kw):
        self.commands[name] = {"handler": handler, "description": description}

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = {"setup_fn": setup_fn, "handler_fn": handler_fn}

    def register_skill(self, name, path, **kw):
        self.skills[name] = Path(path)

    def register_system_prompt_section(self, sid, content, **kw):
        self.sections[sid] = content

    def register_context_reference(self, provider):
        self.references.append(provider)

    def register_redaction_patterns(self, patterns):
        self.patterns.extend(patterns)
        return len(patterns)

    def register_automation_blueprint(self, key, **kw):
        self.blueprints[key] = kw

    def ask_choice(self, question, choices):
        self.asked.append(question)
        return self.choice

    def dispatch_tool(self, name, args, **kw):
        self.dispatched.append((name, args))
        if name != "cronjob_manage":
            return json.dumps({"error": "unexpected"})
        action = args.get("action")
        if action == "list":
            return json.dumps({"success": True, "jobs": self.cron_jobs})
        if action == "create":
            job = {"id": "job1", "name": args["name"], "schedule": args["schedule"], "deliver": args.get("deliver", "origin")}
            self.cron_jobs.append(job)
            return json.dumps({"success": True, "job_id": "job1", "deliver": job["deliver"]})
        if action == "update":
            return json.dumps({"success": True, "job_id": args["job_id"]})
        if action == "remove":
            self.cron_jobs = [j for j in self.cron_jobs if j["id"] != args["job_id"]]
            return json.dumps({"success": True})
        return json.dumps({"error": "bad action"})


@pytest.fixture
def fake_app(pkg, tmp_path, monkeypatch):
    app = FakeApp(tmp_path)
    exe = Path(app.binary)
    # The plugin hands consolecast a filtered environment, so the fake's paths are baked into its launcher.
    exe.write_text(f"#!/bin/sh\nexport FAKE_CC_STATE='{app.state_path}' FAKE_CC_LOG='{app.log_path}'\n"
                   f"exec '{sys.executable}' '{FAKE}' \"$@\"\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("FAKE_CC_STATE", str(app.state_path))
    monkeypatch.setenv("FAKE_CC_LOG", str(app.log_path))
    monkeypatch.setenv("CONSOLECAST_HERMES_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    client = sys.modules["consolecast_plugin.client"]
    monkeypatch.setattr(client, "detect_platform",
                        lambda: client.PlatformInfo("mac", "Mac (Apple Silicon)", True))
    runtime = sys.modules["consolecast_plugin.runtime"]
    ctx = FakeCtx(settings={"binary": app.binary})
    runtime.CTX = ctx
    runtime.bind_config(ctx.get_config)
    runtime.clear_cache()
    tools = sys.modules["consolecast_plugin.tools"]
    tools._TOOLS_CACHE.update(at=0.0, tools=None)
    safety = sys.modules["consolecast_plugin.safety"]
    safety.LEDGER = safety.ApprovalLedger()
    app.ctx = ctx
    yield app
    runtime.CTX = None
    runtime.bind_config(None)
    runtime.clear_cache()


def pytest_configure(config):
    os.environ.setdefault("CONSOLECAST_HERMES_DATA_DIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "cc-test-data"))
