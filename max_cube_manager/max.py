#!/usr/bin/env python3
"""MAX! Cube command-line interface using the local protocol module."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Mapping, Sequence, Tuple

if __package__:
    from .maxcube import CubeClient, CubeError, DAY_ORDER, discover_cube, parse_schedule
else:
    from maxcube import CubeClient, CubeError, DAY_ORDER, discover_cube, parse_schedule


def parse_schedule_input(raw: str) -> Dict[str, List[Tuple[int, float]]]:
    if raw.strip().startswith("{"):
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise CubeError("Schedule JSON must be an object keyed by weekday")
        return parse_schedule(data)

    data: Dict[str, List[Dict[str, Any]]] = {day: [] for day in DAY_ORDER}
    for segment in raw.split(";"):
        if not segment.strip():
            continue
        day_text, separator, entries_text = segment.strip().partition(" ")
        if not separator or day_text not in DAY_ORDER:
            raise CubeError(f"Unsupported schedule day: {day_text!r}")
        for entry in entries_text.split(","):
            time_text, separator, temperature_text = entry.strip().partition("=")
            if not separator:
                raise CubeError(f"Invalid schedule entry: {entry!r}")
            data[day_text].append({
                "time": time_text.strip(),
                "temperature": float(temperature_text),
            })
    return parse_schedule(data)


def _print_json(data: Mapping[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _read_schedule(args: argparse.Namespace) -> Dict[str, List[Tuple[int, float]]]:
    if args.schedule_file:
        with open(args.schedule_file, "r", encoding="utf-8") as handle:
            return parse_schedule_input(handle.read())
    if args.schedule:
        return parse_schedule_input(args.schedule)
    raise CubeError("Schedule is required when setting a thermostat schedule")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover a MAX! Cube, list/read thermostats, or set a weekly schedule."
    )
    parser.add_argument("--host", default=None, help="MAX! Cube host or IP; auto-discovered if omitted")
    parser.add_argument("--port", type=int, default=62910, help="MAX! Cube TCP port")
    parser.add_argument("--discover", action="store_true", help="Discover a MAX! Cube on the local network")
    parser.add_argument("--list", action="store_true", help="List rooms and thermostats")
    parser.add_argument("--read", metavar="ADDRESS", help="Read thermostat parameters")
    parser.add_argument("--set-schedule", metavar="ADDRESS", help="Set a thermostat's weekly schedule")
    parser.add_argument("--schedule", help="Schedule, e.g. 'Mo 06:00=17.5,22:00=19.0; Tu 06:00=18.0'")
    parser.add_argument("--schedule-file", help="JSON file describing a weekly schedule")
    parser.add_argument("--room-id", type=int, help="Optional room ID for schedule writes")
    args = parser.parse_args(argv)

    try:
        if args.discover:
            if args.host is None:
                host, info = discover_cube()
            else:
                with CubeClient(args.host, args.port) as cube:
                    host, info = cube.host, cube.info
            _print_json({"cubes": [{"host": host, "port": args.port, **info}]})
            return 0

        if args.list:
            with CubeClient(args.host, args.port) as cube:
                snapshot = cube.snapshot()
                _print_json({
                    "host": cube.host,
                    "rooms": snapshot["rooms"],
                    "thermostats": snapshot["thermostats"],
                })
            return 0

        if args.read:
            address = args.read.strip().upper().removeprefix("0X")
            with CubeClient(args.host, args.port) as cube:
                device = next(
                    (item for item in cube.snapshot()["thermostats"] if item["address"] == address),
                    None,
                )
                if device is None:
                    raise CubeError(f"Thermostat {address} was not found on the MAX! Cube")
                _print_json(device)
            return 0

        if args.set_schedule:
            address = args.set_schedule.strip().upper().removeprefix("0X")
            schedule = _read_schedule(args)
            with CubeClient(args.host, args.port) as cube:
                cube.set_schedule(address, schedule, room_id=args.room_id)
            _print_json({"status": "schedule set", "address": address, "room_id": args.room_id})
            return 0

        if args.host is None:
            host, info = discover_cube()
            _print_json({"cubes": [{"host": host, "port": args.port, **info}]})
            return 0

        parser.error("No action was requested; use --discover, --list, --read, or --set-schedule")
    except (CubeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
