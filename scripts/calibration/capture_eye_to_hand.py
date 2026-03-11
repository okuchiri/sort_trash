#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pyrealsense2 as rs

from _common import (
    build_chessboard_object_points,
    detect_chessboard,
    dump_json,
    intrinsics_from_rs,
    load_tcp_offset,
    matrix_to_pose6,
    pose6_to_matrix,
    require_output_dir,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture eye-to-hand samples with a fixed D435 and NERO flange pose.")
    parser.add_argument("--channel", required=True, help="CAN channel name, e.g. can0")
    parser.add_argument("--camera-serial", default="", help="Optional D435 serial number")
    parser.add_argument("--board-cols", type=int, required=True, help="Inner chessboard corners along width")
    parser.add_argument("--board-rows", type=int, required=True, help="Inner chessboard corners along height")
    parser.add_argument("--square-size-mm", type=float, required=True, help="Chessboard square size in millimeters")
    parser.add_argument("--samples", type=int, required=True, help="Number of capture samples to save")
    parser.add_argument("--output-dir", required=True, help="Directory for images and manifest.json")
    parser.add_argument("--tcp-offset-yaml", default="", help="Optional YAML file with a 6-element TCP offset pose")
    parser.add_argument("--width", type=int, default=1280, help="Color stream width")
    parser.add_argument("--height", type=int, default=720, help="Color stream height")
    parser.add_argument("--fps", type=int, default=30, help="Color stream FPS")
    parser.add_argument("--warmup-seconds", type=float, default=1.0, help="Camera warmup time before capture")
    parser.add_argument("--robot", default="nero", help="Robot model passed into pyAgxArm")
    return parser.parse_args()


def wait_for_pose(robot: object, timeout_s: float = 2.0) -> tuple[list[float], list[float] | None]:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            flange_msg = robot.get_flange_pose()
            if flange_msg is None:
                time.sleep(0.05)
                continue
            flange_pose = [float(v) for v in flange_msg.msg]
            tcp_msg = robot.get_tcp_pose()
            tcp_pose = [float(v) for v in tcp_msg.msg] if tcp_msg is not None else None
            return flange_pose, tcp_pose
        except Exception as exc:  # pragma: no cover - hardware path
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise RuntimeError(f"Failed to read robot pose: {last_error}") from last_error
    raise TimeoutError("Timed out waiting for robot flange pose")


def build_robot(channel: str, robot_name: str, tcp_offset_yaml: str):
    try:
        from pyAgxArm import AgxArmFactory, create_agx_arm_config
    except ImportError as exc:  # pragma: no cover - import error path
        raise SystemExit("pyAgxArm is not installed in the current environment") from exc

    cfg = create_agx_arm_config(robot=robot_name, comm="can", channel=channel, interface="socketcan")
    robot = AgxArmFactory.create_arm(cfg)
    robot.connect()
    tcp_offset = load_tcp_offset(Path(tcp_offset_yaml)) if tcp_offset_yaml else None
    if tcp_offset is not None:
        robot.set_tcp_offset(tcp_offset)
    return robot, tcp_offset


def build_pipeline(args: argparse.Namespace) -> tuple[rs.pipeline, rs.pipeline_profile]:
    pipeline = rs.pipeline()
    config = rs.config()
    if args.camera_serial:
        config.enable_device(args.camera_serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    profile = pipeline.start(config)
    time.sleep(args.warmup_seconds)
    return pipeline, profile


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    images_dir = output_dir / "images"
    require_output_dir(images_dir)

    robot, tcp_offset = build_robot(args.channel, args.robot, args.tcp_offset_yaml)
    pipeline, profile = build_pipeline(args)
    object_points = build_chessboard_object_points(args.board_cols, args.board_rows, args.square_size_mm)

    color_intrinsics = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
    manifest: dict[str, object] = {
        "robot": args.robot,
        "channel": args.channel,
        "camera_serial": args.camera_serial,
        "board": {
            "type": "chessboard",
            "cols": args.board_cols,
            "rows": args.board_rows,
            "square_size_mm": args.square_size_mm,
        },
        "camera_intrinsics": intrinsics_from_rs(color_intrinsics),
        "tcp_offset_pose": tcp_offset,
        "created_at_unix": time.time(),
        "samples": [],
    }

    captured = 0
    window_name = "capture_eye_to_hand"
    print("Controls: press 'c' to capture when corners are stable, 'q' to quit.")

    try:
        while captured < args.samples:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            if not color_frame:
                continue
            color_image = np.asanyarray(color_frame.get_data())
            gray = cv2.cvtColor(color_image, cv2.COLOR_BGR2GRAY)
            found, corners = detect_chessboard(gray, args.board_cols, args.board_rows)

            display = color_image.copy()
            if found and corners is not None:
                cv2.drawChessboardCorners(display, (args.board_cols, args.board_rows), corners, found)

            cv2.putText(
                display,
                f"captured {captured}/{args.samples}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0) if found else (0, 0, 255),
                2,
            )
            cv2.imshow(window_name, display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key != ord("c"):
                continue
            if not found or corners is None:
                print("Chessboard not detected; sample skipped.")
                continue

            flange_pose, tcp_pose = wait_for_pose(robot)
            sample_name = f"sample_{captured:03d}"
            image_path = images_dir / f"{sample_name}.png"
            cv2.imwrite(str(image_path), color_image)

            sample = {
                "name": sample_name,
                "image": str(image_path.relative_to(output_dir)),
                "captured_at_unix": time.time(),
                "board_corners_px": corners.reshape(-1, 2).astype(float).tolist(),
                "object_points_m": object_points.astype(float).tolist(),
                "flange_pose": flange_pose,
                "flange_transform": pose6_to_matrix(flange_pose).astype(float).tolist(),
                "tcp_pose": tcp_pose,
                "tcp_transform": pose6_to_matrix(tcp_pose).astype(float).tolist() if tcp_pose else None,
            }
            manifest["samples"].append(sample)
            captured += 1
            print(f"Saved {sample_name} with flange pose {matrix_to_pose6(pose6_to_matrix(flange_pose))}")
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()

    dump_json(output_dir / "manifest.json", manifest)
    print(f"Wrote {len(manifest['samples'])} samples to {output_dir / 'manifest.json'}")
    return 0 if captured == args.samples else 1


if __name__ == "__main__":
    sys.exit(main())
