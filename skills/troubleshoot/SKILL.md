---
name: troubleshoot
description: Why is there no picture, why did a destination drop, why does OBS show nothing. Console Cast troubleshooting from its own diagnosis.
version: 1.0.0
author: Belweave
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [streaming, troubleshooting, dns, obs]
    related_skills: [consolecast:setup, consolecast:go-live]
---

# Troubleshoot Console Cast

Console Cast knows what is wrong better than a guess. Start from its diagnosis and change nothing until you have read it.

## Procedure

1. `consolecast_diagnose`. Read `summary` and each finding's `fix`. Blockers first.
2. Common findings and what the user does:
   - **No device has used Console Cast DNS**: the console's DNS is not set, or the computer's IP changed. Call `consolecast_console_setup` and give the values again.
   - **Not running / pass-through**: `consolecast_start` or `consolecast_arm`.
   - **OBS WebSocket off**: OBS → Tools → WebSocket Server Settings → Enable WebSocket server; then `consolecast_obs_add_source`.
   - **Destination retrying**: `consolecast_logs` with tag `err` and the destination ID in `contains`. Wrong or expired keys are fixed by the user in Console Cast's own window (saving the same ID again replaces it).
3. On Linux, port 53 or the firewall can block the console's DNS. Console Cast's diagnosis says so; repeat its fix exactly. Never run `sudo` commands for the user without asking and showing the command first.
4. After a fix, check again with `consolecast_preflight`.

## Never

- Never ask for a stream key, licence key or the agent token, and never read Console Cast's settings files.
- Never change the AI Agents permission; if a tool needs a higher level, say so and let the user decide.
