"""Find Console Cast and talk to it through its own MCP server (`consolecast mcp`).

Standard library only, so the cron watcher can import this file on its own.

Why stdio MCP and not the other two doors the app has:
- `consolecast tool NAME` runs as the person at the terminal, with Full permission. An agent going
  through it would ignore the level chosen in Console Cast -> AI Agents.
- The HTTP endpoint needs the agent token, which this plugin must never hold.
- `consolecast mcp` takes its permission level from the app on every call, lists only the tools that
  level allows, and asks before going live (MCP elicitation). That is the surface to wrap.
"""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

PLUGIN_VERSION = "1.0.1"
SITE_URL = "https://consolecast.app"
DOWNLOAD_URL = "https://consolecast.app/download"
PRICING_URL = "https://consolecast.app/pricing"
SETUP_URL = "https://consolecast.app/setup/"
PROTOCOL_VERSION = "2025-06-18"

MAC_BINARIES = (
    "/Applications/Console Cast.app/Contents/Resources/consolecast",
    "~/Applications/Console Cast.app/Contents/Resources/consolecast",
)
LINUX_BINARIES = ("/usr/lib/console-cast/consolecast",)

# What the consolecast child process may see. Hermes's own provider keys and tokens stay out of it.
_ENV_KEEP = {
    "HOME", "USER", "LOGNAME", "PATH", "LANG", "LANGUAGE", "TMPDIR", "TZ", "SHELL", "DISPLAY",
    "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_CURRENT_DESKTOP",
}
_ENV_PREFIXES = ("LC_", "CONSOLECAST_")


# ---------------------------------------------------------------------------------------- platform


@dataclass(frozen=True)
class PlatformInfo:
    key: str  # mac | linux | windows | other
    label: str
    supported: bool
    note: str = ""


def detect_platform() -> PlatformInfo:
    machine = (platform.machine() or "").lower()
    if sys.platform == "darwin":
        if machine in ("arm64", "aarch64"):
            return PlatformInfo("mac", "Mac (Apple Silicon)", True)
        return PlatformInfo("mac", "Mac (Intel)", False,
                            "Console Cast needs an Apple Silicon Mac with macOS 14 or later.")
    if sys.platform.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            return PlatformInfo("linux", "Linux x64", True)
        return PlatformInfo("linux", f"Linux {machine or 'unknown'}", False,
                            "Console Cast for Linux needs a 64-bit Intel or AMD (x64) computer.")
    if sys.platform in ("win32", "cygwin", "msys"):
        return PlatformInfo("windows", "Windows", False,
                            "Console Cast for Windows: Coming very soon. Today it runs on Apple Silicon Macs "
                            "and x64 Linux. See " + SITE_URL)
    return PlatformInfo("other", sys.platform, False, "Console Cast runs on Apple Silicon Macs and x64 Linux.")


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _ENV_KEEP or k.startswith(_ENV_PREFIXES)}


def find_binary(override: str = "") -> Optional[str]:
    """The `consolecast` executable, or None. Never downloads or installs anything."""
    candidates: list[str] = []
    if override:
        candidates.append(override)
    plat = detect_platform()
    if plat.key == "mac":
        candidates.extend(MAC_BINARIES)
    on_path = shutil.which("consolecast")
    if on_path:
        candidates.append(on_path)
    if plat.key == "linux":
        candidates.extend(LINUX_BINARIES)
    for raw in candidates:
        path = Path(os.path.expanduser(raw))
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def binary_version(binary: str, timeout: float = 5.0) -> str:
    try:
        out = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=timeout,
                             env=child_env(), stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(r"\d+\.\d+(?:\.\d+)?", out.stdout or "")
    return match.group(0) if match else ""


# ---------------------------------------------------------------------------------------- results


class ConsoleCastError(Exception):
    """Something went wrong talking to Console Cast; ``str()`` is one sentence for the user."""


