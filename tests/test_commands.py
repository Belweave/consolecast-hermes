from __future__ import annotations


def run(pkg, text):
    return pkg.commands.handle(text)


def test_status_and_help(pkg, fake_app):
    out = run(pkg, "")
    assert out.startswith("Console Cast 0.3.2") and "Destinations: youtube stopped" in out
    assert "/stream live" in run(pkg, "help")
    assert "Unknown" in run(pkg, "frobnicate")


def test_live_needs_a_yes(pkg, fake_app):
    fake_app.ctx.choice = None  # nobody could be asked
    assert "nothing was changed" in run(pkg, "live youtube").lower()
    fake_app.ctx.choice = "no"
    assert "Not confirmed" in run(pkg, "live youtube")
    assert not fake_app.called("destination_start") and not fake_app.called("obs_program_start")


def test_live_with_a_yes(pkg, fake_app):
    fake_app.ctx.choice = "yes"
    out = run(pkg, "live youtube")
    assert "OBS program output started" in out and "youtube: streaming" in out
    assert "a.rtmps.youtube.com" in fake_app.ctx.asked[-1]
    state = fake_app.state()
    assert state["program_live"] and state["destinations"][0]["state"] == "streaming"


def test_live_without_destinations_explains_how_to_add(pkg, fake_app):
    fake_app.set(destinations=[])
    out = run(pkg, "live")
    assert "Local Outputs → Save Destination" in out


def test_stop(pkg, fake_app):
    fake_app.set(program_live=True, destinations=[{"id": "youtube", "host": "h", "state": "streaming"}])
    fake_app.ctx.choice = "no"
    assert "Still streaming" in run(pkg, "stop")
    fake_app.ctx.choice = "yes"
    out = run(pkg, "stop")
    assert "Stopped: youtube" in out and fake_app.state()["program_live"] is False
    assert "Nothing is being sent" in run(pkg, "stop")


def test_setup_is_idempotent(pkg, fake_app):
    fake_app.set(running=False, state="not_running", source_added=False, console_seen=False)
    fake_app.ctx.choice = "ps5"
    first = run(pkg, "setup")
    assert "Started and armed Console Cast" in first
    assert "Added the 'Console Cast' source to OBS" in first
    assert "Primary 192.168.1.20" in first
    second = run(pkg, "setup")
    assert "Done now" not in second  # nothing left to do that Hermes can do
    assert "Console Cast running" not in second or "Running" in second


def test_setup_with_read_only_permission(pkg, fake_app):
    fake_app.set(level="read", running=False, state="not_running")
    fake_app.ctx.choice = None
    out = run(pkg, "setup xbox")
    assert "Read only" in out and "Left for you" in out
    assert fake_app.state()["running"] is False


def test_watch_and_recap(pkg, fake_app):
    assert "off" in run(pkg, "watch status")
    assert "on" in run(pkg, "watch on 5")
    assert "No stream recorded" in run(pkg, "recap")


def test_add_never_asks_for_the_key_here(pkg, fake_app):
    out = run(pkg, "add kick")
    assert "consolecast output save kick" in out and "don't paste" in out


def test_watch_slash_command_works_in_a_cron_run(pkg, fake_app, monkeypatch):
    """The reviewer's rule is for agents; /stream watch is typed by a person and stays as it was."""
    monkeypatch.setattr(pkg.watch, "in_cron_session", lambda: True)
    monkeypatch.setattr(pkg.watch, "agent_scheduling_allowed", lambda: False)
    assert "Stream notifications are on" in run(pkg, "watch on 5")
    assert any(a.get("action") == "create" for _n, a in fake_app.ctx.dispatched)
    assert "off" in run(pkg, "watch off")
    assert not fake_app.ctx.cron_jobs
