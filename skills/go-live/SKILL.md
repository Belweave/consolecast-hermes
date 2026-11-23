---
name: go-live
description: Go-live checklist for Console Cast. Picture flowing, OBS ready, then a destination, always with the user's confirmation.
version: 1.0.0
author: Belweave
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [streaming, obs, go-live, checklist]
    related_skills: [consolecast:setup, consolecast:troubleshoot, consolecast:recap]
---

# Go live with Console Cast

Going live means OBS's program output goes to a streaming service. It is public. The user decides.

## Checklist

1. `consolecast_preflight`. Fix every ✗ first (or tell the user what is left). Do not go live with blockers.
2. The console's picture must be arriving (`stream.live`). If not: ask the user to start a Twitch broadcast on the console, then `consolecast_wait_for_live`.
3. OBS: the 'Console Cast' source is in the scene the user streams. Offer `consolecast_obs_setup_scene` only if they want the overlay scene.
4. Destinations: `consolecast_destinations`. If none is saved, call `consolecast_destination_add_guide` and stop there; never ask for a stream key in chat.
5. Say exactly what will happen, for example: "I'll start OBS program output and send it to youtube (a.rtmps.youtube.com). YouTube may go live as soon as OBS sends video." Then:
   - `consolecast_obs_output_start` if OBS program output is off,
   - `consolecast_destination_start` with the destination ID.
   Hermes shows the user an approval prompt for each. If it is denied, stop and do not retry another way.
6. Check: `consolecast_status` until the destination is `streaming` (a few seconds). Report it plainly. If it is `retrying`, run `consolecast_diagnose` and `consolecast_logs` with tag `err`.

## Never

- Never claim the user is live until a tool result says `streaming`.
- Never use `consolecast_app_call` to get around a refusal or a declined confirmation.
- If a tool says Console Cast asked and nobody confirmed, tell the user they can type `/stream live ID` themselves.

## Ending

`consolecast_end_stream` stops every destination and OBS program output (safe, never asks). Then offer a recap (`consolecast:recap`).
