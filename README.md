# Console Cast for Hermes Agent

Make Hermes your stream producer. [Console Cast](https://consolecast.app) brings a PS5 or Xbox Series X|S console's built-in broadcast into OBS Studio on your Mac or Linux computer with no capture card, and sends OBS's output to several destinations at once. This plugin lets Hermes check, set up, run and wrap up those streams from any Hermes chat: the terminal, the TUI, the Desktop app, or Telegram, Discord, Slack and the other messaging apps Hermes connects to.

Console Cast itself is free for 7 days with no account, card or key, then $2.99 a month. This plugin is free.

## What you need

- Hermes Agent 0.23.3 or later.
- Console Cast on the same computer as Hermes: an Apple Silicon Mac with macOS 14 or later, or a 64-bit Intel or AMD (x64) Linux computer with Ubuntu 22.04+, Debian 12+ or Fedora 40+. Get it at https://consolecast.app/download. Version 0.3.2 or later also reports the free week's days left.
- OBS Studio 28 or later, and a PS5 or Xbox Series X|S on the same network.
- Windows: Console Cast for Windows is coming very soon. Until then the plugin loads on Windows and says so, instead of failing.

## Install

```bash
hermes plugins install Belweave/consolecast-hermes --enable
```

That clones https://github.com/Belweave/consolecast-hermes into your Hermes plugins folder as `consolecast` and enables it. Where the [Hermes plugin catalog](https://hermes-agent.nousresearch.com/marketplace) lists it, `hermes plugins install consolecast` installs the reviewed version at its pinned commit instead. Without `--enable`, Hermes asks whether to enable it; later, `hermes plugins enable consolecast`. For another [Hermes profile](https://hermes-agent.nousresearch.com/docs/user-guide/profiles), use `hermes -p <profile> plugins install …`.

Start a new Hermes session (tools load in new sessions; `/stream` works right away), then type `/stream`. `/plugins` lists it as `consolecast`.

First time: `/stream setup` (or ask Hermes "set up Console Cast for me"). It checks everything, does the safe steps itself (start, arm, add the OBS source), and tells you exactly what is left for you, like your console's DNS values. Run it again any time; it changes nothing that is already done.

## What it adds

### `/stream` in every chat

| Command | Does |
| --- | --- |
| `/stream` | Status at a glance: LIVE or not, console, OBS, destinations, permission, licence |
| `/stream setup [ps5\|xbox]` | Guided setup, safe to repeat: already done, done now, left for you |
| `/stream doctor` | Am I ready to stream? Checklist plus Console Cast's own diagnosis |
| `/stream live [ID]` | Go live on a destination. Always asks you first, in the chat |
| `/stream stop [ID]` | End the stream (asks), or stop one destination |
| `/stream destinations` | Saved destinations and their state |
| `/stream add ID` | How to save a destination without pasting its key into a chat |
| `/stream watch on\|off\|status [minutes] [target]` | Notifications: going live, stream ended, a destination dropped or came back, free week ending. `target` is a Hermes delivery target such as `telegram` or `discord:#streams` |
| `/stream recap` | After-stream summary |

`/consolecast` is the same command, in case another plugin already uses `/stream`.

### Tools Hermes can use

`consolecast_status`, `consolecast_preflight`, `consolecast_start`, `consolecast_stop`, `consolecast_arm`, `consolecast_disarm`, `consolecast_console_setup`, `consolecast_obs_add_source`, `consolecast_obs_setup_scene`, `consolecast_obs_output_start`, `consolecast_obs_output_stop`, `consolecast_destinations`, `consolecast_destination_add_guide`, `consolecast_destination_start`, `consolecast_destination_stop`, `consolecast_end_stream`, `consolecast_wait_for_live`, `consolecast_diagnose`, `consolecast_license`, `consolecast_viewer`, `consolecast_logs`, `consolecast_stream_summary`, `consolecast_app_tools`, `consolecast_app_call`, `consolecast_notifications`.

They wrap Console Cast's own agent server (`consolecast mcp`), so they behave exactly like the app. `consolecast_app_tools` and `consolecast_app_call` reach the other actions Console Cast offers agents, including ones added after this plugin was released. The plugin covers Console Cast on this computer only: Console Cast Cloud and Console Cast account actions are not available through it.

### Skills

`consolecast:setup` (first-time setup), `consolecast:go-live` (go-live checklist), `consolecast:troubleshoot` (no picture, drops), `consolecast:recap` (after-stream summary).

### And

- **Live status in context.** When you talk about your stream, Hermes reads Console Cast's real status for that message, so it answers from the actual state. Turn it off with the `context_injection` setting.
- **`@stream:` references** in the terminal: `@stream:status`, `@stream:ready`, `@stream:destinations`, `@stream:license`, `@stream:recap`, `@stream:log`.
- **Blueprint** `consolecast:stream-check` (`/blueprint stream-check`): a scheduled "am I ready?" check before your usual stream nights. It never starts anything.
- **`hermes consolecast`** in a terminal: `status`, `doctor`, `setup`.

## Safety

**Console Cast decides what Hermes may do.** In Console Cast → Consoles & Destinations… → AI Agents you choose Read only, Control or Full. The plugin talks to the app's agent server, which enforces that level on every call; the plugin never changes it and never goes around it. At Read only, Hermes can look but not start, arm or go live, and says so.

**Going live always asks you.** Starting a destination or OBS program output, disarming while live, quitting while live and removing things go through Hermes's approval prompt (in the terminal, the Desktop app, or as /approve buttons in Telegram, Discord or Slack). Every go-live is asked separately: an "always" answer does not carry over to the next one. Console Cast then asks its own question unless you turned on "Go live without asking" in the app; the plugin answers it with your answer and only yours. If Hermes did not ask a person (YOLO, approvals off, a cron job), the plugin answers "no" and Console Cast's own setting decides. `/stream live` asks you directly in the chat.

**Keys never pass through Hermes.** The plugin never asks for, reads, holds or stores a stream key, licence key or the Console Cast agent token:

- Console Cast actions that take a key are not offered to the model. You enter keys in Console Cast's own window (Consoles & Destinations… → Local Outputs → Save Destination on a Mac; the licence window for a licence key) or, in your own terminal, with Console Cast's own CLI (`consolecast output save ID`, `consolecast license activate`), never in a chat.
- Results are scrubbed of anything key-shaped before Hermes sees them, and Twitch-style keys are added to Hermes's own redaction.
- The plugin uses Console Cast's stdio agent server, which needs no token, and never reads Console Cast's settings or token files.

**Nothing is installed for you.** If Console Cast is missing, Hermes gives you the download link and asks; it never downloads or installs it.

## What it touches (disclosure)

- **Programs it runs:** `consolecast mcp` and `consolecast version` from Console Cast (`/Applications/Console Cast.app/Contents/Resources/consolecast` on a Mac; `consolecast` on PATH or `/usr/lib/console-cast/consolecast` on Linux; or the `binary` setting). Short-lived child processes, started without a shell, with a reduced environment: home, PATH, locale, display and session-bus variables and `CONSOLECAST_*` only. No Hermes variables (so no YOLO setting) and no API keys are passed. No other shell commands.
- **Network:** the plugin makes no network requests. Some Console Cast actions it calls reach the network themselves (the update check, the DNS self test in the diagnosis, a destination once you start it).
- **Reads outside its own data:** it checks where `consolecast` is installed and reads its own settings through Hermes. To apply its rules, its hooks look at, without storing: the name and arguments of each tool call (and the command text of `terminal` and `execute_code` calls), each user message (to see whether it is about your stream), and Hermes's approval answers for its own requests.
- **Changes to Hermes behaviour:** blocks agent shell commands that would print the Console Cast agent token, read Console Cast's secret files, carry a stream or licence key, change Console Cast's AI Agents setting, reach Console Cast Cloud or account commands, or run `consolecast tool` (which would ignore the AI Agents level) (setting `terminal_guard`). Adds Console Cast's status to messages about your stream (setting `context_injection`) and a short Console Cast note to the system prompt of new sessions.
- **Stored data:** small JSON files in `~/.hermes/plugin-data/consolecast/`: a stream journal for recaps, notification state and the console type you chose in setup. No credentials, ever.
- **Background work:** none of its own. With `/stream watch on`, it writes `~/.hermes/scripts/consolecast-watch.py` (a launcher; Hermes runs cron scripts only from there) and creates the Hermes cron job `consolecast-watch`, which checks Console Cast every few minutes with no model and no tokens. `/stream watch off` removes both.
- **Telemetry:** none.

## Settings

`hermes config set plugins.entries.consolecast.settings.<key> <value>` (or the plugin's page in Hermes Desktop):

| Key | Default | |
| --- | --- | --- |
| `binary` | empty | Path to `consolecast`, if it is somewhere unusual |
| `context_injection` | `true` | Add live status when you talk about your stream |
| `terminal_guard` | `true` | Block agent shell commands that would expose Console Cast secrets or get around its AI Agents setting |
| `watch_interval_minutes` | `2` | How often notifications check |
| `free_week_warn_days` | `2` | Free-week reminder threshold |

## Troubleshooting

- **`/stream` says not installed** but it is: set `binary` to the full path of `consolecast`.
- **"permission is Read only; this needs Control"**: that is Console Cast's AI Agents setting. Change it there if you want Hermes to start, arm or go live.
- **"Console Cast asks before this goes live, and nobody confirmed it here"**: Hermes's approvals were off or answered automatically. Type `/stream live ID` yourself, or turn on "Go live without asking" in Console Cast.
- **Tools missing in a chat**: tools load in new sessions; start one. With many plugins, Hermes's tool search may show them on demand (search for "console cast").
- **No picture**: `/stream doctor`, or ask Hermes to troubleshoot; it follows Console Cast's own diagnosis.
- **Logs**: `hermes logs --level WARNING | grep -i consolecast`.
- **Notifications after removing the plugin**: `hermes cron remove consolecast-watch`.

## Development

The plugin uses only the Python standard library. Tests need `pytest` and use a fake `consolecast` (`tests/fake_consolecast.py`), so neither Hermes nor Console Cast has to be installed:

```bash
python -m pytest tests -q
```

Check it the way the Hermes plugin catalog does, from a Hermes checkout or install:

```bash
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

## Contact

Belweave · https://consolecast.app · info@belweave.com

## Licence and trademarks

Copyright 2026 Belweave. The plugin is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)). Console Cast itself is a separate product with its own terms.

PlayStation and PS5 are registered trademarks of Sony Interactive Entertainment Inc. Xbox is a registered trademark of Microsoft Corporation. Twitch is a registered trademark of Twitch Interactive, Inc. YouTube is a trademark of Google LLC. Discord is a registered trademark of Discord Inc. OBS Studio is a trademark of the OBS Project. Console Cast is not affiliated with or endorsed by any of them.

## License

This plugin is Apache-2.0, copyright Belweave. See [LICENSE](LICENSE). The licence covers the files in this repository only. Console Cast itself, the app this plugin controls, is proprietary, closed-source software from Belweave, used under the terms at <https://consolecast.app/legal/terms>.