class ToolNotListed(ConsoleCastError):
    """The app does not list this tool now, usually because the AI Agents level is too low."""

    def __init__(self, name: str):
        super().__init__(f"Console Cast does not offer {name!r} to agents right now.")
        self.name = name


@dataclass
class CallResult:
    tool: str
    ok: bool
    data: Any = None  # structuredContent (JSON) when the app sent it
    text: str = ""  # the error sentence (or plain text result)
    asked: list[str] = field(default_factory=list)  # confirmation questions the app sent

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            out["result"] = self.data if self.data is not None else self.text
        else:
            out["error"] = self.text
        if self.asked:
            out["console_cast_asked"] = self.asked
        return out


# Elicit callback: (message, requested_schema) -> True to accept, False to decline.
Elicit = Callable[[str, dict], bool]


def _decline(_message: str, _schema: dict) -> bool:
    return False


class McpSession:
    """One `consolecast mcp` process for the duration of a ``with`` block."""

    def __init__(self, binary: str, *, elicit: Optional[Elicit] = None, timeout: float = 30.0):
        self.binary = binary
        self.elicit = elicit or _decline
        self.timeout = timeout
        self.server_info: dict[str, Any] = {}
        self._proc: Optional[subprocess.Popen] = None
        self._lines: queue.Queue[Optional[str]] = queue.Queue()
        self._next_id = 0
        self._asked: list[str] = []

    # -- lifecycle
    def __enter__(self) -> McpSession:
        try:
            self._proc = subprocess.Popen(
                [self.binary, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1, env=child_env())
        except OSError as exc:
            raise ConsoleCastError(f"Could not start Console Cast's agent server: {exc.strerror or exc}") from exc
        threading.Thread(target=self._pump, daemon=True, name="consolecast-mcp-reader").start()
        try:
            init = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"elicitation": {}},
                "clientInfo": {"name": "hermes-consolecast", "version": PLUGIN_VERSION},
            }, timeout=min(self.timeout, 15.0))
            self.server_info = init.get("serverInfo") or {}
            self._notify("notifications/initialized")
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    # -- wire
    def _write(self, obj: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ConsoleCastError("Console Cast's agent server is not running.")
        try:
            proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise ConsoleCastError("Console Cast's agent server closed the connection.") from exc

    def _notify(self, method: str, params: Optional[dict] = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def _answer_server_request(self, msg: dict[str, Any]) -> None:
        method, rid = msg.get("method"), msg.get("id")
        if method == "elicitation/create":
            params = msg.get("params") or {}
            message = str(params.get("message") or "")
            self._asked.append(message)
            try:
                accept = bool(self.elicit(message, params.get("requestedSchema") or {}))
            except Exception:
                accept = False
            result = {"action": "accept", "content": {"confirm": True}} if accept else {"action": "decline"}
            self._write({"jsonrpc": "2.0", "id": rid, "result": result})
        elif method == "ping":
            self._write({"jsonrpc": "2.0", "id": rid, "result": {}})
        else:
            self._write({"jsonrpc": "2.0", "id": rid,
                         "error": {"code": -32601, "message": f"method not supported: {method}"}})

    def _request(self, method: str, params: dict[str, Any], timeout: Optional[float] = None) -> dict[str, Any]:
        self._next_id += 1
        rid = self._next_id
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.close()
                raise ConsoleCastError(f"Console Cast did not answer {method} in time.")
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                raise ConsoleCastError("Console Cast's agent server stopped unexpectedly.")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "method" in msg and "id" in msg:
                self._answer_server_request(msg)
                continue
            if "method" in msg:  # notification (progress, list_changed, ...)
                continue
            if msg.get("id") != rid:
                continue
            if "error" in msg:
                err = msg["error"] or {}
                text = str(err.get("message") or "error")
                if method == "tools/call" and "unknown tool" in text:
                    raise ToolNotListed(params.get("name", "?"))
                raise ConsoleCastError(text)
            return msg.get("result") or {}

    # -- API
    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._request("tools/list", {}).get("tools") or [])

    def call(self, name: str, arguments: Optional[dict[str, Any]] = None,
             timeout: Optional[float] = None) -> CallResult:
        self._asked = []
        res = self._request("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)
        text = "".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))
        data = res.get("structuredContent")
        if data is None and not res.get("isError") and text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        return CallResult(tool=name, ok=not res.get("isError"), data=data, text=text, asked=list(self._asked))


