"""Spatial (within-frame) photosensitive detectors. Pure-NumPy core."""
import numpy as np

from photosensitive.temporal import relative_luminance


def luminance_map(rgb: np.ndarray) -> np.ndarray:
    """Per-pixel relative luminance of a frame (H, W, 3) -> (H, W)."""
    return relative_luminance(rgb)


def spatial_pattern_score(lum: np.ndarray, contrast=None) -> float:
    """Score in [0, 1] of how much of the frame carries a high-contrast
    alternating (striped/checkerboard) pattern.

    Along sampled scanlines we find high-contrast luminance edges (|derivative|
    > `contrast`). A pixel is 'on pattern' when it lies between two consecutive
    edges whose signs alternate, i.e. luminance goes high-low-high-low. This is
    the signature of repetitive stripes and checkerboards and is what triggers a
    photoparoxysmal response to stationary patterns. Coverage = fraction of
    pixels inside such alternating runs, so a full-field stripe pattern scores
    near 1 while flat or noisy frames score low.
    """
    from photosensitive.config import get

    thr = float(get(None, "spatial_contrast")) if contrast is None else float(contrast)
    if lum.ndim != 2 or lum.shape[0] < 4 or lum.shape[1] < 8:
        return 0.0

    # Sample a subset of scanlines for speed; stripes/checkerboards repeat, so
    # a sample is representative.
    rows = lum[:: max(1, lum.shape[0] // 24)]

    total_pix = 0
    covered = 0
    for row in rows:
        w = len(row)
        total_pix += w
        d = np.diff(row)
        sign = np.sign(d)
        strong = np.abs(d) > thr
        idx = np.nonzero(strong)[0]
        if len(idx) < 2:
            continue
        edge_sign = sign[idx]
        flip = edge_sign[1:] != edge_sign[:-1]
        starts = idx[:-1][flip]
        ends = idx[1:][flip]
        if len(starts):
            covered += int((ends - starts).sum())

    if total_pix == 0:
        return 0.0
    return covered / total_pix


def pattern_change(prev_lum: np.ndarray, curr_lum: np.ndarray) -> float:
    """Mean absolute difference between two luminance maps, in [0, 1].

    Used to detect pattern movement / rotation / expansion between consecutive
    frames. Large values with an already-high spatial pattern score indicate a
    moving repetitive pattern, which the spec flags separately from stationary
    stripes."""
    return float(np.mean(np.abs(curr_lum.astype(np.float64) - prev_lum.astype(np.float64))))
