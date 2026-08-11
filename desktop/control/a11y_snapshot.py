#!/usr/bin/env python3
"""Best-effort bounded AT-SPI tree snapshot for hybrid visual grounding."""

from __future__ import annotations

import argparse
import json
from typing import Any


def serialize_accessible(
    accessible: Any, budget: dict[str, int], *, desktop_coords: int
) -> dict[str, object]:
    if budget["remaining"] <= 0:
        return {"truncated": True}
    budget["remaining"] -= 1
    node: dict[str, object] = {
        "role": _safe_call(accessible.getRoleName, "unknown"),
        "name": str(getattr(accessible, "name", ""))[:500],
    }
    try:
        extents = accessible.queryComponent().getExtents(desktop_coords)
        node["bounds"] = {
            "x": extents.x,
            "y": extents.y,
            "width": extents.width,
            "height": extents.height,
        }
    except Exception:
        pass
    try:
        actions = accessible.queryAction()
        node["actions"] = [
            str(actions.getName(index))[:100] for index in range(actions.nActions)
        ]
    except Exception:
        pass
    children = []
    for index in range(min(int(getattr(accessible, "childCount", 0)), 200)):
        if budget["remaining"] <= 0:
            node["truncated"] = True
            break
        try:
            child = accessible.getChildAtIndex(index)
            children.append(
                serialize_accessible(child, budget, desktop_coords=desktop_coords)
            )
        except Exception:
            continue
    if children:
        node["children"] = children
    return node


def _safe_call(function: Any, fallback: object) -> object:
    try:
        return function()
    except Exception:
        return fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-nodes", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.max_nodes <= 5000:
        parser.error("--max-nodes must be between 1 and 5000")
    import pyatspi  # Imported here so pure serialization tests run outside the image.

    desktop = pyatspi.Registry.getDesktop(0)
    result = serialize_accessible(
        desktop, {"remaining": args.max_nodes}, desktop_coords=pyatspi.DESKTOP_COORDS
    )
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
