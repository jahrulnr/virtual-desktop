#!/usr/bin/env python3
"""Root broker for exact, human-approved package installation plans."""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import re
import secrets
import socketserver
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class BrokerError(Exception):
    pass


class ValidationError(BrokerError):
    pass


class ApprovalError(BrokerError):
    pass


PACKAGE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,127}(?::[a-z0-9]+)?$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_plan(plan: object, downloads: Path) -> dict[str, object]:
    if not isinstance(plan, dict):
        raise ValidationError("plan must be an object")
    if plan.get("kind") == "apt":
        packages = plan.get("packages")
        if not isinstance(packages, list) or not 1 <= len(packages) <= 20:
            raise ValidationError("packages must contain between 1 and 20 names")
        if not all(isinstance(name, str) and PACKAGE_PATTERN.fullmatch(name) for name in packages):
            raise ValidationError("a package name is invalid")
        return {"kind": "apt", "packages": sorted(set(packages))}
    if plan.get("kind") == "deb":
        raw_path = plan.get("path")
        if not isinstance(raw_path, str):
            raise ValidationError("path must be a string")
        try:
            root = downloads.resolve(strict=True)
            package = Path(raw_path).resolve(strict=True)
            package.relative_to(root)
        except (FileNotFoundError, RuntimeError, ValueError):
            raise ValidationError("deb must be a file inside Downloads") from None
        if (
            not package.is_file()
            or package.suffix.lower() != ".deb"
            or not 0 < package.stat().st_size <= 2 * 1024 * 1024 * 1024
        ):
            raise ValidationError("deb must be a regular .deb file inside Downloads")
        return {"kind": "deb", "path": str(package), "sha256": sha256_file(package)}
    raise ValidationError("kind must be apt or deb")


class ApprovalStore:
    def __init__(
        self, *, clock: Callable[[], float] = time.monotonic, ttl: float = 120
    ) -> None:
        self.clock = clock
        self.ttl = ttl
        self._items: dict[str, tuple[float, dict[str, object]]] = {}
        self._lock = threading.Lock()

    def create(self, plan: dict[str, object]) -> dict[str, object]:
        with self._lock:
            approval_id = secrets.token_urlsafe(18)
            self._items[approval_id] = (self.clock() + self.ttl, plan)
            return {"approvalId": approval_id, "expiresInSeconds": round(self.ttl)}

    def consume(self, approval_id: object, plan: dict[str, object]) -> None:
        if not isinstance(approval_id, str):
            raise ApprovalError("approvalId is required")
        with self._lock:
            item = self._items.pop(approval_id, None)
            if item is None:
                raise ApprovalError("approval is unknown or already used")
            expires_at, approved_plan = item
            if self.clock() >= expires_at:
                raise ApprovalError("approval expired")
            if approved_plan != plan:
                raise ApprovalError("install plan does not match approval")


class Installer(Protocol):
    def install(self, plan: dict[str, object]) -> dict[str, object]: ...


class InstallManifest:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise BrokerError("install manifest is unreadable") from error
        plans = document.get("plans", []) if isinstance(document, dict) else []
        return plans if isinstance(plans, list) else []

    def record(self, plan: dict[str, object]) -> None:
        plans = self.load()
        if plan in plans:
            return
        plans.append(plan)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "plans": plans}, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o644)
        temporary.replace(self.path)


class SystemInstaller:
    def __init__(self, manifest: InstallManifest) -> None:
        self.manifest = manifest
        self._lock = threading.Lock()

    def _run(self, command: list[str]) -> None:
        environment = os.environ.copy()
        environment["DEBIAN_FRONTEND"] = "noninteractive"
        subprocess.run(command, check=True, timeout=900, env=environment)

    def install(self, plan: dict[str, object], *, record: bool = True) -> dict[str, object]:
        with self._lock:
            self._run(["apt-get", "update"])
            if plan["kind"] == "apt":
                packages = [str(value) for value in plan["packages"]]
                self._run(
                    ["apt-get", "install", "-y", "--no-install-recommends", "--", *packages]
                )
            else:
                path = str(plan["path"])
                self._run(["dpkg-deb", "--info", path])
                self._run(
                    ["apt-get", "install", "-y", "--no-install-recommends", "--", path]
                )
            if record:
                self.manifest.record(plan)
        return {"status": "installed", "plan": plan}


class InstallBrokerCore:
    def __init__(
        self,
        approvals: ApprovalStore,
        installer: Installer,
        downloads: Path = Path("/home/desktop/Downloads"),
    ) -> None:
        self.approvals = approvals
        self.installer = installer
        self.downloads = downloads

    def approve(self, raw_plan: object) -> dict[str, object]:
        plan = normalize_plan(raw_plan, self.downloads)
        result = self.approvals.create(plan)
        return {**result, "plan": plan}

    def install(self, approval_id: object, raw_plan: object) -> dict[str, object]:
        plan = normalize_plan(raw_plan, self.downloads)
        self.approvals.consume(approval_id, plan)
        return self.installer.install(plan)


class BrokerRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(65537)
            if not raw or len(raw) > 65536:
                raise ValidationError("request is empty or too large")
            request = json.loads(raw)
            if request.get("action") == "approve":
                result = self.server.core.approve(request.get("plan"))  # type: ignore[attr-defined]
            elif request.get("action") == "install":
                result = self.server.core.install(  # type: ignore[attr-defined]
                    request.get("approvalId"), request.get("plan")
                )
            elif request.get("action") == "health":
                result = {"status": "ok"}
            else:
                raise ValidationError("unsupported broker action")
            response = {"ok": True, "data": result}
        except (BrokerError, json.JSONDecodeError) as error:
            response = {
                "ok": False,
                "error": {"code": type(error).__name__, "message": str(error)},
            }
        except Exception:
            response = {
                "ok": False,
                "error": {"code": "INTERNAL_ERROR", "message": "install broker failed"},
            }
        self.wfile.write(json.dumps(response).encode("utf-8") + b"\n")


class BrokerServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, core: InstallBrokerCore, group: str = "relayapi") -> None:
        Path(path).unlink(missing_ok=True)
        self.core = core
        super().__init__(path, BrokerRequestHandler)
        os.chown(path, 0, grp.getgrnam(group).gr_gid)
        os.chmod(path, 0o660)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/ai-desktop/installer.sock")
    parser.add_argument("--group", default="relayapi")
    parser.add_argument(
        "--manifest", default="/var/lib/relay/install-manifest.json"
    )
    args = parser.parse_args()
    manifest = InstallManifest(Path(args.manifest))
    core = InstallBrokerCore(ApprovalStore(), SystemInstaller(manifest))
    with BrokerServer(args.socket, core, args.group) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
