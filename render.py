"""Readiness checks and compact text that reads well in a terminal and in Telegram/Discord/Slack.

Plain text with a few symbols; no tables, no Markdown that a chat adapter might mangle.
"""

from __future__ import annotations

from typing import Any, Optional

try:  # package import inside Hermes; plain import for the standalone watcher and tests
    from . import client
except ImportError:  # pragma: no cover
    import client  # type: ignore[no-redef]

OK, BAD, WARN, INFO = "✓", "✗", "!", "•"

LEVELS = {"read": "Read only", "control": "Control", "full": "Full"}


def level_title(level: str) -> str:
    return LEVELS.get(str(level or "").lower(), str(level or "unknown"))


# ---------------------------------------------------------------------------------------- licence


def licence_summary(lic: Optional[dict]) -> dict[str, Any]:
    """Normalise license_status into {kind, text, days_left, purchased}."""
    if not isinstance(lic, dict):
        return {"kind": "unknown", "text": "unknown", "days_left": None, "purchased": False}
    week = lic.get("free_week") if isinstance(lic.get("free_week"), dict) else None
    active = bool(lic.get("active"))
    if not lic.get("required", True):
        return {"kind": "not_required", "text": "no licence needed on this build", "days_left": None,
                "purchased": False}
    if active and not week:
        plan = lic.get("plan") or "subscription"
        text = f"active ({plan})"
        if lic.get("expires_at"):
            text += f", renews or ends {str(lic['expires_at'])[:10]}"
        return {"kind": "active", "text": text, "days_left": None, "purchased": True}
    if week:
        days = week.get("days_left")
        if week.get("ended"):
            return {"kind": "free_week_ended", "text": "free week ended; a subscription is needed",
                    "days_left": 0, "purchased": False}
        if days is not None:
            unit = "day" if int(days) == 1 else "days"
            return {"kind": "free_week", "text": f"free week, {days} {unit} left", "days_left": int(days),
                    "purchased": False}
        return {"kind": "free_week", "text": "free week (not started yet)",
                "days_left": 7, "purchased": False}
    return {"kind": "inactive", "text": "not activated",
            "days_left": None, "purchased": False}


# ---------------------------------------------------------------------------------------- status


def _dest_line(dests: list[dict]) -> str:
    if not dests:
        return "none saved"
    return " · ".join(f"{d.get('id', '?')} {d.get('state', '?')}" for d in dests)


