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
    intrinsics_to_matrix,
    invert_transform,
    load_yaml,
    matrix_to_pose6,
    pose6_to_matrix,
    reprojection_error,
    rt_to_matrix,
    solve_pnp,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a fixed-camera eye-to-hand result with live chessboard observations.")
    parser.add_argument("--calibration-file", required=True, help="Path to calibration_result.yaml")
    parser.add_argument("--channel", required=True, help="CAN channel name, e.g. can0")
    parser.add_argument("--camera-serial", default="", help="Optional D435 serial number")
    parser.add_argument("--samples", type=int, default=5, help="Verification samples to capture")
    parser.add_argument("--output-json", default="", help="Optional explicit verification report path")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--robot", default="nero")
    return parser.parse_args()


def build_robot(channel: str, robot_name: str):
    from pyAgxArm import AgxArmFactory, create_agx_arm_config

    cfg = create_agx_arm_config(robot=robot_name, comm="can", channel=channel, interface="socketcan")
    robot = AgxArmFactory.create_arm(cfg)
    robot.connect()
    return robot


def wait_for_flange_pose(robot: object, timeout_s: float = 2.0) -> list[float]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pose_msg = robot.get_flange_pose()
        if pose_msg is not None:
            return [float(v) for v in pose_msg.msg]
        time.sleep(0.05)
    raise TimeoutError("Timed out waiting for flange pose")


def build_pipeline(args: argparse.Namespace) -> rs.pipeline:
    pipeline = rs.pipeline()
    config = rs.config()
    if args.camera_serial:
        config.enable_device(args.camera_serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    pipeline.start(config)
    time.sleep(1.0)
    return pipeline


def rotation_error_deg(rot_a: np.ndarray, rot_b: np.ndarray) -> float:
    delta = rot_a.T @ rot_b
    trace = np.clip((np.trace(delta) - 1.0) * 0.5, -1.0, 1.0)
    return float(np.degrees(np.arccos(trace)))


def main() -> int:
    args = parse_args()
    calibration_path = Path(args.calibration_file).expanduser().resolve()
    calibration = load_yaml(calibration_path)
    board = calibration["board"]
    object_points = build_chessboard_object_points(board["cols"], board["rows"], board["square_size_mm"])

    intrinsics_block = calibration["camera_intrinsics"]
    camera_matrix = np.asarray(intrinsics_block["camera_matrix"], dtype=np.float64)
    dist_coeffs = np.asarray(intrinsics_block["dist_coeffs"], dtype=np.float64)
    base_to_camera = np.asarray(calibration["transforms"]["T_base_camera"]["matrix"], dtype=np.float64)
    gripper_to_target = np.asarray(calibration["transforms"]["T_gripper_target"]["matrix"], dtype=np.float64)

    robot = build_robot(args.channel, args.robot)
    pipeline = build_pipeline(args)
    report = {"samples": []}
    window_name = "verify_eye_to_hand"

    print("Controls: press 'c' to capture a verification sample, 'q' to quit.")
    try:
        while len(report["samples"]) < args.samples:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            if not color_frame:
                continue
            color_image = np.asanyarray(color_frame.get_data())
            gray = cv2.cvtColor(color_image, cv2.COLOR_BGR2GRAY)
            found, corners = detect_chessboard(gray, board["cols"], board["rows"])

            display = color_image.copy()
            if found and corners is not None:
                cv2.drawChessboardCorners(display, (board["cols"], board["rows"]), corners, found)
            cv2.putText(
                display,
                f"verify {len(report['samples'])}/{args.samples}",
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

            flange_pose = wait_for_flange_pose(robot)
            rvec, tvec = solve_pnp(corners, object_points, camera_matrix, dist_coeffs)
            camera_to_target = rt_to_matrix(rvec, tvec)
            predicted_target_in_base = pose6_to_matrix(flange_pose) @ gripper_to_target
            observed_target_in_base = base_to_camera @ camera_to_target

            translation_error_m = float(
                np.linalg.norm(predicted_target_in_base[:3, 3] - observed_target_in_base[:3, 3])
            )
            rotation_error = rotation_error_deg(
                predicted_target_in_base[:3, :3], observed_target_in_base[:3, :3]
            )
            pnp_error = reprojection_error(object_points, corners, rvec, tvec, camera_matrix, dist_coeffs)
            report["samples"].append(
                {
                    "flange_pose": flange_pose,
                    "predicted_target_pose": matrix_to_pose6(predicted_target_in_base),
                    "observed_target_pose": matrix_to_pose6(observed_target_in_base),
                    "translation_error_mm": translation_error_m * 1000.0,
                    "rotation_error_deg": rotation_error,
                    "pnp_reprojection_px": pnp_error,
                }
            )
            print(
                f"sample {len(report['samples'])}: "
                f"translation={translation_error_m * 1000.0:.2f} mm, "
                f"rotation={rotation_error:.2f} deg, pnp={pnp_error:.3f} px"
            )
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()

    if not report["samples"]:
        return 1

    report["summary"] = {
        "mean_translation_error_mm": float(np.mean([s["translation_error_mm"] for s in report["samples"]])),
        "max_translation_error_mm": float(np.max([s["translation_error_mm"] for s in report["samples"]])),
        "mean_rotation_error_deg": float(np.mean([s["rotation_error_deg"] for s in report["samples"]])),
        "mean_pnp_reprojection_px": float(np.mean([s["pnp_reprojection_px"] for s in report["samples"]])),
    }
    output_path = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json
        else calibration_path.with_name("verification_report.json")
    )
    dump_json(output_path, report)
    print(f"Verification report saved to {output_path}")
    print(report["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
