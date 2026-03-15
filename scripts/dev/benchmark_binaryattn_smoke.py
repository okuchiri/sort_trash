#!/usr/bin/env python3
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vision"))
from _local_ultralytics import maybe_enable_binaryattention
from _common import detection_rows, resolve_path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small inference benchmark for YOLO26 vs YOLO26 + BinaryAttention.")
    parser.add_argument("--image", required=True, help="Benchmark image path")
    parser.add_argument("--baseline-model", default="yolo26s.pt", help="Baseline YOLO26 weights")
    parser.add_argument(
        "--experimental-model",
        default="yolo26_binaryattn_s.pt",
        help="Experimental model weights or YAML",
    )
    parser.add_argument("--pretrained-weights", default="", help="Optional warm-start weights when the experimental model is a YAML")
    parser.add_argument("--device", default="0", help="Inference device")
    parser.add_argument("--conf", type=float, default=0.15, help="Confidence threshold")
    parser.add_argument("--warmup", type=int, default=2, help="Warmup iterations per model")
    parser.add_argument("--repeat", type=int, default=10, help="Timed iterations per model")
    parser.add_argument(
        "--output",
        default="docs/binaryattention_smoke_benchmark.md",
        help="Markdown report output path relative to the repo root or absolute path",
    )
    return parser.parse_args()


def summarize_rows(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "none"
    top = sorted(rows, key=lambda row: float(row["confidence"]), reverse=True)[:3]
    return ", ".join(f"{row['class_name']}:{float(row['confidence']):.2f}" for row in top)


def benchmark_model(model: YOLO, image, device: str, conf: float, warmup: int, repeat: int) -> tuple[float, list[dict[str, object]], object]:
    result = None
    for _ in range(max(0, warmup)):
        result = model.predict(source=image, device=device, conf=conf, verbose=False, stream=False)[0]

    latencies: list[float] = []
    for _ in range(max(1, repeat)):
        start = time.perf_counter()
        result = model.predict(source=image, device=device, conf=conf, verbose=False, stream=False)[0]
        latencies.append((time.perf_counter() - start) * 1000.0)
    assert result is not None
    return statistics.mean(latencies), detection_rows(result), result


def write_report(
    output_path: Path,
    image_path: Path,
    baseline_ms: float,
    baseline_rows: list[dict[str, object]],
    experimental_ms: float,
    experimental_rows: list[dict[str, object]],
) -> None:
    delta_ms = experimental_ms - baseline_ms
    speed_ratio = experimental_ms / baseline_ms if baseline_ms > 0 else 0.0
    report = f"""# BinaryAttention Smoke Benchmark

Image: `{image_path}`

| Model | Avg latency (ms) | Top detections |
| --- | ---: | --- |
| YOLO26 baseline | {baseline_ms:.2f} | {summarize_rows(baseline_rows)} |
| YOLO26 + BinaryAttention prototype | {experimental_ms:.2f} | {summarize_rows(experimental_rows)} |

## Notes

- This is a smoke benchmark on one image, not a trained accuracy benchmark.
- The BinaryAttention path uses the experimental local PSA patch and warm-starts from `yolo26s.pt`.
- Latency delta: {delta_ms:+.2f} ms
- Relative latency: {speed_ratio:.2f}x vs baseline
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    image_path = resolve_path(args.image)
    if not image_path.exists():
        raise SystemExit(f"Image file does not exist: {image_path}")
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"Failed to load image: {image_path}")

    baseline_model_path = resolve_path(args.baseline_model)
    if not baseline_model_path.exists():
        raise SystemExit(f"Baseline model does not exist: {baseline_model_path}")
    experimental_model_ref = resolve_path(args.experimental_model)
    pretrained_weights = resolve_path(args.pretrained_weights) if args.pretrained_weights else Path()

    baseline_model = YOLO(str(baseline_model_path))
    baseline_ms, baseline_rows, baseline_result = benchmark_model(
        baseline_model, image, args.device, args.conf, args.warmup, args.repeat
    )

    maybe_enable_binaryattention(__file__, experimental_model_ref, pretrained_weights if args.pretrained_weights else None, verbose=True)
    experimental_model = YOLO(str(experimental_model_ref))
    if args.pretrained_weights and experimental_model_ref.suffix != ".pt":
        experimental_model = experimental_model.load(str(pretrained_weights))
    experimental_ms, experimental_rows, experimental_result = benchmark_model(
        experimental_model, image, args.device, args.conf, args.warmup, args.repeat
    )

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (Path(__file__).resolve().parents[2] / output_path).resolve()
    write_report(output_path, image_path, baseline_ms, baseline_rows, experimental_ms, experimental_rows)

    cv2.imwrite(str(output_path.with_name("binaryattention_baseline_preview.jpg")), baseline_result.plot())
    cv2.imwrite(str(output_path.with_name("binaryattention_experimental_preview.jpg")), experimental_result.plot())
    print(f"Wrote report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
