"""Temporal (frame-to-frame) photosensitive detectors. Pure-NumPy core."""
import numpy as np


def relative_luminance(rgb: np.ndarray) -> np.ndarray:
    """WCAG relative luminance of an sRGB frame (H, W, 3) -> (H, W)."""
    srgb = np.clip(rgb.astype(np.float64) / 255.0, 0.0, 1.0)
    linear = np.where(
        srgb <= 0.04045,
        srgb / 12.92,
        ((srgb + 0.055) / 1.055) ** 2.4,
    )
    coeffs = np.array([0.2126, 0.7152, 0.0722])
    return linear @ coeffs


def mean_luminance(rgb: np.ndarray) -> float:
    """Mean perceived luminance of a frame, in 0-255 (matches config units)."""
    return float(relative_luminance(rgb).mean() * 255.0)


def classify_flicker(luminances: list[float], flash_delta=None, window=None, limit=None) -> bool:
    """True if any sliding window of `window` frames contains `limit` or more
    frames whose absolute luminance delta from the previous frame is at least
    `flash_delta`. Approximates the WCAG '3+ flashes in a second' general-flash rule."""
    from photosensitive.config import get

    delta_t = float(get(None, "flash_delta")) if flash_delta is None else float(flash_delta)
    win = int(get(None, "flash_window")) if window is None else int(window)
    lim = int(get(None, "flash_limit")) if limit is None else int(limit)

    deltas = [
        abs(luminances[i] - luminances[i - 1])
        for i in range(1, len(luminances))
    ]
    for i in range(len(deltas) - win + 1):
        if sum(1 for d in deltas[i:i + win] if d >= delta_t) >= lim:
            return True
    return False


def red_coverage(rgb: np.ndarray) -> float:
    """Fraction of pixels that read as pure saturated red with real luminance.

    A pixel is 'red' when R dominates G and B, both channels are low relative
    to R, and the pixel is not black (so a dark frame never counts as red).
    """
    r = rgb[..., 0].astype(np.float64)
    g = rgb[..., 1].astype(np.float64)
    b = rgb[..., 2].astype(np.float64)
    total = r + g + b
    with np.errstate(divide="ignore", invalid="ignore"):
        r_frac = np.where(total > 0, r / np.maximum(total, 1.0), 0.0)
    red = (r_frac >= 0.8) & (r > 60) & (g < 120) & (b < 120)
    return float(red.mean())


def classify_red_flash(coverages: list[float], floor=None, window=None) -> bool:
    """True if a red frame (coverage >= floor) is preceded and followed by a
    non-red frame within `window` frames. Captures the WCAG 'transition to and
    from red within ~0.5s' red-flash rule."""
    from photosensitive.config import get

    flr = float(get(None, "red_floor")) if floor is None else float(floor)
    win = int(get(None, "red_window")) if window is None else int(window)

    red = [c >= flr for c in coverages]
    n = len(red)
    for j in range(n):
        if not red[j]:
            continue
        before = any(not red[k] for k in range(max(0, j - win), j))
        after = any(not red[k] for k in range(j + 1, min(n, j + win + 1)))
        if before and after:
            return True
    return False


def mean_color_delta(prev: np.ndarray, curr: np.ndarray) -> float:
    """Mean per-pixel Euclidean distance between two normalized RGB frames."""
    a = prev.astype(np.float64) / 255.0
    b = curr.astype(np.float64) / 255.0
    return float(np.mean(np.linalg.norm(b - a, axis=-1)))


def classify_color_transition(deltas: list[float], threshold=None) -> bool:
    """True if any frame-to-frame color delta meets or exceeds the threshold."""
    from photosensitive.config import get

    thr = float(get(None, "color_threshold")) if threshold is None else float(threshold)
    return any(d >= thr for d in deltas)
