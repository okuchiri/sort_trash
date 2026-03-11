#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from _common import (
    average_transforms,
    camera_matrix_and_dist_from_manifest,
    dump_json,
    dump_yaml,
    load_yaml,
    matrix_to_dict,
    matrix_to_pose6,
    pose6_to_matrix,
    reprojection_error,
    rt_to_matrix,
    solve_pnp,
    invert_transform,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve fixed-camera eye-to-hand calibration from captured chessboard samples.")
    parser.add_argument("--dataset-dir", required=True, help="Directory containing manifest.json and images/")
    parser.add_argument("--output-yaml", default="", help="Optional explicit output YAML path")
    parser.add_argument(
        "--method",
        default="andreff",
        choices=["tsai", "park", "horaud", "andreff", "daniilidis"],
        help="OpenCV hand-eye solver",
    )
    return parser.parse_args()


METHOD_MAP = {
    "tsai": cv2.CALIB_HAND_EYE_TSAI,
    "park": cv2.CALIB_HAND_EYE_PARK,
    "horaud": cv2.CALIB_HAND_EYE_HORAUD,
    "andreff": cv2.CALIB_HAND_EYE_ANDREFF,
    "daniilidis": cv2.CALIB_HAND_EYE_DANIILIDIS,
}


def calibrate_intrinsics(samples: list[dict], board_shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, list[np.ndarray], list[np.ndarray], float]:
    objpoints = [np.asarray(sample["object_points_m"], dtype=np.float32) for sample in samples]
    imgpoints = [np.asarray(sample["board_corners_px"], dtype=np.float32) for sample in samples]
    height = int(samples[0]["image_size"][1])
    width = int(samples[0]["image_size"][0])
    rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints,
        imgpoints,
        (width, height),
        None,
        None,
    )
    return camera_matrix, dist_coeffs, rvecs, tvecs, float(rms)


def compute_hand_eye(
    samples: list[dict],
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    method: int,
) -> tuple[np.ndarray, np.ndarray, list[float], float]:
    rot_gripper_to_base = []
    trans_gripper_to_base = []
    rot_target_to_cam = []
    trans_target_to_cam = []
    per_sample_target = []
    reproj_errors = []

    for sample in samples:
        corners = np.asarray(sample["board_corners_px"], dtype=np.float32)
        object_points = np.asarray(sample["object_points_m"], dtype=np.float32)
        rvec, tvec = solve_pnp(corners, object_points, camera_matrix, dist_coeffs)
        target_to_cam = rt_to_matrix(rvec, tvec)
        base_to_gripper = pose6_to_matrix(sample["flange_pose"])
        gripper_to_base = invert_transform(base_to_gripper)

        rot_gripper_to_base.append(gripper_to_base[:3, :3])
        trans_gripper_to_base.append(gripper_to_base[:3, 3])
        rot_target_to_cam.append(target_to_cam[:3, :3])
        trans_target_to_cam.append(target_to_cam[:3, 3])
        per_sample_target.append(target_to_cam)
        reproj_errors.append(reprojection_error(object_points, corners, rvec, tvec, camera_matrix, dist_coeffs))

    rot_base_to_camera, trans_base_to_camera = cv2.calibrateHandEye(
        rot_gripper_to_base,
        trans_gripper_to_base,
        rot_target_to_cam,
        trans_target_to_cam,
        method=method,
    )
    base_to_camera = np.eye(4, dtype=np.float64)
    base_to_camera[:3, :3] = rot_base_to_camera
    base_to_camera[:3, 3] = trans_base_to_camera.reshape(3)

    gripper_to_target_candidates = []
    for sample, target_to_cam in zip(samples, per_sample_target):
        base_to_gripper = pose6_to_matrix(sample["flange_pose"])
        gripper_to_target = invert_transform(base_to_gripper) @ base_to_camera @ target_to_cam
        gripper_to_target_candidates.append(gripper_to_target)

    avg_gripper_to_target = average_transforms(gripper_to_target_candidates)
    return base_to_camera, avg_gripper_to_target, reproj_errors, float(np.mean(reproj_errors))


def add_image_size(samples: list[dict], dataset_dir: Path) -> None:
    for sample in samples:
        image_path = dataset_dir / sample["image"]
        image = cv2.imread(str(image_path))
        if image is None:
            raise FileNotFoundError(f"Could not read image {image_path}")
        sample["image_size"] = [image.shape[1], image.shape[0]]


def main() -> int:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest: {manifest_path}")

    manifest = load_yaml(manifest_path)
    samples = manifest["samples"]
    if len(samples) < 5:
        raise SystemExit("At least 5 samples are required for hand-eye calibration")

    add_image_size(samples, dataset_dir)
    board = manifest["board"]
    board_shape = (board["cols"], board["rows"])
    initial_camera_matrix, initial_dist = camera_matrix_and_dist_from_manifest(manifest)
    _ = (initial_camera_matrix, initial_dist)

    camera_matrix, dist_coeffs, _, _, rms = calibrate_intrinsics(samples, board_shape)
    base_to_camera, gripper_to_target, reproj_errors, mean_error = compute_hand_eye(
        samples,
        camera_matrix,
        dist_coeffs,
        METHOD_MAP[args.method],
    )

    output_yaml = Path(args.output_yaml).expanduser().resolve() if args.output_yaml else dataset_dir / "calibration_result.yaml"
    output_json = output_yaml.with_suffix(".json")
    result = {
        "solver": {
            "type": "opencv_calibrateHandEye_eye_to_hand",
            "method": args.method,
        },
        "board": board,
        "camera_intrinsics": {
            "camera_matrix": camera_matrix.tolist(),
            "dist_coeffs": dist_coeffs.reshape(-1).tolist(),
            "rms_reprojection_px": rms,
        },
        "transforms": {
            "T_base_camera": matrix_to_dict(base_to_camera),
            "T_gripper_target": matrix_to_dict(gripper_to_target),
        },
        "metrics": {
            "mean_pnp_reprojection_px": mean_error,
            "per_sample_pnp_reprojection_px": reproj_errors,
            "sample_count": len(samples),
        },
        "notes": {
            "frame_convention": "T_a_b maps points from frame b into frame a",
            "robot_pose_source": "pyAgxArm get_flange_pose()",
        },
    }
    dump_yaml(output_yaml, result)
    dump_json(output_json, result)

    print(f"Saved calibration result to {output_yaml}")
    print(f"Saved calibration result to {output_json}")
    print(f"Camera RMS reprojection error: {rms:.4f} px")
    print(f"Mean solvePnP reprojection error: {mean_error:.4f} px")
    print(f"T_base_camera pose6: {matrix_to_pose6(base_to_camera)}")
    print(f"T_gripper_target pose6: {matrix_to_pose6(gripper_to_target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
