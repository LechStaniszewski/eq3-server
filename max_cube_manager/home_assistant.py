"""Home Assistant app entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

if __package__:
    from .max_web import main as web_main
else:
    from max_web import main as web_main


def build_web_args(options: Dict[str, Any]) -> List[str]:
    cube_host = options.get("cube_host")
    if not isinstance(cube_host, str) or not cube_host.strip():
        raise ValueError("Set the MAX! Cube address in the app configuration")

    cube_port = options.get("cube_port", 62910)
    if isinstance(cube_port, bool):
        raise ValueError("The MAX! Cube port must be between 1 and 65535")
    try:
        cube_port = int(cube_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("The MAX! Cube port must be between 1 and 65535") from exc
    if not 1 <= cube_port <= 65535:
        raise ValueError("The MAX! Cube port must be between 1 and 65535")

    debug = options.get("debug", False)
    if not isinstance(debug, bool):
        raise ValueError("Debug logging must be true or false")

    args = [
        "--cube-host",
        cube_host.strip(),
        "--cube-port",
        str(cube_port),
        "--bind",
        "0.0.0.0",
        "--port",
        "8765",
        "--home-assistant-ingress",
    ]
    if debug:
        args.append("--debug")
    return args


def main() -> int:
    try:
        options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
        if not isinstance(options, dict):
            raise ValueError("App options must be a JSON object")
        args = build_web_args(options)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return web_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