# ---------------------------------------------------------------------------------------- scrubbing

_SECRET_KEY = re.compile(r"(stream_?key|(^|_)key$|token|secret|password|passphrase|credential)", re.IGNORECASE)
_STREAM_URL = re.compile(r"\b(rtmps?|srt)://([^\s/?\"'<>]+)([/?][^\s\"'<>]*)?", re.IGNORECASE)
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _split_stream_url(match: re.Match[str]) -> tuple[str, str, str, bool]:
    """(scheme, host, first path segment, carries more) for a stream URL match."""
    scheme, host, path = match.group(1), match.group(2), match.group(3) or ""
    userinfo = "@" in host
    host = host.rsplit("@", 1)[-1]
    path, _, query = path.partition("?")
    segments = [s for s in path.split("/") if s]
    first = "/" + segments[0] if segments else ""
    return scheme, host, first, userinfo or len(segments) > 1 or bool(query)


def _is_local(host: str) -> bool:
    return host.startswith("[::1]") or host.split(":")[0] in _LOCAL_HOSTS


def _scrub_url(match: re.Match[str]) -> str:
    scheme, host, first, more = _split_stream_url(match)
    if _is_local(host):
        return match.group(0)
    return f"{scheme}://{host}{first}{'/…' if more else ''}"


def scrub(value: Any) -> Any:
    """Drop anything key-shaped before a result reaches the model, a chat or a log."""
    if isinstance(value, dict):
        return {k: ("[hidden]" if isinstance(k, str) and _SECRET_KEY.search(k) and v not in (None, "", False)
                    else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return _STREAM_URL.sub(_scrub_url, value)
    return value


def looks_like_secret_argument(args: Any) -> bool:
    """True when a model-supplied argument carries something that should never pass through a model."""
    if isinstance(args, dict):
        for k, v in args.items():
            if isinstance(k, str) and _SECRET_KEY.search(k) and v not in (None, "", False):
                return True
            if looks_like_secret_argument(v):
                return True
        return False
    if isinstance(args, list):
        return any(looks_like_secret_argument(v) for v in args)
    if isinstance(args, str):
        for m in _STREAM_URL.finditer(args):
            _scheme, host, _first, more = _split_stream_url(m)
            if more and not _is_local(host):
                return True
        return bool(re.search(r"\blive_\d{5,}_[A-Za-z0-9]{16,}", args))
    return False


# ---------------------------------------------------------------------------------------- helpers


def call_tool(binary: str, name: str, arguments: Optional[dict[str, Any]] = None, *,
              elicit: Optional[Elicit] = None, timeout: float = 30.0) -> CallResult:
    with McpSession(binary, elicit=elicit, timeout=timeout) as s:
        return s.call(name, arguments, timeout=timeout)


def snapshot(binary: str, *, include: tuple[str, ...] = ("status", "license_status", "permissions"),
             timeout: float = 20.0) -> dict[str, Any]:
    """Several read-only tools over one connection. Missing or failing ones are reported, not raised."""
    out: dict[str, Any] = {"errors": {}}
    with McpSession(binary, timeout=timeout) as s:
        out["server_version"] = s.server_info.get("version", "")
        for name in include:
            try:
                res = s.call(name)
            except ToolNotListed:
                out["errors"][name] = "not offered at this permission level"
                continue
            if res.ok:
                out[name] = scrub(res.data if res.data is not None else res.text)
            else:
                out["errors"][name] = scrub(res.text)
    return out
