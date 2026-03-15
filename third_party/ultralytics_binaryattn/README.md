# ultralytics_binaryattn

This directory contains a local prototype of `YOLO26 + BinaryAttention` for the `sort_trash` project.

## Source

- Paper: `BinaryAttention: One-Bit QK-Attention for Vision and Diffusion Transformers`
- Reference repository: `https://github.com/EdwardChasel/BinaryAttention`

## Scope

This is not a full fork of the upstream research code. It only adapts the core idea to the PSA path used by Ultralytics YOLO26:

- binarize `Q` and `K` with a straight-through sign estimator
- add a learnable attention bias term
- fake-quantize `V` to 8-bit during the attention path

The implementation is wired as a local experiment patch. It replaces the PSA attention classes inside Ultralytics at runtime when a model path or config path contains `binaryattn`.

## Limitations

- This prototype uses standard PyTorch matmul, not a custom XNOR/popcount kernel.
- It is intended for finetuning from `yolo26s.pt`, not for direct drop-in replacement without retraining.
- It only targets the YOLO26 `C2PSA` branch used in the default detection model.
