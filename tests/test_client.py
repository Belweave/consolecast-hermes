from __future__ import annotations

import pytest


def test_handshake_lists_tools_by_level(pkg, fake_app):
    client = pkg.client
    with client.McpSession(fake_app.binary) as s:
        assert s.server_info["version"] == "0.3.2"
        names = {t["name"] for t in s.list_tools()}
    assert "destination_start" in names and "destination_add" not in names
    fake_app.set(level="read")
    with client.McpSession(fake_app.binary) as s:
        names = {t["name"] for t in s.list_tools()}
    assert "status" in names and "arm" not in names


def test_unlisted_tool_raises_tool_not_listed(pkg, fake_app):
    fake_app.set(level="read")
    with pytest.raises(pkg.client.ToolNotListed):
        pkg.client.call_tool(fake_app.binary, "arm")
    assert not any(c.get("call") == "arm" and c.get("ok") for c in fake_app.calls())
    assert fake_app.state()["state"] == "armed_waiting"


def test_elicitation_declined_by_default_and_accepted_on_request(pkg, fake_app):
    client = pkg.client
    res = client.call_tool(fake_app.binary, "destination_start", {"id": "youtube"})
    assert not res.ok and "declined" in res.text
    assert res.asked and "youtube" in res.asked[0]
    assert fake_app.state()["destinations"][0]["state"] == "stopped"
    res = client.call_tool(fake_app.binary, "destination_start", {"id": "youtube"}, elicit=lambda m, s: True)
    assert res.ok and fake_app.state()["destinations"][0]["state"] == "streaming"


def test_snapshot_hides_keys(pkg, fake_app):
    snap = pkg.client.snapshot(fake_app.binary)
    obs = snap["status"]["obs"]
    assert obs["program_stream_key"] == "[hidden]"
    assert obs["source_url"] == "rtmp://127.0.0.1:1935/console"  # local source address stays usable
    assert snap["permissions"]["level"] == "control"


@pytest.mark.parametrize("text,expected", [
    ("rtmps://a.rtmps.youtube.com/live2/abcd-efgh-ijkl", "rtmps://a.rtmps.youtube.com/live2/…"),
    ("rtmps://a.rtmps.youtube.com/live2", "rtmps://a.rtmps.youtube.com/live2"),
    ("srt://ingest.example.com:9000?streamid=SECRET", "srt://ingest.example.com:9000/…"),
    ("rtmp://user:pw@host.example/app", "rtmp://host.example/app/…"),
    ("rtmp://127.0.0.1:1935/console", "rtmp://127.0.0.1:1935/console"),
])
def test_scrub_stream_urls(pkg, text, expected):
    assert pkg.client.scrub(text) == expected


def test_secret_argument_detection(pkg):
    looks = pkg.client.looks_like_secret_argument
    assert looks({"stream_key": "x"})
    assert looks({"url": "rtmp://live.twitch.tv/app/live_123456_abcdefghijklmnopqrstu"})
    assert looks("echo live_123456789_abcdefghijklmnopqrst")
    assert not looks({"id": "youtube"})
    assert not looks({"server": "rtmps://a.rtmps.youtube.com/live2"})
    assert not looks({"stream_key": ""})


def test_find_binary_respects_override_and_reports_missing(pkg, fake_app, tmp_path, monkeypatch):
    client = pkg.client
    assert client.find_binary(fake_app.binary) == fake_app.binary
    monkeypatch.setattr(client, "MAC_BINARIES", ())
    monkeypatch.setattr(client, "LINUX_BINARIES", ())
    monkeypatch.setattr(client.shutil, "which", lambda name: None)
    assert client.find_binary(str(tmp_path / "missing")) is None


def test_child_env_drops_hermes_secrets(pkg, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "nope")
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    monkeypatch.setenv("CONSOLECAST_STATE_DIR", "/x")
    env = pkg.client.child_env()
    assert "OPENAI_API_KEY" not in env and env["CONSOLECAST_STATE_DIR"] == "/x"
    assert not [k for k in env if k.startswith("HERMES_")]  # no YOLO or other Hermes state reaches the app


def test_platforms(pkg, monkeypatch):
    client = pkg.client
    monkeypatch.setattr(client.sys, "platform", "win32")
    plat = client.detect_platform()
    assert not plat.supported and "Coming very soon" in plat.note
    monkeypatch.setattr(client.sys, "platform", "darwin")
    monkeypatch.setattr(client.platform, "machine", lambda: "x86_64")
    assert "Apple Silicon" in client.detect_platform().note
    monkeypatch.setattr(client.sys, "platform", "linux")
    monkeypatch.setattr(client.platform, "machine", lambda: "x86_64")
    assert client.detect_platform().supported
