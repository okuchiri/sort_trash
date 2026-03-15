#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trash_labels import (  # type: ignore[no-redef]
    UNIFIED_TARGET_LABELS,
    normalize_label_text,
    normalize_requested_target_labels,
    resolve_target_name,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare public trash datasets for unified multi-class Ultralytics training.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    remap_yolo = subparsers.add_parser(
        "remap-yolo",
        help="Remap an existing YOLO dataset into the unified trash labels.",
    )
    remap_yolo.add_argument("--source-root", required=True, help="Root directory of the exported YOLO dataset.")
    remap_yolo.add_argument("--output-root", required=True, help="Output directory for the remapped YOLO dataset.")
    remap_yolo.add_argument(
        "--preset",
        default="beverage-containers",
        choices=["beverage-containers", "generic-container", "generic-trash"],
        help="Preset for preset-specific source label exclusions.",
    )
    add_label_filter_args(remap_yolo)

    coco_to_yolo = subparsers.add_parser(
        "coco-to-yolo",
        help="Convert a COCO dataset into the unified trash labels.",
    )
    coco_to_yolo.add_argument("--images-dir", required=True, help="Directory containing the COCO images.")
    coco_to_yolo.add_argument("--annotations-json", required=True, help="COCO annotations JSON path.")
    coco_to_yolo.add_argument("--output-root", required=True, help="Output directory for the converted YOLO dataset.")
    coco_to_yolo.add_argument(
        "--preset",
        default="taco",
        choices=["taco", "generic-container", "generic-trash"],
        help="Preset for preset-specific source label exclusions.",
    )
    coco_to_yolo.add_argument(
        "--split",
        default="train",
        choices=["train", "val", "test"],
        help="Output split name for the COCO conversion.",
    )
    add_label_filter_args(coco_to_yolo)
    return parser.parse_args()


def add_label_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-labels",
        nargs="*",
        default=UNIFIED_TARGET_LABELS,
        help="Unified target labels to keep. Defaults to all eight labels.",
    )
    parser.add_argument(
        "--exclude-labels",
        nargs="*",
        default=[],
        help="Unified target labels to exclude after mapping.",
    )


def build_target_label_order(include_labels: list[str], exclude_labels: list[str]) -> list[str]:
    try:
        included = normalize_requested_target_labels(include_labels, default=UNIFIED_TARGET_LABELS)
        excluded = set(normalize_requested_target_labels(exclude_labels, default=[]))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    labels = [label for label in included if label not in excluded]
    if not labels:
        raise SystemExit("No target labels remain after applying include/exclude filters.")
    return labels


def build_target_names(target_labels: list[str]) -> dict[int, str]:
    return {idx: label for idx, label in enumerate(target_labels)}


def build_target_ids(target_labels: list[str]) -> dict[str, int]:
    return {label: idx for idx, label in enumerate(target_labels)}


def classify_name(name: str, preset: str, allowed_targets: set[str]) -> str | None:
    text = normalize_label_text(name)
    if preset == "beverage-containers" and text in {"glass wine", "glass normal"}:
        return None
    if preset in {"beverage-containers", "taco", "generic-container"} and any(
        token in text for token in ("cap", "lid")
    ):
        return None
    target_name = resolve_target_name(text)
    if target_name is None or target_name not in allowed_targets:
        return None
    return target_name


def load_data_yaml(root: Path) -> dict:
    for candidate in ["data.yaml", "dataset.yaml"]:
        path = root / candidate
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
            if not isinstance(data, dict):
                raise SystemExit(f"Dataset YAML root must be a mapping: {path}")
            return data
    raise SystemExit(f"Could not find data.yaml or dataset.yaml under {root}")


