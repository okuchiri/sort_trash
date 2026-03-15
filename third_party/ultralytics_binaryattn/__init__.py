from __future__ import annotations

from ultralytics.nn import tasks
from ultralytics.nn import modules as ultralytics_modules
from ultralytics.nn.modules import block

from .modules import BinaryAttention2d, BinaryC2PSA, BinaryPSA, BinaryPSABlock

_PATCHED = False


def register_binaryattention(verbose: bool = True) -> bool:
    """Patch Ultralytics PSA attention modules in-place for binary-attention experiments."""
    global _PATCHED
    if _PATCHED:
        return False

    replacements = {
        "Attention": BinaryAttention2d,
        "PSABlock": BinaryPSABlock,
        "PSA": BinaryPSA,
        "C2PSA": BinaryC2PSA,
        "BinaryAttention2d": BinaryAttention2d,
        "BinaryPSABlock": BinaryPSABlock,
        "BinaryPSA": BinaryPSA,
        "BinaryC2PSA": BinaryC2PSA,
    }
    for name, obj in replacements.items():
        setattr(block, name, obj)
        setattr(tasks, name, obj)
        setattr(ultralytics_modules, name, obj)

    _PATCHED = True
    if verbose:
        print("BinaryAttention patch enabled for Ultralytics YOLO26 PSA modules.")
    return True


__all__ = [
    "BinaryAttention2d",
    "BinaryC2PSA",
    "BinaryPSA",
    "BinaryPSABlock",
    "register_binaryattention",
]
