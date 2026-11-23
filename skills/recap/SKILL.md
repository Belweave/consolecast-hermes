---
name: recap
description: After-stream summary for Console Cast. How long it ran, which destinations, drops and reconnects, and anything to fix before next time.
version: 1.0.0
author: Belweave
license: Apache-2.0
platforms: [macos, linux]
metadata:
  hermes:
    tags: [streaming, recap, summary]
    related_skills: [consolecast:go-live, consolecast:troubleshoot]
---

# Stream recap

1. `consolecast_stream_summary`. It has the last (or current) stream as Hermes noticed it: start, end, duration, peak bitrate from the console, each destination with drops and connection attempts, warnings and recent error lines.
2. Write a short recap: one line on how long it ran, one line per destination, then anything that went wrong with a concrete fix for next time (from the warnings and errors; `consolecast_diagnose` if something is still wrong).
3. Times are when Hermes noticed the change, so say "about". If the result says no stream was recorded, say so and mention `/stream watch on` so the next one is tracked.
4. If a destination is still running, ask whether to end the stream (`consolecast_end_stream`).
