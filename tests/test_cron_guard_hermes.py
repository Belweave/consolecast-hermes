"""The cron guard against the real Hermes API. Skipped when Hermes is not installed; the Hermes home
is the test's own temporary folder (set by the fake_app fixture)."""

from __future__ import annotations

import json

import pytest


def test_guard_reads_hermes_session_and_config(pkg, fake_app, tmp_path, monkeypatch):
    pytest.importorskip("gateway.session_context")
    pytest.importorskip("hermes_cli.config")
    watch = pkg.watch
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    config = home / "config.yaml"

    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    assert watch.in_cron_session() is False
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    assert watch.in_cron_session() is True

    config.write_text("cron:\n  allow_agent_scheduling: false\n", encoding="utf-8")
    assert watch.agent_scheduling_allowed() is False
    out = json.loads(pkg.tools.handle_notifications({"action": "on"}))
    assert out["ok"] is False and "/stream watch on" in out["error"]
    assert fake_app.ctx.dispatched == []

    config.write_text("cron:\n  allow_agent_scheduling: true\n", encoding="utf-8")
    assert watch.agent_scheduling_allowed() is True
    out = json.loads(pkg.tools.handle_notifications({"action": "on"}))
    assert out["ok"] is True

    config.write_text("cron: {}\n", encoding="utf-8")
    assert watch.agent_scheduling_allowed() is False  # Hermes's default is off
