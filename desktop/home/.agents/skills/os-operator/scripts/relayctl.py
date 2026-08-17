#!/usr/bin/env python3
"""Small capability-safe client for Relay's operator API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any


class RelayClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = opener

    def _request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        auth: bool = True,
        expect_bytes: bool = False,
        timeout: int = 20,
    ) -> object:
        headers = {"Content-Type": "application/json"}
        if auth:
            if not self.token:
                raise ValueError("RELAY_OPERATOR_TOKEN is required for this command")
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener(request, timeout=timeout) as response:
                payload = response.read()
                if expect_bytes:
                    return payload
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get("error", {}).get("message")
            except (json.JSONDecodeError, AttributeError):
                detail = None
            raise RuntimeError(detail or f"Relay returned HTTP {error.code}") from None

    def status(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/control", auth=False)  # type: ignore[return-value]

    def agent_control(self, action: str, agent_id: str) -> dict[str, object]:
        if action not in {"claim", "heartbeat", "release"}:
            raise ValueError("unsupported agent control action")
        return self._request(
            "POST",
            f"/api/v1/control/agent/{action}",
            {"agentId": agent_id},
        )  # type: ignore[return-value]

    def input(self, agent_id: str, actions: object) -> None:
        if not isinstance(actions, list):
            raise ValueError("actions must be a JSON array")
        self._request(
            "POST",
            "/api/v1/input",
            {"agentId": agent_id, "actions": actions},
        )

    def screenshot(self) -> bytes:
        return self._request(
            "GET", "/api/v1/screenshot", expect_bytes=True
        )  # type: ignore[return-value]

    def cursor(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/cursor")  # type: ignore[return-value]

    def accessibility(self) -> dict[str, object]:
        return self._request("GET", "/api/v1/accessibility")  # type: ignore[return-value]

    def install(self, approval_id: str, plan: object) -> dict[str, object]:
        if not isinstance(plan, dict):
            raise ValueError("plan must be a JSON object")
        return self._request(
            "POST",
            "/api/v1/installs",
            {"approvalId": approval_id, "plan": plan},
            timeout=920,
        )  # type: ignore[return-value]


def json_argument(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"invalid JSON: {error.msg}") from None


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Operate a Relay desktop session")
    root.add_argument(
        "--base-url",
        default=os.environ.get("RELAY_BASE_URL", "http://127.0.0.1:8080"),
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    for name in ("claim", "heartbeat", "release"):
        command = commands.add_parser(name)
        command.add_argument("--agent-id", required=True)
    input_command = commands.add_parser("input")
    input_command.add_argument("--agent-id", required=True)
    input_command.add_argument("--actions", required=True, type=json_argument)
    shot = commands.add_parser("screenshot")
    shot.add_argument("--out", required=True)
    commands.add_parser("cursor")
    commands.add_parser("accessibility")
    install = commands.add_parser("install")
    install.add_argument("--approval-id", required=True)
    install.add_argument("--plan", required=True, type=json_argument)
    return root


def main() -> int:
    args = parser().parse_args()
    client = RelayClient(
        base_url=args.base_url,
        token=os.environ.get("RELAY_OPERATOR_TOKEN"),
    )
    try:
        if args.command == "status":
            result = client.status()
        elif args.command in {"claim", "heartbeat", "release"}:
            result = client.agent_control(args.command, args.agent_id)
        elif args.command == "input":
            client.input(args.agent_id, args.actions)
            result = {"status": "accepted"}
        elif args.command == "screenshot":
            path = Path(args.out)
            path.write_bytes(client.screenshot())
            result = {"status": "saved", "path": str(path)}
        elif args.command == "cursor":
            result = client.cursor()
        elif args.command == "accessibility":
            result = client.accessibility()
        else:
            result = client.install(args.approval_id, args.plan)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"relayctl: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
