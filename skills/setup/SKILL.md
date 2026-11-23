---
name: setup
description: First-time Console Cast setup, start to finish, safe to run again. Brings a PS5 or Xbox Series X|S broadcast into OBS on this Mac or Linux computer.
version: 1.0.0
author: Belweave
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [streaming, obs, ps5, xbox, setup]
    related_skills: [consolecast:go-live, consolecast:troubleshoot]
---

# Set up Console Cast

Console Cast brings a PS5 or Xbox Series X|S console's built-in broadcast into OBS Studio on this computer, with no capture card. It works for 7 days with no account or key, then needs a subscription.

## Rules

- Check before you act. Every step starts with a check; when it passes, skip the step. Running this again must change nothing.
- Do everything you can with the consolecast tools. Ask the user only where a step says to.
- Never ask for, repeat, log or save a licence key, stream key or the agent token.
- Console Cast Cloud and account sign-in are not part of this plugin; do not offer them.
- Never start a destination or OBS program output here. Setup never puts anyone on air.
- Never download or install anything without asking first, and never change Console Cast's AI Agents setting: what you may do is the user's choice in Console Cast → Consoles & Destinations… → AI Agents.

## Procedure

1. **Computer and install.** Call `consolecast_preflight`.
   - Unsupported computer (Windows, Intel Mac, non-x64 Linux): tell the user what the result says and stop.
   - Not installed: give the download link from the result (https://consolecast.app/download) and ask whether they want to install it themselves now. Wait. Do not download it for them unless they explicitly ask, and even then confirm before running anything.
2. **Licence.** From the same result. During the free week there is nothing to do; say how many days are left. If the free week has ended, point to https://consolecast.app/pricing and say they enter the key in Console Cast's own window. Never ask for the key in chat.
3. **Start and arm.** If not running: `consolecast_start` (arms by default). If running but in pass-through: `consolecast_arm`. If a tool says the permission level is too low, tell the user exactly what it says and continue with the steps you can do.
4. **OBS.** If `websocket_enabled` is false, ask the user to switch it on in OBS: Tools → WebSocket Server Settings → Enable WebSocket server. If OBS is not installed, ask before suggesting anything: it is free at https://obsproject.com. With OBS open and the WebSocket on, call `consolecast_obs_add_source`.
5. **Console.** Only the user can do this one. Ask which console they have, call `consolecast_console_setup` with `ps5` or `xbox`, and give the menu path and both DNS values exactly as returned.
6. **Confirm.** Ask the user to start a Twitch broadcast on the console, then call `consolecast_wait_for_live`. If no picture arrives, call `consolecast_diagnose` and do what it says (load `consolecast:troubleshoot`).
7. **Optional.** Mention `/stream watch on` (notifications when they go live, a destination drops, or the free week ends) and that destinations are saved in Console Cast itself (Consoles & Destinations… → Local Outputs), never by pasting a key here.

Finish with three short lists: already done, done now, left for the user.

## Shortcut

The user can type `/stream setup` (or `/stream setup ps5`) for the same checks without a model.
