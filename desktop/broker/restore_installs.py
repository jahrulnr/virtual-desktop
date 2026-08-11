#!/usr/bin/env python3
"""Replay approved package plans after a container is recreated."""

from __future__ import annotations

import argparse
from pathlib import Path

from install_broker import InstallManifest, SystemInstaller, normalize_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="/var/lib/relay/install-manifest.json")
    parser.add_argument("--downloads", default="/home/desktop/Downloads")
    args = parser.parse_args()
    manifest = InstallManifest(Path(args.manifest))
    installer = SystemInstaller(manifest)
    plans = manifest.load()
    if not plans:
        return
    print(f"Restoring {len(plans)} approved install plan(s)", flush=True)
    for saved_plan in plans:
        normalized = normalize_plan(saved_plan, Path(args.downloads))
        if normalized != saved_plan:
            raise RuntimeError("persisted install plan no longer matches its source")
        installer.install(normalized, record=False)


if __name__ == "__main__":
    main()
