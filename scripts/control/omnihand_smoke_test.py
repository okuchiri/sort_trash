#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _local_sdk import prefer_local_pyagxarm
from omnihand_2025_controller import OmniHandController

prefer_local_pyagxarm(__file__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test OmniHand SDK import, connection, and simple open/close motions."
    )
    parser.add_argument(
        "--config",
        default="config/sort_trash_pipeline.example.yaml",
        help="YAML file containing a top-level hand: section or a direct hand config mapping.",
    )
    parser.add_argument(
        "--action",
        default="cycle",
        choices=["open", "close", "cycle"],
        help="Which action to run after connecting.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=1.0,
        help="Pause between open/close actions when using --action cycle.",
    )
    parser.add_argument(
        "--show-data-details",
        action="store_true",
        help="Enable SDK data detail logging after connection.",
    )
    parser.add_argument(
        "--go",
        action="store_true",
        help="Actually connect to the hand and send commands. Without this flag, only config is validated.",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"YAML root must be a mapping: {path}")
    return data


def load_hand_config(path: Path) -> dict[str, Any]:
    data = load_yaml(path)
    hand_cfg = data.get("hand") if "hand" in data else data
    if not isinstance(hand_cfg, dict):
        raise SystemExit(f"Expected a hand config mapping in: {path}")
    cfg = dict(hand_cfg)
    cfg["enabled"] = True
    return cfg


def print_config_summary(cfg: dict[str, Any], path: Path) -> None:
    print(f"Config file: {path}")
    print(f"transport: {cfg.get('transport', 'can')}")
    print(f"device_id: {int(cfg.get('device_id', 1))}")
    print(f"canfd_id: {int(cfg.get('canfd_id', 0))}")
    print(f"serial_port: {cfg.get('serial_port', '/dev/ttyUSB0')}")
    print(f"serial_baudrate: {int(cfg.get('serial_baudrate', 460800))}")
    print(f"hand_type: {cfg.get('hand_type', 'left')}")
    print(f"open_wait_s: {float(cfg.get('open_wait_s', 0.4))}")
    print(f"close_wait_s: {float(cfg.get('close_wait_s', 0.5))}")
    print(f"has_open_angles: {cfg.get('open_angles_rad') is not None}")
    print(f"has_close_angles: {cfg.get('close_angles_rad') is not None}")


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        raise SystemExit(f"Config file does not exist: {config_path}")

    hand_cfg = load_hand_config(config_path)
    if args.show_data_details:
        hand_cfg["show_data_details"] = True

    print_config_summary(hand_cfg, config_path)
    if not args.go:
        print("Dry run: pass --go to connect and send OmniHand commands.")
        return 0

    controller = OmniHandController(hand_cfg, execute=True)
    print("OmniHand connected.")

    if args.action == "open":
        print("Sending open command...")
        controller.open()
    elif args.action == "close":
        print("Sending close command...")
        controller.close()
    else:
        print("Sending open command...")
        controller.open()
        if args.pause_seconds > 0:
            time.sleep(args.pause_seconds)
        print("Sending close command...")
        controller.close()
        if args.pause_seconds > 0:
            time.sleep(args.pause_seconds)
        print("Sending open command...")
        controller.open()

    print("OmniHand smoke test complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
