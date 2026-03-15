#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _local_ultralytics import maybe_enable_binaryattention

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO26 trash detector for the unified trash label set.")
    parser.add_argument("--dataset", required=True, help="Ultralytics dataset YAML path")
    parser.add_argument("--model", default="yolo26s.pt", help="Starting model weights")
    parser.add_argument("--pretrained-weights", default="", help="Optional warm-start weights when --model is a YAML file")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0", help="CUDA device id, e.g. 0")
    parser.add_argument("--project", default="runs/detect", help="Training project directory")
    parser.add_argument("--name", default="trash_yolo26s", help="Training run name")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--cache", default="ram", choices=["ram", "disk", "False", "false"], help="Ultralytics cache mode")
    parser.add_argument("--close-mosaic", type=int, default=10, help="Disable mosaic in the last N epochs")
    return parser.parse_args()


def require_cuda(device: str) -> None:
    if str(device) in {"cpu", "mps"}:
        raise SystemExit("GPU is required for training; do not use CPU or MPS")
    if not torch.cuda.is_available():
        raise SystemExit("torch.cuda.is_available() is False; GPU setup is incomplete")


def normalize_cache(value: str) -> str | bool:
    if value.lower() == "false":
        return False
    return value


def resolve_reference(path_str: str) -> str:
    path = Path(path_str).expanduser()
    if path.is_absolute() and path.exists():
        return str(path.resolve())
    cwd_path = (Path.cwd() / path).resolve()
    if cwd_path.exists():
        return str(cwd_path)
    repo_path = (Path(__file__).resolve().parents[2] / path).resolve()
    if repo_path.exists():
        return str(repo_path)
    return path_str


def main() -> int:
    args = parse_args()
    require_cuda(args.device)
    dataset = Path(args.dataset).expanduser().resolve()
    if not dataset.exists():
        raise SystemExit(f"Dataset YAML does not exist: {dataset}")
    model_ref = resolve_reference(args.model)
    pretrained_ref = resolve_reference(args.pretrained_weights) if args.pretrained_weights else ""
    if args.name == "trash_yolo26s" and "binaryattn" in str(model_ref).lower():
        args.name = "trash_yolo26_binaryattn_s"
    maybe_enable_binaryattention(__file__, model_ref, pretrained_ref, verbose=True)

    model = YOLO(model_ref)
    if pretrained_ref:
        model = model.load(pretrained_ref)
    results = model.train(
        data=str(dataset),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        workers=args.workers,
        patience=args.patience,
        cache=normalize_cache(args.cache),
        close_mosaic=args.close_mosaic,
        pretrained=bool(pretrained_ref or Path(str(model_ref)).suffix == ".pt"),
    )
    print(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
