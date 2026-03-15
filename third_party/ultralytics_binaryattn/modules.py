from __future__ import annotations

import torch
import torch.nn as nn

from ultralytics.nn.modules.conv import Conv


def ste_sign(x: torch.Tensor) -> torch.Tensor:
    """Straight-through sign quantizer that keeps gradients of the input."""
    signed = torch.where(x >= 0, torch.ones_like(x), -torch.ones_like(x))
    return x + (signed - x).detach()


def fake_symmetric_quantize(x: torch.Tensor, bits: int) -> torch.Tensor:
    """Apply per-head symmetric fake quantization for a prototype low-bit path."""
    if bits >= 16:
        return x
    qmin = -(2 ** (bits - 1))
    qmax = 2 ** (bits - 1) - 1
    scale = x.detach().abs().amax(dim=(-2, -1), keepdim=True).clamp_min(1e-6) / float(qmax)
    quantized = torch.clamp(torch.round(x / scale), qmin, qmax) * scale
    return x + (quantized - x).detach()


class BinaryAttention2d(nn.Module):
    """Prototype BinaryAttention for Ultralytics 2D PSA blocks.

    This keeps the official YOLO26 PSA tensor layout (`B, C, H, W`) but binarizes the
    query/key paths and fake-quantizes the value path to approximate the research idea.
    """

    def __init__(
        self,
        dim: int,
        num_heads: int = 8,
        attn_ratio: float = 0.5,
        value_bits: int = 8,
        use_attn_bias: bool = True,
    ):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.key_dim = int(self.head_dim * attn_ratio)
        self.scale = self.key_dim**-0.5
        self.value_bits = value_bits
        self.use_attn_bias = use_attn_bias

        nh_kd = self.key_dim * num_heads
        hidden = dim + nh_kd * 2
        self.qkv = Conv(dim, hidden, 1, act=False)
        self.proj = Conv(dim, dim, 1, act=False)
        self.pe = Conv(dim, dim, 3, 1, g=dim, act=False)
        self.attn_bias = nn.Parameter(torch.zeros(1, num_heads, 1, 1)) if use_attn_bias else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        bsz, channels, height, width = x.shape
        tokens = height * width
        qkv = self.qkv(x)
        q, k, v = qkv.view(bsz, self.num_heads, self.key_dim * 2 + self.head_dim, tokens).split(
            [self.key_dim, self.key_dim, self.head_dim], dim=2
        )

        q = ste_sign(q)
        k = ste_sign(k)
        v = fake_symmetric_quantize(v, self.value_bits)

        attn = (q.transpose(-2, -1) @ k) * self.scale
        if self.attn_bias is not None:
            attn = attn + self.attn_bias
        attn = attn.softmax(dim=-1)
        out = (v @ attn.transpose(-2, -1)).view(bsz, channels, height, width)
        out = out + self.pe(v.reshape(bsz, channels, height, width))
        return self.proj(out)


class BinaryPSABlock(nn.Module):
    """Drop-in PSABlock replacement that uses BinaryAttention2d."""

    def __init__(
        self,
        c: int,
        attn_ratio: float = 0.5,
        num_heads: int = 4,
        shortcut: bool = True,
        value_bits: int = 8,
    ) -> None:
        super().__init__()
        self.attn = BinaryAttention2d(c, attn_ratio=attn_ratio, num_heads=num_heads, value_bits=value_bits)
        self.ffn = nn.Sequential(Conv(c, c * 2, 1), Conv(c * 2, c, 1, act=False))
        self.add = shortcut

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(x) if self.add else self.attn(x)
        x = x + self.ffn(x) if self.add else self.ffn(x)
        return x


class BinaryPSA(nn.Module):
    """PSA variant that keeps Ultralytics parameter names for partial weight loading."""

    def __init__(self, c1: int, c2: int, e: float = 0.5, value_bits: int = 8):
        super().__init__()
        assert c1 == c2
        self.c = int(c1 * e)
        self.cv1 = Conv(c1, 2 * self.c, 1, 1)
        self.cv2 = Conv(2 * self.c, c1, 1)
        self.attn = BinaryAttention2d(self.c, attn_ratio=0.5, num_heads=max(self.c // 64, 1), value_bits=value_bits)
        self.ffn = nn.Sequential(Conv(self.c, self.c * 2, 1), Conv(self.c * 2, self.c, 1, act=False))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.cv1(x).split((self.c, self.c), dim=1)
        b = b + self.attn(b)
        b = b + self.ffn(b)
        return self.cv2(torch.cat((a, b), 1))


class BinaryC2PSA(nn.Module):
    """C2PSA drop-in replacement that swaps PSA attention for BinaryAttention."""

    def __init__(self, c1: int, c2: int, n: int = 1, e: float = 0.5, value_bits: int = 8):
        super().__init__()
        assert c1 == c2
        self.c = int(c1 * e)
        self.cv1 = Conv(c1, 2 * self.c, 1, 1)
        self.cv2 = Conv(2 * self.c, c1, 1)
        self.m = nn.Sequential(
            *(BinaryPSABlock(self.c, attn_ratio=0.5, num_heads=max(self.c // 64, 1), value_bits=value_bits) for _ in range(n))
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.cv1(x).split((self.c, self.c), dim=1)
        b = self.m(b)
        return self.cv2(torch.cat((a, b), 1))
