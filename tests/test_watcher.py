from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def load_watcher():
    """Import watcher.py the way the cron job runs it: as a script next to client.py and store.py."""
    spec = importlib.util.spec_from_file_location("cc_watcher_under_test", PLUGIN_DIR / "watcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_messages_on_transitions(pkg, fake_app):
    w = load_watcher()
    snap = {"status": {"running": True, "console": {"ip": "192.168.1.30"}, "obs": {"source_added": True}},
            "license_status": {"active": True, "free_week": {"days_left": 5}}}
    lines, state = w.messages({}, snap, [{"kind": "live_started"}], warn_days=2, now=1000.0)
    assert lines == ["● Console Cast: 192.168.1.30 is live. The picture is arriving in OBS."]
    lines, state = w.messages(state, snap, [{"kind": "destination_dropped", "id": "yt", "host": "h"}],
                              warn_days=2, now=1010.0)
    assert "dropped" in lines[0]
    lines, _ = w.messages(state, snap, [], warn_days=2, now=1020.0)
    assert lines == []  # nothing changed, silent tick


def test_free_week_warning_once_per_day(pkg, fake_app):
    w = load_watcher()
    snap = {"status": {"running": True}, "license_status": {"active": True, "free_week": {"days_left": 2}}}
    lines, state = w.messages({}, snap, [], warn_days=2, now=1.0)
    assert "2 days left in your free week" in lines[0]
    lines, state = w.messages(state, snap, [], warn_days=2, now=2.0)
    assert lines == []
    snap["license_status"]["free_week"] = {"days_left": 0, "ended": True}
    lines, state = w.messages(state, snap, [], warn_days=2, now=3.0)
    assert "free week has ended" in lines[0]


def test_run_against_fake_app(pkg, fake_app, capsys, monkeypatch):
    w = load_watcher()
    monkeypatch.setattr(w.client, "detect_platform", lambda: w.client.PlatformInfo("mac", "Mac", True))
    assert w.run(fake_app.binary) == 0
    assert capsys.readouterr().out == ""  # not live: silent
    fake_app.set(live=True, state="live")
    w.run(fake_app.binary)
    assert "is live" in capsys.readouterr().out
    fake_app.set(live=False, state="armed_waiting")
    w.run(fake_app.binary)
    assert "stream ended" in capsys.readouterr().out
    # Clean up the bare-name imports watcher.py made, so other tests keep the packaged modules.
    for name in ("client", "render", "store"):
        sys.modules.pop(name, None)
