from __future__ import annotations

import pytest


def test_classify(pkg):
    classify = pkg.safety.classify
    assert classify("destination_start", {"id": "yt"}).action == "ask"
    assert classify("obs_program_start", {}).action == "ask"
    assert classify("disarm", {}, live=lambda: True).action == "ask"
    assert classify("disarm", {}, live=lambda: False).action == "allow"
    assert classify("disarm", {}, live=lambda: None).action == "ask"  # unknown counts as live
    assert classify("destination_remove", {"id": "yt"}).action == "ask"
    assert classify("status", {}).action == "allow"
    for secret in ("destination_add", "destination_update", "license_activate"):
        assert classify(secret, {}).action == "block"
    assert classify("status", {"note": "rtmp://live.twitch.tv/app/live_1234567_abcdefghijklmnopqrstuv"}).action == "block"


@pytest.mark.parametrize("tool", [
    # every Cloud and account tool in Console Cast 0.3.2 ...
    "account_status", "account_sign_in", "account_sign_out", "cloud_session_status", "cloud_session_start",
    "cloud_session_end", "cloud_console_pair", "cloud_console_unpair", "cloud_destinations_list",
    "cloud_destination_add", "cloud_destination_update", "cloud_destination_remove", "cloud_destination_set_enabled",
    "cloud_direct_link_status", "cloud_direct_link_set", "cloud_direct_link_rotate", "cloud_recordings_list",
    "cloud_recording_delete",
    # ... and names a later version might use
    "cloud", "session_cloud_start", "accounts_list", "sign_in", "signout", "login_device", "recap_cloud",
])
def test_cloud_and_account_tools_are_blocked(pkg, tool):
    decision = pkg.safety.classify(tool, {}, live=lambda: False)
    assert decision.action == "block" and "Cloud" in decision.message


@pytest.mark.parametrize("tool", ["status", "destination_start", "license_status", "updates_check", "logs_tail",
                                  "disarm", "viewer_open", "obs_add_source", "permissions", "wait_for_live"])
def test_local_tools_are_not_mistaken_for_cloud(pkg, tool):
    assert not pkg.safety.is_cloud_tool(tool)


def test_classify_tools_newer_than_the_plugin(pkg):
    classify = pkg.safety.classify
    assert classify("future_publish", {}, annotations={"readOnlyHint": False, "openWorldHint": True}).action == "ask"
    assert classify("future_read", {}, annotations={"readOnlyHint": True}).action == "allow"
    assert classify("future_keyed", {}, input_schema={"properties": {"api_token": {}}}).action == "block"


def test_ledger_only_counts_a_person(pkg):
    ledger = pkg.safety.ApprovalLedger()
    key = pkg.safety.call_key("consolecast_destination_start", {"id": "yt"}, "t", "s")
    rule = ledger.expect(key)
    ledger.resolve("plugin_rule:" + rule, "once")
    assert ledger.consume(key) is True
    assert ledger.consume(key) is False  # single use

    for choice, decided_by in (("deny", None), ("timeout", None), ("cancelled", None), ("smart_approve", "aux_llm"),
                               ("once", "aux_llm")):
        rule = ledger.expect(key)
        ledger.resolve("plugin_rule:" + rule, choice, decided_by)
        assert ledger.consume(key) is False, (choice, decided_by)

    other = pkg.safety.call_key("consolecast_destination_start", {"id": "twitch"}, "t", "s")
    rule = ledger.expect(key)
    ledger.resolve("plugin_rule:" + rule, "always")
    assert ledger.consume(other) is False  # bound to the exact call
    assert ledger.consume(key) is True


def test_every_request_gets_its_own_rule_key(pkg):
    ledger = pkg.safety.ApprovalLedger()
    key = pkg.safety.call_key("consolecast_destination_start", {"id": "yt"})
    assert ledger.expect(key) != ledger.expect(key)


def test_ledger_expires(pkg, monkeypatch):
    ledger = pkg.safety.ApprovalLedger(ttl=10)
    clock = [1000.0]
    monkeypatch.setattr(pkg.safety.time, "monotonic", lambda: clock[0])
    rule = ledger.expect("k")
    ledger.resolve(rule, "once")
    clock[0] += 11
    assert ledger.consume("k") is False


@pytest.mark.parametrize("command,blocked", [
    ('"/Applications/Console Cast.app/Contents/Resources/consolecast" agents token', True),
    ("consolecast agents rotate-token", True),
    ("cat ~/Library/Application\\ Support/Console\\ Cast/agents-token", True),
    ("echo $KEY | consolecast license activate", True),
    ("printf 'rtmp://x/app/k' | consolecast output save youtube", True),
    ("consolecast tool destination_add -", True),
    ("consolecast tool arm", True),
    ("consolecast tool list", True),
    ("consolecast agents level full", True),
    ("consolecast agents live-without-asking on", True),
    ("consolecast account sign-in", True),
    ("consolecast cloud start", True),
    ("consolecast status --json", False),
    ("consolecast agents status", False),
    ("ls -la", False),
])
def test_terminal_guard(pkg, command, blocked):
    assert (pkg.safety.terminal_guard(command) is not None) is blocked
