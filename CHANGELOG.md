# Changelog

All notable changes to the Console Cast plugin for Hermes Agent.

## 1.0.0

First release. Tested with Hermes Agent 0.23.3 and Console Cast 0.3.x on macOS (Apple Silicon).

- 25 tools in the `consolecast` toolset, wrapping Console Cast's own agent server (`consolecast mcp`): status, readiness check, start and quit, arm and disarm, console DNS values, OBS source, overlay scene and program output, destinations, wait for live, diagnosis, licence and free week, Viewer, logs, after-stream summary, and pass-through to the other local actions Console Cast offers agents (`consolecast_app_tools`, `consolecast_app_call`).
- `/stream` and `/consolecast` in every Hermes chat: status, setup, doctor, live, stop, destinations, add, watch, recap.
- `hermes consolecast` in a terminal: status, doctor, setup.
- Skills: `consolecast:setup`, `consolecast:go-live`, `consolecast:troubleshoot`, `consolecast:recap`.
- Safety: every go-live goes through Hermes's approval prompt and Console Cast's own confirmation is answered only with a person's answer; tools that take keys are not offered to the model and keys are entered only in Console Cast itself; Console Cast Cloud and account actions are not reachable; key-shaped values are scrubbed from results; shell commands that would expose Console Cast secrets are blocked.
- Live Console Cast status added to messages about your stream; a bounded session-start note in the system prompt; `@stream:` context references.
- Stream notifications through a no-LLM Hermes cron job (`/stream watch on`): going live, stream ended, destination dropped or recovered, free week ending.
- Automation blueprint `consolecast:stream-check`.
- Clear messages on Windows (Console Cast for Windows is coming very soon), Intel Macs and non-x64 Linux.