def status_card(info: dict[str, Any]) -> str:
    """info: {platform, binary, version, snapshot|error}."""
    plat: client.PlatformInfo = info["platform"]
    if not plat.supported:
        return f"Console Cast · {plat.label}\n{plat.note}"
    if not info.get("binary"):
        return ("Console Cast is not installed on this computer.\n"
                f"Get it at {client.DOWNLOAD_URL} (free for 7 days, no account). "
                "I will not download or install anything without asking you.")
    snap = info.get("snapshot") or {}
    st = snap.get("status") or {}
    head = f"Console Cast {info.get('version') or snap.get('server_version') or ''} · {plat.label}".replace("  ", " ")
    if info.get("error"):
        return f"{head}\n{BAD} {info['error']}"
    lines = [head]
    if not st:
        lines.append(f"{BAD} Status unavailable: {(snap.get('errors') or {}).get('status', 'no answer')}")
        return "\n".join(lines)
    state_title = st.get("state_title") or st.get("state") or "unknown"
    if not st.get("running"):
        lines.append(f"○ {state_title}")
    else:
        live = (st.get("stream") or {}).get("live")
        mark = "● LIVE" if live else "○"
        bits = [f"{mark} {state_title}" if not live else mark]
        console = st.get("console") or {}
        if console.get("seen"):
            bits.append(f"console {console.get('ip') or 'seen'}")
        kbps = (st.get("stream") or {}).get("bitrate_kbps")
        if live and kbps:
            bits.append(f"{int(kbps):,} kbps")
        lines.append(" · ".join(bits))
        obs = st.get("obs") or {}
        obs_bits = ["source added" if obs.get("source_added") else "source not added",
                    "program output on" if obs.get("program_live") else "program output off"]
        if not obs.get("websocket_enabled"):
            obs_bits.append("WebSocket off")
        lines.append("OBS: " + " · ".join(obs_bits))
        lines.append("Destinations: " + _dest_line(st.get("destinations") or []))
    perm = snap.get("permissions") or {}
    level = perm.get("level") or st.get("permission")
    if level:
        asks = "going live without asking" if (perm.get("allow_live_without_asking")
                                                 or st.get("allow_live_without_asking")) else "going live asks first"
        lines.append(f"Agents: {level_title(level)} · {asks}")
    lic = licence_summary(snap.get("license_status"))
    if lic["kind"] != "unknown":
        lines.append(f"Licence: {lic['text']}")
    for w in (st.get("warnings") or [])[:3]:
        if (w or {}).get("code") != "not_running":
            lines.append(f"{WARN} {w.get('message', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------- preflight


def preflight(info: dict[str, Any], diagnosis: Optional[dict] = None) -> dict[str, Any]:
    """Am I ready to stream? A checklist with one next action."""
    plat: client.PlatformInfo = info["platform"]
    checks: list[dict[str, Any]] = []

    def add(ok: Optional[bool], label: str, fix: str = "") -> None:
        checks.append({"ok": ok, "label": label, "fix": fix})

    if not plat.supported:
        add(False, f"Supported computer: {plat.label}", plat.note)
        return _finish(checks)
    add(True, f"Supported computer: {plat.label}")
    if not info.get("binary"):
        add(False, "Console Cast installed", f"Download it from {client.DOWNLOAD_URL}, then ask me again.")
        return _finish(checks)
    add(True, f"Console Cast {info.get('version') or ''} installed".replace("  ", " "))
    if info.get("error"):
        add(False, "Console Cast answers", info["error"])
        return _finish(checks)
    snap = info.get("snapshot") or {}
    st = snap.get("status") or {}
    perm = snap.get("permissions") or {}
    level = str(perm.get("level") or st.get("permission") or "read")
    lic = licence_summary(snap.get("license_status"))

    if lic["kind"] == "free_week_ended":
        add(False, "Licence", f"The free week is over. Subscribe at {client.PRICING_URL}, then enter the key in "
                              "Console Cast's own window.")
    elif lic["kind"] == "free_week" and (lic["days_left"] or 0) <= 2:
        add(None, f"Licence: {lic['text']}", f"Plans: {client.PRICING_URL}")
    elif lic["kind"] == "inactive":
        add(None, f"Licence: {lic['text']}", f"Console Cast works for 7 days with no key, then needs a subscription: "
                                             f"{client.PRICING_URL}")
    elif lic["kind"] != "unknown":
        add(True, f"Licence: {lic['text']}")

    running = bool(st.get("running"))
    state = st.get("state") or ""
    add(running, "Console Cast running",
        "" if running else "Start it (consolecast_start, or Start Console Cast in the app).")
    if running:
        armed = state not in ("passthrough", "not_running", "stopping", "error", "")
        add(armed, "Armed (the console's broadcast comes here)",
            "" if armed else "Arm it (consolecast_arm, or Arm in the app).")
        console = st.get("console") or {}
        dns = st.get("console_dns") or {}
        seen = bool(console.get("seen"))
        add(seen, "Console found on the network",
            "" if seen else (f"Set the console's DNS: Primary {dns.get('primary', '?')}, Secondary "
                             f"{dns.get('secondary', '0.0.0.0')} (consolecast_console_setup has the menus)."))
        live = bool((st.get("stream") or {}).get("live"))
        add(live if seen else None, "Picture arriving from the console",
            "" if live else "On the console start a Twitch broadcast; then consolecast_wait_for_live.")
        obs = st.get("obs") or {}
        ws = bool(obs.get("websocket_enabled"))
        add(ws, "OBS WebSocket on",
            "" if ws else "In OBS: Tools → WebSocket Server Settings → Enable WebSocket server.")
        added = bool(obs.get("source_added"))
        add(added if ws else None, "Console Cast source in OBS",
            "" if added else "With OBS open: consolecast_obs_add_source.")
        dests = st.get("destinations") or []
        if dests:
            add(True, "Destinations: " + _dest_line(dests))
        else:
            add(None, "Destinations: none saved (optional)",
                "Only needed to send OBS's output to more services; see consolecast_destination_add_guide.")
    if level == "read":
        add(None, "AI Agents permission: Read only",
            "I can look but not start or arm. Raise it in Console Cast → Consoles & Destinations… → AI Agents "
            "if you want me to do those steps.")
    else:
        add(True, f"AI Agents permission: {level_title(level)}")
    update = snap.get("updates_check") or {}
    if update.get("update_available"):
        add(None, f"Console Cast {update.get('latest_version')} is available (you have "
                  f"{update.get('current_version')})", str(update.get("note") or
                                                          "Check for Updates in Console Cast's menu."))
    for finding in (diagnosis or {}).get("findings") or []:
        if finding.get("severity") == "blocker":
            add(False, str(finding.get("problem", ""))[:160], str(finding.get("fix", ""))[:240])
    return _finish(checks)


def _finish(checks: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [c for c in checks if c["ok"] is False]
    first = blockers[0] if blockers else next((c for c in checks if c["ok"] is None and c["fix"]), None)
    return {"ready": not blockers, "checks": checks, "left": len(blockers),
            "next": (first or {}).get("fix") or ("Ready: start a broadcast on the console." if not blockers else "")}


def preflight_text(pf: dict[str, Any]) -> str:
    head = "Ready to stream." if pf["ready"] else (
        f"Not ready yet: {pf['left']} thing{'s' if pf['left'] != 1 else ''} left.")
    lines = [head]
    for c in pf["checks"]:
        mark = OK if c["ok"] is True else BAD if c["ok"] is False else WARN if c["fix"] else INFO
        lines.append(f"{mark} {c['label']}")
    if pf.get("next"):
        lines.append(f"Next: {pf['next']}")
    return "\n".join(lines)


def destinations_text(dests: list[dict]) -> str:
    if not dests:
        return ("No destinations saved. Add one in Console Cast: Consoles & Destinations… → Local Outputs → Save "
                "Destination.")
    lines = []
    for d in dests:
        extra = f" (attempt {d['attempts']})" if d.get("state") == "retrying" and d.get("attempts") else ""
        lines.append(f"{INFO} {d.get('id')}: {d.get('state')} → {d.get('host', '')}{extra}")
    return "\n".join(lines)
