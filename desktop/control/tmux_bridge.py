"""Bounded tmux terminal bridge for agent shell sessions."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


class TerminalError(Exception):
    """Base class for terminal bridge failures."""


class TerminalValidationError(TerminalError):
    """Input failed validation."""


SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
MAX_CAPTURE_LINES = 200
MAX_CAPTURE_BYTES = 64 * 1024
MAX_INPUT_BYTES = 4096


class TmuxBridge:
    def __init__(
        self,
        *,
        user: str | None = None,
        home: Path | None = None,
        socket_dir: Path | None = None,
    ) -> None:
        self.user = user or os.environ.get("RELAY_DESKTOP_USER", "desktop")
        self.home = Path(home or os.environ.get("RELAY_DESKTOP_HOME", "/home/desktop"))
        runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
        self.socket_dir = Path(socket_dir or os.environ.get("RELAY_TMUX_SOCKET_DIR", f"{runtime}/relay-tmux"))
        self.socket_path = self.socket_dir / "relay.sock"

    def _run(self, command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.home),
            "USER": self.user,
            "LOGNAME": self.user,
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "tmux command failed").strip()
            raise TerminalError(detail[:240])
        return result

    def ensure_server(self) -> None:
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "tmux",
                "-S",
                str(self.socket_path),
                "new-session",
                "-d",
                "-s",
                "relay-bootstrap",
                "-c",
                str(self.home),
                "bash",
                "-lc",
                "sleep infinity",
            ],
            check=False,
        )
        self._run(
            ["tmux", "-S", str(self.socket_path), "kill-session", "-t", "relay-bootstrap"],
            check=False,
        )

    def list_sessions(self) -> list[dict[str, object]]:
        result = self._run(
            [
                "tmux",
                "-S",
                str(self.socket_path),
                "list-sessions",
                "-F",
                "#{session_name}|#{session_created}|#{session_activity}",
            ],
            check=False,
        )
        sessions: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            name, created, activity = (line.split("|") + ["", "", ""])[:3]
            if not SESSION_PATTERN.fullmatch(name):
                continue
            sessions.append(
                {
                    "name": name,
                    "createdAt": int(created) if created.isdigit() else 0,
                    "lastActivityAt": int(activity) if activity.isdigit() else 0,
                }
            )
        return sessions

    def create(self, name: str, *, cwd: str | None = None) -> dict[str, object]:
        if not SESSION_PATTERN.fullmatch(name):
            raise TerminalValidationError("session name must be 1-32 alphanumeric, dash, or underscore")
        workdir = cwd or str(self.home)
        if not workdir.startswith(str(self.home)):
            raise TerminalValidationError("cwd must stay inside the desktop home directory")
        self._run(
            [
                "tmux",
                "-S",
                str(self.socket_path),
                "new-session",
                "-d",
                "-s",
                name,
                "-c",
                workdir,
                "bash",
                "-l",
            ]
        )
        return {"name": name, "cwd": workdir}

    def destroy(self, name: str) -> dict[str, object]:
        if not SESSION_PATTERN.fullmatch(name):
            raise TerminalValidationError("session name must be 1-32 alphanumeric, dash, or underscore")
        self._run(["tmux", "-S", str(self.socket_path), "kill-session", "-t", name])
        return {"name": name, "status": "destroyed"}

    def capture(self, name: str, lines: int = 100) -> dict[str, object]:
        if not SESSION_PATTERN.fullmatch(name):
            raise TerminalValidationError("session name must be 1-32 alphanumeric, dash, or underscore")
        if lines < 1 or lines > MAX_CAPTURE_LINES:
            raise TerminalValidationError(f"lines must be between 1 and {MAX_CAPTURE_LINES}")
        result = self._run(
            [
                "tmux",
                "-S",
                str(self.socket_path),
                "capture-pane",
                "-p",
                "-t",
                name,
                "-S",
                f"-{lines}",
            ]
        )
        output = result.stdout
        if len(output.encode("utf-8")) > MAX_CAPTURE_BYTES:
            output = output.encode("utf-8")[:MAX_CAPTURE_BYTES].decode("utf-8", errors="ignore")
        return {"name": name, "output": output, "truncated": len(result.stdout.encode("utf-8")) > MAX_CAPTURE_BYTES}

    def send(self, name: str, text: str, *, enter: bool = True) -> dict[str, object]:
        if not SESSION_PATTERN.fullmatch(name):
            raise TerminalValidationError("session name must be 1-32 alphanumeric, dash, or underscore")
        if not text or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise TerminalValidationError(f"text must contain between 1 and {MAX_INPUT_BYTES} bytes")
        self._run(
            [
                "tmux",
                "-S",
                str(self.socket_path),
                "send-keys",
                "-t",
                name,
                "-l",
                text,
            ]
        )
        if enter:
            self._run(["tmux", "-S", str(self.socket_path), "send-keys", "-t", name, "Enter"])
        return {"name": name, "bytesSent": len(text.encode("utf-8")), "enter": enter}
