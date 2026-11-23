from __future__ import annotations

import asyncio
import re
from pathlib import Path

from conftest import FakeCtx

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def manifest_list(field: str) -> list[str]:
    text = (PLUGIN_DIR / "plugin.yaml").read_text()
    block = re.search(rf"^{field}:\n((?:  - .+\n)+)", text, re.MULTILINE)
    return [line.strip()[2:] for line in block.group(1).splitlines()]


def test_register_wires_everything(pkg, fake_app):
    ctx = FakeCtx()
    pkg.register(ctx)
    assert set(ctx.tools) == set(manifest_list("provides_tools")) and len(ctx.tools) == 25
    assert set(ctx.hooks) == set(manifest_list("provides_hooks"))
    assert {t["toolset"] for t in ctx.tools.values()} == {"consolecast"}
    assert set(ctx.commands) == {"stream", "consolecast"}
    assert set(ctx.cli) == {"consolecast"}
    assert set(ctx.skills) == {"setup", "go-live", "troubleshoot", "recap"}
    assert all(p.is_file() for p in ctx.skills.values())
    assert "consolecast.guide" in ctx.sections
    assert ctx.patterns and "consolecast:stream-check" not in ctx.blueprints and "stream-check" in ctx.blueprints
    for schema in (t["schema"] for t in ctx.tools.values()):
        assert schema["description"] and schema["parameters"]["type"] == "object"


def test_tool_descriptions_mention_console_cast_for_tool_search(pkg):
    for name, schema in pkg.schemas.SCHEMAS.items():
        assert name.startswith("consolecast_")
        assert len(schema["description"]) < 700


def test_skill_frontmatter(pkg):
    for skill in (PLUGIN_DIR / "skills").iterdir():
        text = (skill / "SKILL.md").read_text()
        assert text.startswith("---\nname: " + skill.name + "\n")
        assert "platforms: [macos, linux]" in text


def test_reference_provider(pkg, fake_app, monkeypatch):
    import sys
    import types

    mod = types.ModuleType("agent.context_references")

    class Item:
        def __init__(self, text, display="", meta=""):
            self.text, self.meta = text, meta

    class Base:
        pass

    mod.ContextCompletionItem, mod.ContextReferenceProvider = Item, Base
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.context_references", mod)
    provider = pkg.hooks.make_reference_provider()
    assert provider.prefix == "stream"
    items = asyncio.run(provider.autocomplete("re"))
    assert {i.text for i in items} == {"ready", "recap"}
    text = asyncio.run(provider.expand("status"))
    assert text.startswith("Console Cast 0.3.2")


def test_context_injection_only_when_talking_about_the_stream(pkg, fake_app):
    assert pkg.hooks.pre_llm_call(user_message="what's the weather") is None
    out = pkg.hooks.pre_llm_call(user_message="am I live on YouTube yet?")
    assert out["context"].startswith("[Console Cast status")
    fake_app.ctx.settings["context_injection"] = False
    pkg.runtime.clear_cache()
    assert pkg.hooks.pre_llm_call(user_message="am I live?") is None


def test_system_prompt_section_is_bounded(pkg, fake_app):
    text = pkg.hooks.system_prompt_section({})
    assert "consolecast:setup" in text and len(text) <= 1600
    assert "At session start: Console Cast 0.3.2 installed" in text


def test_no_personal_details_in_plugin(pkg):
    for path in PLUGIN_DIR.rglob("*"):
        if path.is_file() and path.suffix in (".py", ".md", ".yaml") and "__pycache__" not in path.parts:
            text = path.read_text(encoding="utf-8")
            emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)) - {"info@belweave.com"}
            assert not {e for e in emails if not e.endswith((".invalid", "example.com", ".example"))}, (path, emails)
