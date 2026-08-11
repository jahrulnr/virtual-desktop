#!/usr/bin/env python3
"""UID-1000 AT-SPI adapter for the separately privileged control API."""

from __future__ import annotations

import argparse
import grp
import json
import os
import socketserver
from pathlib import Path

import pyatspi

from a11y_snapshot import serialize_accessible


class AccessibilityHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(1025)
            if not raw or len(raw) > 1024:
                raise ValueError("request is empty or too large")
            request = json.loads(raw)
            maximum = request.get("maxNodes")
            if isinstance(maximum, bool) or not isinstance(maximum, int):
                raise ValueError("maxNodes must be an integer")
            if not 1 <= maximum <= 5000:
                raise ValueError("maxNodes must be between 1 and 5000")
            desktop = pyatspi.Registry.getDesktop(0)
            data = serialize_accessible(
                desktop,
                {"remaining": maximum},
                desktop_coords=pyatspi.DESKTOP_COORDS,
            )
            response = {"ok": True, "data": data}
        except Exception:
            response = {
                "ok": False,
                "error": {"code": "SNAPSHOT_FAILED", "message": "AT-SPI snapshot failed"},
            }
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")


class AccessibilityServer(socketserver.UnixStreamServer):
    def __init__(self, path: str, group: str) -> None:
        Path(path).unlink(missing_ok=True)
        super().__init__(path, AccessibilityHandler)
        os.chown(path, -1, grp.getgrnam(group).gr_gid)
        os.chmod(path, 0o660)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/relay-access/a11y.sock")
    parser.add_argument("--group", default="relayaccess")
    args = parser.parse_args()
    with AccessibilityServer(args.socket, args.group) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
