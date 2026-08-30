#!/usr/bin/env python3
"""Run the deterministic part of a short Computer Relay showcase.

The helper talks to the stateless Streamable HTTP MCP endpoint. It intentionally
stops after submitting the visible task: an agent can then inspect the real
result, interact with the rendered output, and save or discard the recording.
No model picker, folder picker, fake provider, or fallback is touched here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_PROMPT = (
    "Jelaskan alur login web maksimal tiga kalimat. Sertakan satu diagram "
    "Mermaid sequenceDiagram sederhana dengan Pengguna, Browser, API, dan "
    "Database. Jangan gunakan tools atau web."
)

# Deliberately small chunks make the visible input look like a person typing,
# while the MCP client still avoids dozens of model-tool round trips.
DEFAULT_CHUNKS = (
    "Jelas", "kan ", "a", "lur ", "lo", "gin ", "web ", "mak", "si", "mal ",
    "ti", "ga ", "ka", "li", "mat. ", "Ser", "ta", "kan ", "sa", "tu ",
    "di", "a", "gram ", "Mer", "maid ", "se", "quence", "Dia", "gram ",
    "se", "der", "ha", "na ", "de", "ngan ", "Peng", "gu", "na, ", "Brow",
    "ser, ", "A", "PI, ", "dan ", "Da", "ta", "base. ", "Ja", "ngan ",
    "gu", "na", "kan ", "tools ", "a", "tau ", "web.",
)


class MCPError(RuntimeError):
    """An MCP transport or tool-call failure without request-body details."""


def human_chunks(text: str) -> tuple[str, ...]:
    """Split text into short visible typing units while preserving every byte."""

    chunks: list[str] = []
    for token in re.findall(r"\s+|[\w]+|[^\w\s]", text, flags=re.UNICODE):
        if token.isspace():
            if chunks:
                chunks[-1] += token
            else:
                chunks.append(token)
            continue
        if token.isalnum() or "_" in token:
            chunks.extend(token[index:index + 3] for index in range(0, len(token), 3))
        else:
            chunks.append(token)
    return tuple(chunks)


def _text_content(result: dict[str, Any]) -> str:
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text", ""))
    return ""


def parse_mcp_response(body: str, request_id: int) -> dict[str, Any]:
    """Parse either JSON or an SSE-wrapped JSON-RPC response."""

    message: dict[str, Any] | None = None
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            candidate = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("id") == request_id:
            message = candidate
            break

    if message is None:
        try:
            candidate = json.loads(body)
        except json.JSONDecodeError as exc:
            raise MCPError("MCP returned neither JSON nor a matching SSE message") from exc
        if isinstance(candidate, dict):
            message = candidate

    if message is None:
        raise MCPError("MCP returned an invalid response")
    if "error" in message:
        error = message.get("error")
        detail = error.get("message") if isinstance(error, dict) else None
        raise MCPError(f"MCP request failed: {detail or 'unknown error'}")

    result = message.get("result")
    if not isinstance(result, dict):
        raise MCPError("MCP response did not contain a result")
    if result.get("isError"):
        detail = _text_content(result) or "tool call failed"
        raise MCPError(detail)
    return result


@dataclass
class MCPClient:
    endpoint: str
    token: str | None = None
    timeout: float = 45.0
    request_id: int = 0

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # Keep error output bounded and do not echo the JSON request body.
            detail = exc.read(512).decode("utf-8", errors="replace").strip()
            raise MCPError(f"MCP HTTP {exc.code}: {detail or 'request failed'}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"MCP connection failed: {exc.reason}") from exc
        return parse_mcp_response(body, self.request_id)

    def tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.call("tools/call", {"name": name, "arguments": arguments or {}})


def showcase_action_plan(
    chunks: tuple[str, ...], composer: tuple[int, int], record: bool = True
) -> list[tuple[str, dict[str, Any]]]:
    """Build the visible action sequence; model/folder selection is absent by design."""

    plan: list[tuple[str, dict[str, Any]]] = []
    if record:
        plan.append(("record_screen", {"mode": "START_RECORDING"}))
    plan.append(("computer", {"action": "left_click", "coordinate": [composer[0], composer[1]]}))
    plan.extend(("computer", {"action": "type", "text": chunk}) for chunk in chunks)
    plan.append(("computer", {"action": "key", "key": "CTRL+ENTER"}))
    return plan


def _runtime_state(client: MCPClient) -> dict[str, Any]:
    result = client.tool("runtime_status")
    try:
        state = json.loads(_text_content(result))
    except json.JSONDecodeError as exc:
        raise MCPError("relay returned invalid runtime status") from exc
    if not isinstance(state, dict):
        raise MCPError("relay runtime status was not an object")
    owner = state.get("control", {}).get("owner")
    if owner not in (None, "none"):
        raise MCPError("a human currently controls the desktop")
    return state


def run_showcase(
    client: MCPClient,
    prompt: str,
    composer: tuple[int, int],
    typing_delay: float,
    record: bool,
) -> dict[str, Any]:
    if typing_delay < 0 or typing_delay > 2:
        raise MCPError("typing delay must be between 0 and 2 seconds")

    _runtime_state(client)
    client.tool("computer", {"action": "screenshot"})
    chunks = DEFAULT_CHUNKS if prompt == DEFAULT_PROMPT else human_chunks(prompt)
    started = False
    try:
        for tool_name, arguments in showcase_action_plan(chunks, composer, record):
            client.tool(tool_name, arguments)
            if tool_name == "record_screen":
                started = True
            if arguments.get("action") == "type":
                time.sleep(typing_delay)
    except Exception:
        if started:
            try:
                client.tool("record_screen", {"mode": "DISCARD_RECORDING"})
            except Exception:
                pass
        raise

    return {
        "status": "submitted",
        "chunks": len(chunks),
        "recording_started": started,
        "next": "observe the result with Computer Relay, then save or discard the recording",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("RELAY_MCP_URL", "http://127.0.0.1:8091/mcp"),
        help="MCP Streamable HTTP endpoint (default: RELAY_MCP_URL or external relay endpoint)",
    )
    parser.add_argument(
        "--token-env",
        default="MCP_AUTH_TOKEN",
        help="environment variable containing the external MCP bearer token",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--composer-x", type=int, default=900)
    parser.add_argument("--composer-y", type=int, default=688)
    parser.add_argument("--typing-delay", type=float, default=0.06)
    parser.add_argument("--no-recording", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the action plan without calling MCP")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    chunks = DEFAULT_CHUNKS if args.prompt == DEFAULT_PROMPT else human_chunks(args.prompt)
    plan = showcase_action_plan(chunks, (args.composer_x, args.composer_y), not args.no_recording)
    if args.dry_run:
        print(json.dumps({"url": args.url, "chunks": len(chunks), "actions": [name for name, _ in plan]}))
        return 0

    token = os.environ.get(args.token_env)
    if not token and ":8090/" not in args.url:
        print(f"{args.token_env} is required for an external MCP endpoint", file=sys.stderr)
        return 2

    try:
        result = run_showcase(
            MCPClient(args.url, token=token),
            args.prompt,
            (args.composer_x, args.composer_y),
            args.typing_delay,
            not args.no_recording,
        )
    except (MCPError, OSError) as exc:
        print(f"showcase automation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