def resolve_split_dir(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def labels_dir_from_images_dir(images_dir: Path) -> Path:
    if images_dir.name == "images":
        return images_dir.parent / "labels"
    if images_dir.parent.name == "images":
        return images_dir.parent.parent / "labels" / images_dir.name
    return images_dir.parent / "labels"


def write_dataset_yaml(output_root: Path, target_labels: list[str]) -> None:
    data = {
        "path": str(output_root.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": build_target_names(target_labels),
    }
    with (output_root / "data.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def ensure_split_dirs(output_root: Path, split: str) -> tuple[Path, Path]:
    images_dir = output_root / "images" / split
    labels_dir = output_root / "labels" / split
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    return images_dir, labels_dir


def remap_yolo_dataset(
    source_root: Path,
    output_root: Path,
    preset: str,
    target_labels: list[str],
) -> None:
    data = load_data_yaml(source_root)
    names = data.get("names")
    target_ids = build_target_ids(target_labels)
    allowed_targets = set(target_labels)
    if isinstance(names, dict):
        source_names = {int(k): str(v) for k, v in names.items()}
    elif isinstance(names, list):
        source_names = {idx: str(name) for idx, name in enumerate(names)}
    else:
        raise SystemExit("Dataset YAML must contain names as a list or mapping.")

    for split in ["train", "val", "test"]:
        if split not in data:
            continue
        images_dir = resolve_split_dir(source_root, str(data[split]))
        labels_dir = labels_dir_from_images_dir(images_dir)
        out_images_dir, out_labels_dir = ensure_split_dirs(output_root, split)

        for image_path in sorted(images_dir.rglob("*")):
            if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
                continue
            rel = image_path.relative_to(images_dir)
            label_path = (labels_dir / rel).with_suffix(".txt")
            if not label_path.exists():
                continue
            remapped_lines: list[str] = []
            for raw_line in label_path.read_text(encoding="utf-8").splitlines():
                parts = raw_line.strip().split()
                if len(parts) != 5:
                    continue
                source_cls = int(float(parts[0]))
                source_name = source_names.get(source_cls)
                if source_name is None:
                    continue
                target_name = classify_name(source_name, preset, allowed_targets)
                if target_name is None:
                    continue
                remapped_lines.append(" ".join([str(target_ids[target_name]), *parts[1:]]))
            if not remapped_lines:
                continue

            target_image_path = out_images_dir / rel
            target_label_path = (out_labels_dir / rel).with_suffix(".txt")
            target_image_path.parent.mkdir(parents=True, exist_ok=True)
            target_label_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image_path, target_image_path)
            target_label_path.write_text("\n".join(remapped_lines) + "\n", encoding="utf-8")

    write_dataset_yaml(output_root, target_labels)


def coco_bbox_to_yolo(bbox: list[float], width: int, height: int) -> tuple[float, float, float, float]:
    x, y, w, h = bbox
    cx = (x + w * 0.5) / width
    cy = (y + h * 0.5) / height
    return cx, cy, w / width, h / height


def convert_coco_dataset(
    images_dir: Path,
    annotations_json: Path,
    output_root: Path,
    preset: str,
    split: str,
    target_labels: list[str],
) -> None:
    target_ids = build_target_ids(target_labels)
    allowed_targets = set(target_labels)
    with annotations_json.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    images = {int(row["id"]): row for row in data.get("images", [])}
    categories = {int(row["id"]): str(row["name"]) for row in data.get("categories", [])}
    grouped: dict[int, list[list[float]]] = defaultdict(list)
    for ann in data.get("annotations", []):
        if ann.get("iscrowd"):
            continue
        category_name = categories.get(int(ann["category_id"]))
        if category_name is None:
            continue
        target_name = classify_name(category_name, preset, allowed_targets)
        if target_name is None:
            continue
        image_info = images.get(int(ann["image_id"]))
        if image_info is None:
            continue
        width = int(image_info["width"])
        height = int(image_info["height"])
        bbox = coco_bbox_to_yolo([float(v) for v in ann["bbox"]], width, height)
        grouped[int(ann["image_id"])].append([float(target_ids[target_name]), *bbox])

    out_images_dir, out_labels_dir = ensure_split_dirs(output_root, split)
    for image_id, labels in grouped.items():
        image_info = images[image_id]
        image_path = images_dir / str(image_info["file_name"])
        if not image_path.exists():
            continue
        target_image_path = out_images_dir / image_info["file_name"]
        target_label_path = (out_labels_dir / image_info["file_name"]).with_suffix(".txt")
        target_image_path.parent.mkdir(parents=True, exist_ok=True)
        target_label_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, target_image_path)
        target_label_path.write_text(
            "\n".join(
                f"{int(label[0])} {label[1]:.6f} {label[2]:.6f} {label[3]:.6f} {label[4]:.6f}" for label in labels
            )
            + "\n",
            encoding="utf-8",
        )

    write_dataset_yaml(output_root, target_labels)


def main() -> int:
    args = parse_args()
    target_labels = build_target_label_order(args.include_labels, args.exclude_labels)
    if args.command == "remap-yolo":
        remap_yolo_dataset(
            source_root=Path(args.source_root).expanduser().resolve(),
            output_root=Path(args.output_root).expanduser().resolve(),
            preset=args.preset,
            target_labels=target_labels,
        )
        return 0
    if args.command == "coco-to-yolo":
        convert_coco_dataset(
            images_dir=Path(args.images_dir).expanduser().resolve(),
            annotations_json=Path(args.annotations_json).expanduser().resolve(),
            output_root=Path(args.output_root).expanduser().resolve(),
            preset=args.preset,
            split=args.split,
            target_labels=target_labels,
        )
        return 0
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
