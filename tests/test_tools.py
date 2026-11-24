from __future__ import annotations

import json


def call(pkg, name, args=None, **kw):
    return json.loads(pkg.tools.handler_for(name)(args or {}, **kw))


def approve_like_hermes(pkg, tool, args, choice="once", task_id="t1", session_id="s1"):
    """What Hermes does around a tool call: pre_tool_call, the approval prompt, post_approval_response."""
    directive = pkg.hooks.pre_tool_call(tool_name=tool, args=args, task_id=task_id, session_id=session_id)
    if directive and directive.get("action") == "approve" and choice is not None:
        pkg.hooks.post_approval_response(pattern_key="plugin_rule:" + directive["rule_key"], choice=choice)
    return directive


def test_status_and_preflight(pkg, fake_app):
    out = call(pkg, "consolecast_status")
    assert out["installed"] and out["version"] == "0.3.2"
    assert "Licence: free week, 3 days left" in out["summary"]
    assert out["status"]["obs"]["program_stream_key"] == "[hidden]"
    pf = call(pkg, "consolecast_preflight", {"diagnose": True})
    assert pf["ready"] is False and "DNS" in pf["summary"]


def test_go_live_needs_a_person(pkg, fake_app):
    args = {"id": "youtube"}
    directive = pkg.hooks.pre_tool_call(tool_name="consolecast_destination_start", args=args, task_id="t1",
                                        session_id="s1")
    assert directive["action"] == "approve" and "youtube" in directive["message"]
    # Hermes skipped its prompt (YOLO / approvals off): nobody answered, so the app's question is declined.
    out = call(pkg, "consolecast_destination_start", args, task_id="t1", session_id="s1")
    assert out["ok"] is False and "nobody confirmed" in out["error"]
    assert fake_app.state()["destinations"][0]["state"] == "stopped"
    assert {"elicitation_answer": "decline"} in fake_app.calls()


def test_go_live_after_a_person_approves(pkg, fake_app):
    args = {"id": "youtube"}
    approve_like_hermes(pkg, "consolecast_destination_start", args, choice="once")
    out = call(pkg, "consolecast_destination_start", args, task_id="t1", session_id="s1")
    assert out["ok"] is True
    assert fake_app.state()["destinations"][0]["state"] == "streaming"
    assert {"elicitation_answer": "accept"} in fake_app.calls()


def test_denied_or_automatic_answers_do_not_count(pkg, fake_app):
    args = {"id": "youtube"}
    approve_like_hermes(pkg, "consolecast_destination_start", args, choice="deny")
    assert call(pkg, "consolecast_destination_start", args, task_id="t1", session_id="s1")["ok"] is False
    directive = pkg.hooks.pre_tool_call(tool_name="consolecast_destination_start", args=args, task_id="t1",
                                        session_id="s1")
    pkg.hooks.post_approval_response(pattern_key="plugin_rule:" + directive["rule_key"], choice="once",
                                     decided_by="aux_llm")
    assert call(pkg, "consolecast_destination_start", args, task_id="t1", session_id="s1")["ok"] is False
    assert fake_app.state()["destinations"][0]["state"] == "stopped"


def test_app_setting_go_live_without_asking_is_respected(pkg, fake_app):
    fake_app.set(allow_live_without_asking=True)
    out = call(pkg, "consolecast_destination_start", {"id": "youtube"}, task_id="t", session_id="s")
    assert out["ok"] is True
    assert not any("elicitation_answer" in c for c in fake_app.calls())


def test_level_too_low_is_explained(pkg, fake_app):
    fake_app.set(level="read")
    out = call(pkg, "consolecast_arm")
    assert out["ok"] is False and "Read only" in out["error"] and "Control" in out["error"]
    assert fake_app.state()["state"] == "armed_waiting"


def test_secret_tools_never_reach_the_app(pkg, fake_app):
    fake_app.set(level="full")
    directive = pkg.hooks.pre_tool_call(tool_name="consolecast_app_call",
                                        args={"tool": "destination_add", "arguments": {"id": "x"}})
    assert directive["action"] == "block"
    out = call(pkg, "consolecast_app_call", {"tool": "destination_add", "arguments": {"id": "x", "stream_key": "k"}})
    assert out["ok"] is False and "never" in out["error"]
    assert not fake_app.called("destination_add")
    guide = call(pkg, "consolecast_destination_add_guide", {"id": "kick"})
    assert "consolecast output save kick" in json.dumps(guide)
    assert "Save Destination" in json.dumps(guide)


