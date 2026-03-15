# YOLO26 BinaryAttention Experiment

This document describes the local `YOLO26 + BinaryAttention` experiment path for `sort_trash`.

## Reference

- Paper: [BinaryAttention: One-Bit QK-Attention for Vision and Diffusion Transformers](https://arxiv.org/abs/2603.09582)
- Reference implementation: <https://github.com/EdwardChasel/BinaryAttention>

## Local implementation scope

This repository does not vendor the whole upstream research code. Instead it adapts the main idea to the PSA branch used by Ultralytics YOLO26:

- binarize `Q` and `K`
- add a learnable attention bias
- fake-quantize `V` to 8-bit

The runtime patch is only enabled when the model reference contains `binaryattn`, or when `SORT_TRASH_BINARYATTN=1` is set.

## Unified target labels

The project now uses one shared internal label space for both runtime and training data:

- `bottle`
- `cup`
- `drink_can`
- `paper`
- `cardboard`
- `plastic_bag`
- `food_waste`
- `other_trash`

## Recommended public datasets

### Primary dataset

- `Beverage Containers`
- Why:
  - already focuses on bottle-like and cup-like containers
  - useful as a clean subset for the unified mapping pipeline
  - can be exported directly in YOLO format

Suggested remap:

- `bottle`: `bottle-glass`, `bottle-plastic`, `gym bottle`
- `cup`: `cup-disposable`, `cup-handle`, `glass-mug`
- Exclude in phase one: `glass-wine`, `glass-normal`

### Secondary dataset

- `TACO`
- Why:
  - useful for cluttered litter backgrounds, occlusions, and messy object poses
  - good second-stage finetune after the main container dataset

Suggested remap:

- `bottle`: any category containing `bottle`, but exclude `cap`
- `cup`: categories containing `cup` or `mug`
- `drink_can`: categories containing `can`, but exclude `lid` / `cap` / trash-can style labels
- `paper` / `cardboard` / `plastic_bag` / `food_waste` / `other_trash`: mapped by the shared runtime label rules when source names match
- Exclude: labels that remain unmapped or are intentionally filtered out

## Dataset preparation

### Remap Beverage Containers YOLO export

```bash
python scripts/vision/prepare_public_bottle_cup_dataset.py remap-yolo \
  --source-root /path/to/beverage_containers_yolo \
  --output-root /path/to/public_trash_yolo \
  --preset beverage-containers \
  --include-labels bottle cup drink_can
```

### Convert TACO COCO annotations

```bash
python scripts/vision/prepare_public_bottle_cup_dataset.py coco-to-yolo \
  --images-dir /path/to/taco/images \
  --annotations-json /path/to/taco/annotations.json \
  --output-root /path/to/taco_trash_yolo \
  --preset taco \
  --split train
```

The script now emits `data.yaml` with unified class names in shared label order. Use [`config/datasets/bottle_cup_public.example.yaml`](../config/datasets/bottle_cup_public.example.yaml) as the template when you need a hand-written dataset YAML.

## Training

### Build the experiment model from YAML and warm-start from YOLO26s

```bash
python scripts/vision/train_yolo11_trash.py \
  --dataset /path/to/public_trash_yolo/data.yaml \
  --model config/models/yolo26s_binaryattn.yaml \
  --pretrained-weights yolo26s.pt \
  --name trash_yolo26_binaryattn_s
```

### Optional second-stage finetune on TACO remap

```bash
python scripts/vision/train_yolo11_trash.py \
  --dataset /path/to/taco_trash_yolo/data.yaml \
  --model config/models/yolo26s_binaryattn.yaml \
  --pretrained-weights runs/detect/trash_yolo26_binaryattn_s/weights/best.pt \
  --name trash_yolo26_binaryattn_s_taco_ft
```

## Runtime

### One-click launcher

```bash
MODEL_VARIANT=binaryattn \
BINARYATTN_MODEL_PATH=/absolute/path/to/yolo26_binaryattn_s.pt \
bash run_project.sh detect2d
```

### Pipeline config

- Runtime example: [`config/sort_trash_pipeline.binaryattn.example.yaml`](../config/sort_trash_pipeline.binaryattn.example.yaml)
- Dev/smoke config: [`config/sort_trash_pipeline.binaryattn.dev.yaml`](../config/sort_trash_pipeline.binaryattn.dev.yaml)

## Smoke benchmark

- Report: [`docs/binaryattention_smoke_benchmark.md`](./binaryattention_smoke_benchmark.md)
- Current smoke result on the local test image:
  - baseline `yolo26s.pt`: `9.26 ms`
  - prototype `yolo26_binaryattn_s.pt`: `9.87 ms`
  - detection quality is not directly comparable yet because the BinaryAttention path has only been warm-started, not finetuned

## Notes

- This prototype is expected to be finetuned, not used as a zero-shot replacement for `yolo26s.pt`.
- The current implementation keeps standard PyTorch attention math, so the speed gain is algorithmic/prototyping only, not a bit-kernel benchmark.
