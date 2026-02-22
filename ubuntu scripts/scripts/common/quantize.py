import random
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

Bounds = Dict[str, Tuple[float, float]]

@dataclass
class QuantConfig:
    b: int                 # word length (bits)
    seed: int              # RNG seed
    safety_margin_frac: float = 0.05  # expand bounds by this fraction

def inflate_bounds(vmin: float, vmax: float, margin_frac: float) -> Tuple[float, float]:
    if vmax <= vmin:
        return vmin, vmax
    span = vmax - vmin
    pad = margin_frac * span
    return vmin - pad, vmax + pad

def dither_quantize_decode(x: float, vmin: float, vmax: float, b: int, rng: random.Random) -> float:
    """
    Schuchman dither quantization + decoding:
      x_tilde = Q(x + w) - w, where w ~ U[-Δ/2, Δ/2] per component,
      Δ = (vmax - vmin) / (2^b - 1).
    We clamp to [vmin, vmax] after quantization indexing.
    """
    levels = 2 ** b
    if levels <= 1 or vmax <= vmin:
        return float(x)

    delta = (vmax - vmin) / (levels - 1)
    w = rng.uniform(-0.5 * delta, 0.5 * delta)

    q = int(round((float(x) + w - vmin) / delta))
    q = max(0, min(levels - 1, q))

    xq = vmin + q * delta
    return xq - w

def quantize_row(row: Dict[str, float], bounds: Bounds, qc: QuantConfig) -> Dict[str, float]:
    rng = random.Random(qc.seed)
    out = dict(row)
    for k, (vmin, vmax) in bounds.items():
        if k not in row or row[k] is None:
            continue
        vmin_i, vmax_i = inflate_bounds(vmin, vmax, qc.safety_margin_frac)
        out[f"{k}_qd"] = dither_quantize_decode(row[k], vmin_i, vmax_i, qc.b, rng)
    return out
