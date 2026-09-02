#!/usr/bin/env python3
"""Apply small, intentional Chromium profile defaults before Playwright starts."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


DEFAULT_START_PAGE = "http://127.0.0.1:8080/start-page/index.html"
SHOWCASE_WINDOW_PLACEMENT = {
    "left": 170,
    "top": 60,
    "right": 1270,
    "bottom": 820,
    "maximized": False,
}
SHOWCASE_MAX_WIDTH = 1120
SHOWCASE_MAX_HEIGHT = 820


def _update_preferences(path: Path, update: Callable[[dict[str, Any]], bool]) -> bool:
    if not path.exists():
        return False

    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        print(f"Chromium preference update skipped for {path}: {error}", file=sys.stderr)
        return False
    if not isinstance(loaded, dict):
        print(f"Chromium preference update skipped for {path}: root is not an object", file=sys.stderr)
        return False
    data: dict[str, Any] = loaded
    if not update(data):
        return False

    file_stat = path.stat()
    mode = stat.S_IMODE(file_stat.st_mode)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            json.dump(data, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.write("\n")
        os.chown(temporary_path, file_stat.st_uid, file_stat.st_gid)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except OSError as error:
        print(f"Chromium preference update skipped for {path}: {error}", file=sys.stderr)
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        return False
    return True


def _set_bookmark_bar_hidden(path: Path) -> bool:
    def update(data: dict[str, Any]) -> bool:
        bookmark_bar = data.get("bookmark_bar")
        if not isinstance(bookmark_bar, dict):
            bookmark_bar = {}
            data["bookmark_bar"] = bookmark_bar
        if bookmark_bar.get("show_on_all_tabs") is False:
            return False
        bookmark_bar["show_on_all_tabs"] = False
        return True

    return _update_preferences(path, update)


def _set_default_start_page(path: Path) -> bool:
    def update(data: dict[str, Any]) -> bool:
        session = data.get("session")
        if not isinstance(session, dict):
            session = {}
            data["session"] = session
        if session.get("restore_on_startup") == 4 and session.get("startup_urls") == [DEFAULT_START_PAGE]:
            return False
        session["restore_on_startup"] = 4
        session["startup_urls"] = [DEFAULT_START_PAGE]
        return True

    return _update_preferences(path, update)


def _set_showcase_window_placement(path: Path) -> bool:
    def update(data: dict[str, Any]) -> bool:
        browser = data.get("browser")
        if not isinstance(browser, dict):
            browser = {}
            data["browser"] = browser

        placement = browser.get("window_placement")
        if not isinstance(placement, dict):
            placement = {}

        try:
            width = int(placement["right"]) - int(placement["left"])
            height = int(placement["bottom"]) - int(placement["top"])
            is_safe = (
                placement.get("maximized") is False
                and int(placement["left"]) >= 0
                and int(placement["top"]) >= 29
                and width > 0
                and width <= SHOWCASE_MAX_WIDTH
                and height > 0
                and height <= SHOWCASE_MAX_HEIGHT
            )
        except (KeyError, TypeError, ValueError):
            is_safe = False

        if is_safe:
            return False

        placement.update(SHOWCASE_WINDOW_PLACEMENT)
        browser["window_placement"] = placement
        return True

    return _update_preferences(path, update)


def configure_profile(profile_preferences: Path, master_preferences: Path) -> int:
    # The master file handles first launch; the profile file handles an existing
    # named volume. Bookmarks themselves are intentionally preserved.
    for path in (master_preferences, profile_preferences):
        _set_bookmark_bar_hidden(path)
        _set_default_start_page(path)
        _set_showcase_window_placement(path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile-preferences",
        type=Path,
        default=Path("/home/desktop/.config/chromium/Default/Preferences"),
    )
    parser.add_argument(
        "--master-preferences",
        type=Path,
        default=Path("/etc/chromium/master_preferences"),
    )
    args = parser.parse_args()
    return configure_profile(args.profile_preferences, args.master_preferences)


if __name__ == "__main__":
    raise SystemExit(main())