def test_app_call_passthrough_and_newer_tools(pkg, fake_app):
    out = call(pkg, "consolecast_app_call", {"tool": "updates_check"})
    assert out["ok"] and out["result"]["current_version"] == "0.3.2"
    directive = pkg.hooks.pre_tool_call(tool_name="consolecast_app_call", args={"tool": "future_publish"})
    assert directive["action"] == "approve"  # open-world, not read-only, unknown to the plugin
    listing = call(pkg, "consolecast_app_tools")
    rows = {r["name"]: r for r in listing["tools"]}
    assert rows["future_publish"]["through_hermes"] == "asks the user first"
    assert rows["status"]["through_hermes"] == "yes"


def test_end_stream_and_recap(pkg, fake_app):
    fake_app.set(live=True, state="live", program_live=True,
                 destinations=[{"id": "youtube", "host": "a.rtmps.youtube.com", "state": "streaming", "attempts": 1}])
    call(pkg, "consolecast_status")  # Hermes notices the live stream
    out = call(pkg, "consolecast_end_stream")
    assert out["destinations_stopped"] == ["youtube"] and out["obs_program_output"] == "stopped"
    fake_app.set(live=False, state="armed_waiting")
    call(pkg, "consolecast_status")  # ... and that it ended
    recap = call(pkg, "consolecast_stream_summary")
    assert "Last stream" in recap["summary"] and "youtube" in recap["summary"]
    assert recap["recent_errors"]


def test_disarm_asks_only_when_live(pkg, fake_app):
    assert pkg.hooks.pre_tool_call(tool_name="consolecast_disarm", args={}) is None
    fake_app.set(live=True, state="live")
    pkg.runtime.clear_cache()
    assert pkg.hooks.pre_tool_call(tool_name="consolecast_disarm", args={})["action"] == "approve"


def test_not_installed_and_windows(pkg, fake_app, monkeypatch):
    monkeypatch.setattr(pkg.runtime, "binary", lambda: None)
    out = call(pkg, "consolecast_arm")
    assert out["ok"] is False and "consolecast.app/download" in out["error"]
    status = call(pkg, "consolecast_status")
    assert status["installed"] is False and "Do not download" in status["install_note"]
    client = pkg.client
    monkeypatch.setattr(client, "detect_platform", lambda: client.PlatformInfo(
        "windows", "Windows", False, "Console Cast for Windows: Coming very soon."))
    assert "Coming very soon" in call(pkg, "consolecast_status")["summary"]
    assert "Coming very soon" in call(pkg, "consolecast_arm")["error"]


def test_cloud_and_account_are_not_reachable(pkg, fake_app):
    fake_app.set(level="full")
    listing = call(pkg, "consolecast_app_tools")
    names = {r["name"] for r in listing["tools"]}
    assert "status" in names and "future_publish" in names
    assert not {n for n in names if "cloud" in n or n.startswith("account_")}
    for tool in ("account_status", "account_sign_in", "cloud_session_start", "cloud_destinations_list",
                 "future_cloud_recap"):
        directive = pkg.hooks.pre_tool_call(tool_name="consolecast_app_call", args={"tool": tool})
        assert directive["action"] == "block" and "Cloud" in directive["message"], tool
        out = call(pkg, "consolecast_app_call", {"tool": tool})
        assert out["ok"] is False and "not available through this plugin" in out["error"], tool
        assert not fake_app.called(tool), tool
    assert pkg.tools.run_app("cloud_session_start", {"minutes": 60})["ok"] is False


def test_preflight_has_no_setup_extras(pkg, fake_app):
    out = call(pkg, "consolecast_preflight", {"diagnose": False})
    assert set(out) == {"ready", "left", "next", "checks", "summary"}
    assert "for_setup" not in pkg.schemas.SCHEMAS["consolecast_preflight"]["parameters"]["properties"]


