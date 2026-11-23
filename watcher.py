"""Console Cast watcher for a Hermes no-agent cron job.

Run on a schedule by Hermes (`/stream watch on`). It reads Console Cast's status through the app's own
agent server, compares it with the last run, and prints a message only when something changed: the
console went live or stopped, a destination dropped or came back, or the free week is about to end.
Empty output means a silent tick (Hermes sends nothing). No model is involved and nothing is changed
in Console Cast. Standard library only.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import client
import render
import store


def messages(prev: dict[str, Any], snap: dict[str, Any], events: list[dict[str, Any]], *, warn_days: int,
             now: float) -> tuple[list[str], dict[str, Any]]:
    """What to tell the user, and the state to remember. Pure, so it is easy to test."""
    out: list[str] = []
    state = dict(prev)
    status = snap.get("status") if isinstance(snap.get("status"), dict) else {}
    for ev in events:
        kind = ev["kind"]
        if kind == "live_started":
            console = (status.get("console") or {}).get("ip") or "your console"
            obs = (status.get("obs") or {})
            where = "in OBS" if obs.get("source_added") else "in Console Cast (add the OBS source with /stream setup)"
            out.append(f"● Console Cast: {console} is live. The picture is arriving {where}.")
        elif kind == "live_ended":
            ran = store.duration_text(now - float(ev.get("started_at") or now))
            out.append(f"○ Console Cast: the console stream ended after about {ran} ({ev.get('because')}). "
                       "Ask me for a recap with /stream recap.")
        elif kind == "destination_dropped":
            out.append(f"! Console Cast: {ev['id']} ({ev.get('host', '')}) dropped and is reconnecting.")
        elif kind == "destination_recovered":
            out.append(f"✓ Console Cast: {ev['id']} is streaming again.")
        elif kind == "destination_stopped":
            out.append(f"○ Console Cast: {ev['id']} stopped.")
    was_running = prev.get("running")
    running = bool(status.get("running")) if status else None
    if was_running and running is False and not any(e["kind"] == "live_ended" for e in events):
        out.append("○ Console Cast stopped running. The console has no DNS until it runs again.")
    if running is not None:
        state["running"] = running

    lic = render.licence_summary(snap.get("license_status"))
    if lic["kind"] == "free_week" and lic["days_left"] is not None and lic["days_left"] <= warn_days:
        if state.get("warned_days_left") != lic["days_left"]:
            state["warned_days_left"] = lic["days_left"]
            unit = "day" if lic["days_left"] == 1 else "days"
            out.append(f"! Console Cast: {lic['days_left']} {unit} left in your free week. "
                       f"Plans: {client.PRICING_URL}")
    elif lic["kind"] == "free_week_ended" and not state.get("warned_ended"):
        state["warned_ended"] = True
        out.append(f"! Console Cast: your free week has ended. Plans: {client.PRICING_URL}")
    elif lic.get("purchased"):
        state.pop("warned_days_left", None)
        state.pop("warned_ended", None)
    state["checked_at"] = now
    return out, state


def run(binary_override: str = "", warn_days: int = 2) -> int:
    plat = client.detect_platform()
    if not plat.supported:
        print(f"Console Cast watcher: {plat.note} Turn it off with /stream watch off.")
        return 0
    path = client.find_binary(binary_override)
    prev = store.read("watch.json", {}) or {}
    if not path:
        if not prev.get("warned_missing"):
            prev["warned_missing"] = True
            store.write("watch.json", prev)
            print(f"Console Cast watcher: Console Cast is not installed ({client.DOWNLOAD_URL}). "
                  "Turn the watcher off with /stream watch off.")
        return 0
    try:
        snap = client.snapshot(path, include=("status", "license_status"), timeout=25)
    except client.ConsoleCastError as exc:
        if not prev.get("warned_unreachable"):
            prev["warned_unreachable"] = True
            store.write("watch.json", prev)
            print(f"Console Cast watcher: could not read Console Cast ({exc}).")
        return 0
    now = time.time()
    events = store.observe(snap.get("status")) if isinstance(snap.get("status"), dict) else []
    lines, state = messages(prev, snap, events, warn_days=warn_days, now=now)
    state.pop("warned_missing", None)
    state.pop("warned_unreachable", None)
    store.write("watch.json", state)
    if lines:
        print("\n".join(lines))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    binary = os.environ.get("CONSOLECAST_BINARY", "")
    warn = int(os.environ.get("CONSOLECAST_WARN_DAYS", "2") or 2)
    return run(binary, warn)


if __name__ == "__main__":
    sys.exit(main())