def cron_run(pkg, monkeypatch, *, cron, allowed=False):
    """Pretend to be (or not be) inside a Hermes cron run, with cron.allow_agent_scheduling on or off."""
    monkeypatch.setattr(pkg.watch, "in_cron_session", lambda: cron)
    monkeypatch.setattr(pkg.watch, "agent_scheduling_allowed", lambda: allowed)


def test_notifications_via_hermes_cron(pkg, fake_app, tmp_path, monkeypatch):
    cron_run(pkg, monkeypatch, cron=False)
    out = call(pkg, "consolecast_notifications", {"action": "on", "every_minutes": 3, "deliver": "telegram"})
    assert out["ok"] and "every 3 min" in out["summary"]
    create = next(a for _n, a in fake_app.ctx.dispatched if a.get("action") == "create")
    assert create == {"action": "create", "name": "consolecast-watch", "schedule": "every 3m",
                      "script": "consolecast-watch.py", "no_agent": True, "deliver": "telegram"}
    launcher = (tmp_path / "home" / "scripts" / "consolecast-watch.py").read_text()
    assert "watcher.py" in launcher and "CONSOLECAST_HERMES_DATA_DIR" in launcher
    assert call(pkg, "consolecast_notifications", {"action": "status"})["on"] is True
    assert call(pkg, "consolecast_notifications", {"action": "off"})["ok"] is True
    assert not (tmp_path / "home" / "scripts" / "consolecast-watch.py").exists()


def test_cron_run_cannot_turn_notifications_on_or_off(pkg, fake_app, tmp_path, monkeypatch):
    launcher = tmp_path / "home" / "scripts" / "consolecast-watch.py"
    cron_run(pkg, monkeypatch, cron=True, allowed=False)
    out = call(pkg, "consolecast_notifications", {"action": "on", "every_minutes": 3})
    assert out["ok"] is False and "/stream watch on" in out["error"] and "allow_agent_scheduling" in out["error"]
    assert fake_app.ctx.dispatched == [] and not launcher.exists()
    fake_app.ctx.cron_jobs.append({"id": "job1", "name": "consolecast-watch", "schedule": "every 2m"})
    out = call(pkg, "consolecast_notifications", {"action": "off"})
    assert out["ok"] is False and "/stream watch off" in out["error"]
    assert fake_app.ctx.dispatched == [] and fake_app.ctx.cron_jobs
    status = call(pkg, "consolecast_notifications", {"action": "status"})
    assert status["ok"] is True and status["on"] is True
    assert [a.get("action") for _n, a in fake_app.ctx.dispatched] == ["list"]


def test_unknown_cron_state_is_refused(pkg, fake_app, monkeypatch):
    cron_run(pkg, monkeypatch, cron=None, allowed=False)  # a Hermes without get_session_env
    out = call(pkg, "consolecast_notifications", {"action": "on"})
    assert out["ok"] is False and fake_app.ctx.dispatched == []


def test_cron_run_may_schedule_when_hermes_allows_it(pkg, fake_app, monkeypatch):
    cron_run(pkg, monkeypatch, cron=True, allowed=True)
    out = call(pkg, "consolecast_notifications", {"action": "on", "every_minutes": 5})
    assert out["ok"] is True and "every 5 min" in out["summary"]
    assert any(a.get("action") == "create" for _n, a in fake_app.ctx.dispatched)
    assert call(pkg, "consolecast_notifications", {"action": "off"})["ok"] is True
    assert not fake_app.ctx.cron_jobs


def test_model_cannot_pick_the_person_path(pkg, fake_app, monkeypatch):
    cron_run(pkg, monkeypatch, cron=True, allowed=False)
    out = call(pkg, "consolecast_notifications", {"action": "on", "by_person": True, "dispatch": "x",
                                                  "run_yourself": True})
    assert out["ok"] is False and fake_app.ctx.dispatched == []
    assert pkg.tools.LOCAL_HANDLERS["consolecast_notifications"] is pkg.tools.handle_notifications
    import inspect

    assert "manage_for_person" not in inspect.getsource(pkg.tools)


def test_approval_prompt_asks_for_once(pkg, fake_app):
    directive = pkg.hooks.pre_tool_call(tool_name="consolecast_destination_start", args={"id": "youtube"})
    assert directive["action"] == "approve" and 'Answer "once"' in directive["message"]
    assert directive["rule_key"].startswith("consolecast:")
