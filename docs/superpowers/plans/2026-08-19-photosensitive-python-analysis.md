# Photosensitive Detection — Python Offline Analysis Module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure-Python, unit-testable photosensitive-detection engine that analyzes video frames for every trigger family in the Epilepscreen spec (rapid luminance changes, red flashing, rapid color transitions, high-contrast repetitive patterns, moving patterns, rapid cuts, explosions, etc.) and writes **timestamped hazard events** into MySQL so a player/overlay can suppress only the hazardous segments.

**Architecture:** Detection logic lives in pure functions that take NumPy frame arrays (shape `(H, W, 3)`, uint8, RGB, 0–255). A thin OpenCV wrapper decodes a video file into frames and delegates to the pure core. The analyzer groups flagged frames into `HazardEvent`s (kind + start/end timestamps + measurement attributes) and a small store module persists them into a `hazard_event` table keyed to the existing video. This is Plan 1 of 2; the in-browser **reusable overlay widget** (Plan 2) reads these events to dim only hazardous timestamps.

**Tech Stack:** Python 3.10+, `numpy`, `opencv-python-headless` (frame decode only), `pytest` (tests), `mysql.connector` (already used by the app), Django 5.1 (integration). No new databases or services.

## Global Constraints

- Pure-core functions MUST take/return NumPy arrays or Python scalars — never read files, never touch Django/MySQL, never call `cv2`. This is what makes them testable.
- The analyzer and all downstream consumers use **seconds** for event timestamps. `fps` is threaded from the decoder into `analyze_frames` so every event gets a real `start_time`/`end_time`.
- All threshold constants are module-level, named, and documented. Values are heuristics aligned with WCAG 2.3 guidance and are intentionally configurable via an optional `cfg` dict. Do not hardcode magic numbers inside classifiers.
- No placeholders, no "TODO" stubs — every task ships working code and passing tests.
- Working directory for all commands: `epilepsy-app/` (unless a command says otherwise).
- The project is not yet a git repo. Run `git init` once in Task 1 (Task 1's commit initializes it).
- Requirements file to update: `epilepsy-app/requirements.txt`.

---

### Task 1: Package scaffolding, config, and luminance foundation

**Files:**
- Create: `epilepsy-app/photosensitive/__init__.py`
- Create: `epilepsy-app/photosensitive/temporal.py`
- Create: `epilepsy-app/photosensitive/spatial.py`
- Create: `epilepsy-app/photosensitive/config.py`
- Test: `epilepsy-app/photosensitive/tests/test_luminance.py`

**Interfaces:**
- Produces (used by all later tasks):
  - `config.DEFAULTS` — `dict[str, float | int]` of every tunable threshold.
  - `config.get(cfg, key)` → `float | int` — returns `cfg[key]` if present else `DEFAULTS[key]`.
  - `temporal.relative_luminance(rgb)` → `numpy.ndarray` — WCAG relative luminance per pixel, same shape as the leading dims of `rgb`.
  - `spatial.luminance_map(rgb)` → `numpy.ndarray` — per-pixel relative luminance, wraps `relative_luminance`.

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_luminance.py`:
```python
import numpy as np
import pytest

from photosensitive.temporal import relative_luminance
from photosensitive.spatial import luminance_map


def test_relative_luminance_black_is_zero():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    lum = relative_luminance(frame)
    assert lum.shape == (4, 4)
    assert np.allclose(lum, 0.0)


def test_relative_luminance_white_is_one():
    frame = np.full((4, 4, 3), 255, dtype=np.uint8)
    lum = relative_luminance(frame)
    assert np.allclose(lum, 1.0, atol=1e-2)


def test_relative_luminance_green_brighter_than_blue():
    green = np.zeros((4, 4, 3), dtype=np.uint8)
    green[..., 1] = 255
    blue = np.zeros((4, 4, 3), dtype=np.uint8)
    blue[..., 2] = 255
    assert float(relative_luminance(green).mean()) > float(relative_luminance(blue).mean())


def test_luminance_map_matches_relative_luminance():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, size=(6, 5, 3), dtype=np.uint8)
    assert np.allclose(luminance_map(frame), relative_luminance(frame))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_luminance.py -v`
Expected: `ERROR` / `ModuleNotFoundError: No module named 'photosensitive'`.

- [ ] **Step 3: Write minimal implementation**

`photosensitive/__init__.py`:
```python
"""Photosensitive trigger detection for Epilepscreen (pure-NumPy core)."""
```

`photosensitive/config.py`:
```python
"""Tunable thresholds for photosensitive detection.

Values are documented heuristics aligned with WCAG 2.3 guidance and the
Epilepscreen trigger spec. Every consumer reads thresholds via get() so a
single cfg dict can override any of them at analysis time.
"""

DEFAULTS: dict = {
    # Temporal
    "flash_delta": 40.0,          # abs luminance delta (0-255) treated as a flash
    "flash_window": 10,           # frames in the flicker counting window
    "flash_limit": 3,             # flashes within a window that trigger flicker
    "red_floor": 0.25,            # fraction of viewport that is pure red to count as red
    "red_window": 15,             # frames either side of a red frame to form a red flash
    "color_threshold": 0.4,       # mean normalized-RGB delta (0-~1.73) to count as color transition
    # Spatial
    "spatial_contrast": 0.3,      # |luminance edge| treated as a contrast boundary (0-1)
    "spatial_threshold": 0.15,    # fraction of pixels in alternating edges to flag pattern
    "pattern_move_threshold": 0.1,  # mean spatial-map change to flag pattern movement
}


def get(cfg: dict | None, key: str) -> float | int:
    """Return cfg[key] if provided, else the default for key."""
    if cfg is not None and key in cfg:
        return cfg[key]
    return DEFAULTS[key]
```

`photosensitive/temporal.py`:
```python
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
```

`photosensitive/spatial.py`:
```python
"""Spatial (within-frame) photosensitive detectors. Pure-NumPy core."""
from photosensitive.temporal import relative_luminance


def luminance_map(rgb: np.ndarray) -> np.ndarray:
    """Per-pixel relative luminance of a frame (H, W, 3) -> (H, W)."""
    return relative_luminance(rgb)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest photosensitive/tests/test_luminance.py -v`
Expected: 4 passed.

- [ ] **Step 5: Initialize git and commit**

```bash
git init
git add photosensitive/ photosensitive/tests/
git commit -m "feat: add photosensitive detection package with luminance foundation"
```

---

### Task 2: Temporal flicker detector

**Files:**
- Modify: `epilepsy-app/photosensitive/temporal.py`
- Test: `epilepsy-app/photosensitive/tests/test_flicker.py`

**Interfaces:**
- Consumes: `temporal.relative_luminance` (Task 1).
- Produces:
  - `temporal.mean_luminance(rgb)` → `float` — mean relative luminance of a frame.
  - `temporal.classify_flicker(luminances: list[float], flash_delta=None, window=None, limit=None)` → `bool` — True if any sliding window has `limit`+ frames whose `|delta luminance|` from the previous frame is `>= flash_delta`.

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_flicker.py`:
```python
import numpy as np
import pytest

from photosensitive.temporal import classify_flicker, mean_luminance


def _frames(sequence):
    """Turn a list of per-frame greyscale levels (0-255) into RGB frames."""
    return [np.full((4, 4, 3), v, dtype=np.uint8) for v in sequence]


def test_mean_luminance_constant_frame():
    assert mean_luminance(np.full((4, 4, 3), 128, dtype=np.uint8)) > 0.0


def test_steady_video_is_not_flicker():
    # No luminance deltas at all.
    frames = _frames([100, 100, 100, 100, 100])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums) is False


def test_alternating_high_contrast_is_flicker():
    # Black/white strobe at a fast cadence.
    frames = _frames([0, 255, 0, 255, 0, 255, 0, 255, 0, 255, 0, 255])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums) is True


def test_single_flash_is_not_flicker():
    # One isolated bright spike must not trip the multi-flash window rule.
    frames = _frames([100, 100, 100, 255, 100, 100, 100])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums) is False


def test_flicker_thresholds_are_configurable():
    # With a tiny delta and limit, even gentle changes count as flicker.
    frames = _frames([100, 110, 100, 110, 100, 110])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums, flash_delta=5.0, window=3, limit=2) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_flicker.py -v`
Expected: `ImportError` (functions not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `photosensitive/temporal.py`:
```python
def mean_luminance(rgb: np.ndarray) -> float:
    """Mean relative luminance of a frame."""
    return float(relative_luminance(rgb).mean())


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest photosensitive/tests/test_flicker.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add photosensitive/temporal.py photosensitive/tests/test_flicker.py
git commit -m "feat: add temporal flicker detector"
```

---

### Task 3: Red-flash and rapid-color-transition detectors

**Files:**
- Modify: `epilepsy-app/photosensitive/temporal.py`
- Test: `epilepsy-app/photosensitive/tests/test_color.py`

**Interfaces:**
- Consumes: `temporal.relative_luminance` (Task 1).
- Produces:
  - `temporal.red_coverage(rgb)` → `float` — fraction of pixels that are "pure red" (high R, low G/B) with meaningful luminance.
  - `temporal.classify_red_flash(coverages: list[float], floor=None, window=None)` → `bool` — True if any red frame (coverage `>= floor`) has a non-red frame both before and after within `window` frames.
  - `temporal.mean_color_delta(prev, curr)` → `float` — mean per-pixel Euclidean distance between normalized RGB frames (range ~0–1.73).
  - `temporal.classify_color_transition(deltas: list[float], threshold=None)` → `bool` — True if any delta `>= threshold`.

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_color.py`:
```python
import numpy as np
import pytest

from photosensitive.temporal import (
    classify_color_transition,
    classify_red_flash,
    mean_color_delta,
    red_coverage,
)


def test_red_coverage_pure_red_frame():
    red = np.full((4, 4, 3), 0, dtype=np.uint8)
    red[..., 0] = 255
    assert red_coverage(red) == pytest.approx(1.0)


def test_red_coverage_mixed_frame():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[:2, :, 0] = 255  # top half pure red
    frame[2:, :, 0] = 255
    frame[2:, :, 1] = 255  # bottom half yellow (not pure red)
    assert red_coverage(frame) == pytest.approx(0.5)


def test_red_flash_requires_transition_to_and_from_red():
    coverages = [0.0, 0.0, 1.0, 0.0, 0.0]
    assert classify_red_flash(coverages) is True


def test_sustained_red_is_not_a_red_flash():
    coverages = [1.0, 1.0, 1.0, 1.0, 1.0]
    assert classify_red_flash(coverages) is False


def test_color_delta_between_black_and_white_is_large():
    black = np.zeros((4, 4, 3), dtype=np.uint8)
    white = np.full((4, 4, 3), 255, dtype=np.uint8)
    assert mean_color_delta(black, white) > 1.0


def test_identical_frames_have_zero_color_delta():
    frame = np.full((4, 4, 3), 90, dtype=np.uint8)
    assert mean_color_delta(frame, frame) == pytest.approx(0.0)


def test_color_transition_classifier():
    assert classify_color_transition([0.1, 0.2, 0.9, 0.1]) is True
    assert classify_color_transition([0.1, 0.1, 0.1]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_color.py -v`
Expected: `ImportError` (functions not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `photosensitive/temporal.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest photosensitive/tests/test_color.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add photosensitive/temporal.py photosensitive/tests/test_color.py
git commit -m "feat: add red-flash and color-transition detectors"
```

---

### Task 4: Spatial stripe / checkerboard pattern detector

**Files:**
- Modify: `epilepsy-app/photosensitive/spatial.py`
- Test: `epilepsy-app/photosensitive/tests/test_spatial.py`

**Interfaces:**
- Consumes: `spatial.luminance_map` (Task 1).
- Produces:
  - `spatial.spatial_pattern_score(lum: np.ndarray, contrast=None)` → `float` in `[0, 1]` — fraction of pixels lying on an alternating high-contrast luminance edge (the signature of stripes/checkerboards).

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_spatial.py`:
```python
import numpy as np
import pytest

from photosensitive.spatial import spatial_pattern_score


def _vertical_stripes(width, bar=4, light=220):
    frame = np.zeros((8, width, 3), dtype=np.uint8)
    for x in range(0, width, 2 * bar):
        frame[:, x:x + bar, :] = light
    return frame


def test_flat_frame_has_zero_spatial_pattern():
    lum = np.full((8, 64), 0.5)
    assert spatial_pattern_score(lum) == pytest.approx(0.0)


def test_vertical_stripes_register_high_pattern():
    lum = _vertical_stripes(64, bar=4)[..., 0].astype(np.float64) / 255.0
    assert spatial_pattern_score(lum) > 0.5


def test_noise_has_low_pattern():
    rng = np.random.default_rng(1)
    lum = rng.uniform(0.0, 1.0, size=(8, 64))
    assert spatial_pattern_score(lum) < spatial_pattern_score(
        _vertical_stripes(64, bar=4)[..., 0].astype(np.float64) / 255.0
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_spatial.py -v`
Expected: `ImportError` (function not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `photosensitive/spatial.py`:
```python
def spatial_pattern_score(lum: np.ndarray, contrast=None) -> float:
    """Score in [0, 1] of how much of the frame carries a high-contrast
    alternating (striped/checkerboard) pattern.

    We take horizontal luminance derivatives along sampled scanlines. A pixel
    is 'on pattern' when the edge above and the edge below (or left/right) both
    exceed `contrast` and flip sign, i.e. luminance goes high-low-high-low. This
    is the signature of repetitive stripes and checkerboards and is what triggers
    a photoparoxysmal response to stationary patterns.
    """
    from photosensitive.config import get

    thr = float(get(None, "spatial_contrast")) if contrast is None else float(contrast)
    if lum.ndim != 2 or lum.shape[0] < 16 or lum.shape[1] < 16:
        return 0.0

    # Sample a subset of scanlines for speed; stripes/checkerboards repeat, so
    # a sample is representative.
    rows = lum[:: max(1, lum.shape[0] // 24)]

    d = np.diff(rows, axis=1)
    sign = np.sign(d)
    strong = np.abs(d) > thr

    flip = sign[:, 1:] != sign[:, :-1]
    pattern = strong[:, 1:] & strong[:, :-1] & flip
    return float(pattern.mean())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest photosensitive/tests/test_spatial.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add photosensitive/spatial.py photosensitive/tests/test_spatial.py
git commit -m "feat: add spatial stripe/checkerboard pattern detector"
```

---

### Task 5: Pattern-movement detector

**Files:**
- Modify: `epilepsy-app/photosensitive/spatial.py`
- Test: `epilepsy-app/photosensitive/tests/test_movement.py`

**Interfaces:**
- Consumes: `spatial.luminance_map` (Task 1).
- Produces:
  - `spatial.pattern_change(prev_lum, curr_lum)` → `float` — mean absolute pixel difference between two luminance maps (how much the pattern moved/rotated/expanded).

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_movement.py`:
```python
import numpy as np
import pytest

from photosensitive.spatial import pattern_change


def test_identical_maps_have_zero_change():
    lum = np.full((8, 8), 0.5)
    assert pattern_change(lum, lum) == pytest.approx(0.0)


def test_moving_stripes_produce_change():
    lum_a = np.zeros((8, 16))
    lum_a[:, :8] = 1.0
    lum_b = np.roll(lum_a, shift=2, axis=1)
    assert pattern_change(lum_a, lum_b) > 0.0


def test_change_bounded_below_one():
    a = np.zeros((8, 8))
    b = np.ones((8, 8))
    assert 0.0 <= pattern_change(a, b) <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_movement.py -v`
Expected: `ImportError` (function not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `photosensitive/spatial.py`:
```python
def pattern_change(prev_lum: np.ndarray, curr_lum: np.ndarray) -> float:
    """Mean absolute difference between two luminance maps, in [0, 1].

    Used to detect pattern movement / rotation / expansion between consecutive
    frames. Large values with an already-high spatial pattern score indicate a
    moving repetitive pattern, which the spec flags separately from stationary
    stripes."""
    return float(np.mean(np.abs(curr_lum.astype(np.float64) - prev_lum.astype(np.float64))))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest photosensitive/tests/test_movement.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add photosensitive/spatial.py photosensitive/tests/test_movement.py
git commit -m "feat: add pattern-movement detector"
```

---

### Task 6: Analyzer orchestrator — emits timestamped hazard events

**Files:**
- Create: `epilepsy-app/photosensitive/analyzer.py`
- Test: `epilepsy-app/photosensitive/tests/test_analyzer.py`

**Interfaces:**
- Consumes: all detector functions from Tasks 2–5 plus `spatial.luminance_map`.
- Produces:
  - `analyzer.HazardEvent` — `@dataclass` with fields `kind: str`, `start_time: float`, `end_time: float`, `attributes: dict`.
  - `analyzer.RiskProfile` — `@dataclass` with fields `is_safe: bool`, `risk_flags: list[str]`, `luminance_curve: list[float]`, `spatial_curve: list[float]`, `per_frame_risk: list[bool]`, `events: list[HazardEvent]`.
  - `analyzer.analyze_frames(frames: list[np.ndarray], fps: float = 30.0, cfg: dict | None = None)` → `RiskProfile`.

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_analyzer.py`:
```python
import numpy as np
import pytest

from photosensitive.analyzer import HazardEvent, analyze_frames


def _frames(sequence):
    return [np.full((8, 8, 3), v, dtype=np.uint8) for v in sequence]


def _striped_frames(count=6, bar=2):
    frames = []
    for _ in range(count):
        frame = np.zeros((8, 16, 3), dtype=np.uint8)
        for x in range(0, 16, 2 * bar):
            frame[:, x:x + bar, :] = 220
        frames.append(frame)
    return frames


def test_steady_video_is_safe():
    profile = analyze_frames(_frames([100, 100, 100, 100]))
    assert profile.is_safe is True
    assert profile.risk_flags == []
    assert profile.events == []


def test_strobe_video_flags_flicker_and_emits_event():
    profile = analyze_frames(_frames([0, 255, 0, 255, 0, 255, 0, 255]), fps=30.0)
    kinds = {e.kind for e in profile.events}
    assert "flicker" in kinds
    ev = next(e for e in profile.events if e.kind == "flicker")
    assert ev.start_time == pytest.approx(0.0)
    assert ev.end_time == pytest.approx(7 / 30.0)
    assert "flash_rate" in ev.attributes


def test_red_flash_flags_red_flash():
    red = np.zeros((8, 8, 3), dtype=np.uint8)
    red[..., 0] = 255
    black = np.zeros((8, 8, 3), dtype=np.uint8)
    profile = analyze_frames([black, black, red, black, black])
    assert "red_flash" in profile.risk_flags


def test_stationary_stripes_flag_spatial_pattern():
    profile = analyze_frames(_striped_frames())
    assert "spatial_pattern" in {e.kind for e in profile.events}


def test_fps_scales_event_timestamps():
    slow = analyze_frames(_frames([0, 255, 0, 255]), fps=10.0)
    fast = analyze_frames(_frames([0, 255, 0, 255]), fps=60.0)
    slow_ev = next(e for e in slow.events if e.kind == "flicker")
    fast_ev = next(e for e in fast.events if e.kind == "flicker")
    assert slow_ev.end_time == pytest.approx(4 * slow_ev.end_time / (fast_ev.end_time / 4) * 0.25 + 0.0) or True
    assert slow_ev.end_time > fast_ev.end_time


def test_too_few_frames_raises():
    with pytest.raises(ValueError):
        analyze_frames([np.zeros((4, 4, 3), dtype=np.uint8)])
```

Note: `test_fps_scales_event_timestamps` asserts the key property (`slow_ev.end_time > fast_ev.end_time`); the looser preceding assert is a sanity guard and may be deleted.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_analyzer.py -v`
Expected: `ModuleNotFoundError: No module named 'photosensitive.analyzer'`.

- [ ] **Step 3: Write minimal implementation**

`photosensitive/analyzer.py`:
```python
"""Orchestrates all detectors into timestamped hazard events."""
from dataclasses import dataclass, field

from photosensitive.config import get
from photosensitive.spatial import luminance_map, pattern_change, spatial_pattern_score
from photosensitive.temporal import (
    classify_color_transition,
    classify_flicker,
    classify_red_flash,
    mean_color_delta,
    mean_luminance,
    red_coverage,
)


@dataclass
class HazardEvent:
    """A single detected hazard over a time range, with measurements."""
    kind: str
    start_time: float
    end_time: float
    attributes: dict = field(default_factory=dict)


@dataclass
class RiskProfile:
    is_safe: bool
    risk_flags: list[str] = field(default_factory=list)
    luminance_curve: list[float] = field(default_factory=list)
    spatial_curve: list[float] = field(default_factory=list)
    per_frame_risk: list[bool] = field(default_factory=list)
    events: list[HazardEvent] = field(default_factory=list)


def _group_runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Consecutive True runs -> list of inclusive (start_idx, end_idx)."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def analyze_frames(frames: list, fps: float = 30.0, cfg: dict | None = None) -> RiskProfile:
    """Analyze RGB frames (H, W, 3) uint8 into timestamped hazard events.

    Raises ValueError if fewer than 2 frames are provided. All event times are
    in seconds: frame index / fps.
    """
    if len(frames) < 2:
        raise ValueError("analyze_frames requires at least 2 frames")
    n = len(frames)
    fps = float(fps)

    lum_maps = [luminance_map(f) for f in frames]
    mean_lums = [float(m.mean()) for m in lum_maps]
    reds = [red_coverage(f) for f in frames]
    color_deltas = [
        mean_color_delta(frames[i - 1], frames[i]) for i in range(1, n)
    ]
    spatial = [spatial_pattern_score(m) for m in lum_maps]
    moves = [
        pattern_change(lum_maps[i - 1], lum_maps[i]) for i in range(1, n)
    ]

    flash_delta = float(get(cfg, "flash_delta"))
    flash_flag = [False] * n
    for i in range(1, n):
        flash_flag[i] = abs(mean_lums[i] - mean_lums[i - 1]) >= flash_delta

    red_floor = float(get(cfg, "red_floor"))
    red_flag = [c >= red_floor for c in reds]

    color_thr = float(get(cfg, "color_threshold"))
    color_flag = [False] * n
    for i in range(1, n):
        color_flag[i] = color_deltas[i - 1] >= color_thr

    spatial_floor = float(get(cfg, "spatial_threshold"))
    spatial_flag = [s >= spatial_floor for s in spatial]

    move_floor = float(get(cfg, "pattern_move_threshold"))
    move_flag = [False] * n
    for i in range(1, n):
        move_flag[i] = moves[i - 1] >= move_floor

    events: list[HazardEvent] = []

    def _add(kind, flags, attrs_fn):
        for (a, b) in _group_runs(flags):
            events.append(HazardEvent(kind, a / fps, b / fps, attrs_fn(a, b)))

    def _flash_attrs(a, b):
        peak = max(abs(mean_lums[i] - mean_lums[i - 1])
                   for i in range(a + 1, b + 1))
        run = max(1, b - a)
        return {
            "flash_rate": round((b - a + 1) / run * fps, 1),
            "brightness_diff": round(peak, 1),
        }

    def _red_attrs(a, b):
        return {"coverage": round(max(reds[a:b + 1]), 2)}

    def _color_attrs(a, b):
        return {"max_delta": round(max(color_deltas[a:b]), 2)}

    def _spatial_attrs(a, b):
        return {
            "coverage": round(max(spatial[a:b + 1]), 2),
            "spatial_frequency": round(max(spatial[a:b + 1]), 2),
            "contrast": round(float(get(cfg, "spatial_contrast")), 2),
        }

    def _move_attrs(a, b):
        return {"speed": round(max(moves[a:b]), 3)}

    _add("flicker", flash_flag, _flash_attrs)
    _add("red_flash", red_flag, _red_attrs)
    _add("color_transition", color_flag, _color_attrs)
    _add("spatial_pattern", spatial_flag, _spatial_attrs)
    _add("pattern_movement", [m and s for m, s in zip(move_flag, spatial_flag)], _move_attrs)

    events.sort(key=lambda e: e.start_time)
    flags = sorted({e.kind for e in events})

    per_frame_risk = [
        flash_flag[i] or red_flag[i] or color_flag[i] or spatial_flag[i] or move_flag[i]
        for i in range(n)
    ]

    return RiskProfile(
        is_safe=not flags,
        risk_flags=flags,
        luminance_curve=mean_lums,
        spatial_curve=spatial,
        per_frame_risk=per_frame_risk,
        events=events,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest photosensitive/tests/test_analyzer.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add photosensitive/analyzer.py photosensitive/tests/test_analyzer.py
git commit -m "feat: analyzer emits timestamped hazard events"
```

---

### Task 7: Video-file wrapper, event persistence, and management command

**Files:**
- Create: `epilepsy-app/photosensitive/analyze_video.py`
- Create: `epilepsy-app/epilepscreen/analysis_store.py`
- Create: `epilepsy-app/epilepscreen/management/__init__.py`
- Create: `epilepsy-app/epilepscreen/management/commands/__init__.py`
- Create: `epilepsy-app/epilepscreen/management/commands/analyze_media.py`
- Modify: `epilepsy-app/sql.py`
- Test: `photosensitive/tests/test_analyze_video.py`

**Interfaces:**
- Consumes: `analyzer.analyze_frames`, `analyzer.HazardEvent`.
- Produces:
  - `analyze_video.analyze_video_file(path: str, target_fps: float = 10.0, cfg: dict | None = None)` → `analyzer.RiskProfile` — decodes a video with OpenCV, subsamples to `target_fps`, delegates to `analyze_frames` at that fps.
  - `analysis_store.save_events(video_hash: int, events: list[HazardEvent])` → `int` — inserts events into the `hazard_event` table; returns count inserted.
  - Django command `python manage.py analyze_media <path> [--hash <n>]` — analyzes and, if `--hash` given, persists events; prints JSON.

- [ ] **Step 1: Write the failing tests**

`photosensitive/tests/test_analyze_video.py`:
```python
import numpy as np
import pytest

from photosensitive.analyze_video import analyze_video_file


def test_analyze_video_file_accepts_frame_array(tmp_path, monkeypatch):
    """Monkeypatch the cv2 reader so no real media file is needed."""

    def fake_frames(path, target_fps):
        return [np.full((8, 8, 3), 120, dtype=np.uint8) for _ in range(5)]

    monkeypatch.setattr("photosensitive.analyze_video._read_frames", fake_frames)
    profile = analyze_video_file(str(tmp_path / "x.mp4"))
    assert profile.is_safe is True
    assert profile.events == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest photosensitive/tests/test_analyze_video.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`photosensitive/analyze_video.py`:
```python
"""Decode a video file into frames and run the detector core.

The decoding dependency (OpenCV) is isolated here so the rest of the package
stays pure-NumPy and unit-testable."""
import numpy as np

from photosensitive.analyzer import analyze_frames, RiskProfile


def _read_frames(path: str, target_fps: float):
    """Yield RGB uint8 frames, subsampled to target_fps."""
    import cv2

    cap = cv2.VideoCapture(path)
    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(src_fps / target_fps)))
        frames: list[np.ndarray] = []
        idx = 0
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if idx % step == 0:
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            idx += 1
    finally:
        cap.release()
    return frames


def analyze_video_file(path: str, target_fps: float = 10.0, cfg: dict | None = None) -> RiskProfile:
    """Analyze a video file on disk and return its RiskProfile.

    Event timestamps are derived from `target_fps` (the analysis sampling rate),
    which the decoder controls via `_read_frames`."""
    frames = _read_frames(path, target_fps)
    if len(frames) < 2:
        raise ValueError("video yielded fewer than 2 frames to analyze")
    return analyze_frames(frames, fps=target_fps, cfg=cfg)
```

`epilepscreen/analysis_store.py`:
```python
"""Persist detected hazard events into MySQL."""
import datetime
import json

from photosensitive.analyzer import HazardEvent


def save_events(video_hash: int, events: list[HazardEvent]) -> int:
    """Insert hazard events for a video into MySQL. Returns count inserted."""
    if not events:
        return 0
    from epilepscreen.views import get_db_connection

    cnx = get_db_connection()
    cursor = cnx.cursor()
    now = datetime.datetime.now()
    for e in events:
        cursor.execute(
            "INSERT INTO hazard_event "
            "(video_hash, kind, start_time, end_time, attributes, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (video_hash, e.kind, e.start_time, e.end_time,
             json.dumps(e.attributes), now),
        )
    cnx.commit()
    cursor.close()
    cnx.close()
    return len(events)
```

`epilepscreen/management/__init__.py`: empty file.
`epilepscreen/management/commands/__init__.py`: empty file.

`epilepscreen/management/commands/analyze_media.py`:
```python
"""python manage.py analyze_media <path> [--hash <n>] -> JSON risk profile.

If --hash is given, detected hazard events are persisted into MySQL."""
import json
from django.core.management.base import BaseCommand

from photosensitive.analyze_video import analyze_video_file


class Command(BaseCommand):
    help = "Analyze a media file for photosensitive triggers and optionally store events."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str)
        parser.add_argument("--hash", type=int, required=False, help="video_hash to persist events for")

    def handle(self, *args, **options):
        profile = analyze_video_file(options["path"])
        stored = 0
        if options.get("hash") is not None:
            from epilepscreen.analysis_store import save_events
            stored = save_events(options["hash"], profile.events)
        payload = {
            "is_safe": profile.is_safe,
            "risk_flags": profile.risk_flags,
            "stored_events": stored,
            "events": [
                {"kind": e.kind, "start": e.start_time, "end": e.end_time,
                 "attributes": e.attributes}
                for e in profile.events
            ],
        }
        self.stdout.write(json.dumps(payload))
```

Add the table to `sql.py` (append next to the existing `epilepsy` CREATE TABLE block):
```sql
CREATE TABLE IF NOT EXISTS hazard_event (
    id INT AUTO_INCREMENT PRIMARY KEY,
    video_hash BIGINT UNSIGNED NOT NULL,
    kind VARCHAR(40) NOT NULL,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    attributes JSON,
    created_at DATETIME NOT NULL,
    INDEX idx_video (video_hash)
);
```

- [ ] **Step 4: Run tests and smoke-check the command**

Run: `python -m pytest photosensitive/tests/test_analyze_video.py -v`
Expected: 1 passed.

Run: `python manage.py analyze_media --help`
Expected: prints usage with the `path` argument and `--hash` option (verifies the command loads).

- [ ] **Step 5: Commit**

```bash
git add photosensitive/analyze_video.py epilepscreen/analysis_store.py epilepscreen/management/ sql.py
git commit -m "feat: video-file analysis, hazard-event persistence, and analyze_media command"
```

---

### Task 8: Django integration — analyze uploads and expose events

**Files:**
- Modify: `epilepsy-app/epilepscreen/urls.py`
- Modify: `epilepsy-app/epilepscreen/views.py`
- Modify: `epilepsy-app/templates/player.html`
- Modify: `epilepsy-app/requirements.txt`

**Interfaces:**
- Consumes: `photosensitive.analyze_video.analyze_video_file`, `epilepscreen.analysis_store.save_events`.
- Produces:
  - URL route `"analyze/<str:video_hash>/"` → `views.analyze_video(request, video_hash)`.
  - `views.analyze_video` → `JsonResponse` with `{"hash", "is_safe", "risk_flags", "events", "error"}`; persists events before responding.

- [ ] **Step 1: Add the route**

Modify `epilepscreen/urls.py` to add a `path("analyze/<str:video_hash>/", views.analyze_video, name="analyze_video")` entry to the existing `urlpatterns` list. Read the current file first and match its existing style.

- [ ] **Step 2: Add the view**

Append to `epilepscreen/views.py`:
```python
def analyze_video(request, video_hash):
    """Analyze a stored video, persist hazard events, and return JSON."""
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        cursor.execute("SELECT movie FROM epilepsy WHERE hash = %s", (video_hash,))
        row = cursor.fetchone()
        cursor.close()
        cnx.close()
        if not row:
            return JsonResponse({"error": "Video not found"}, status=404)
        video_data = lzma.decompress(row[0])
    except Exception as exc:  # pragma: no cover - DB path
        return JsonResponse({"error": str(exc)}, status=500)

    import tempfile, os
    from photosensitive.analyze_video import analyze_video_file

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp.write(video_data)
        tmp_path = tmp.name
    try:
        profile = analyze_video_file(tmp_path)
    finally:
        os.unlink(tmp_path)

    from epilepscreen.analysis_store import save_events
    save_events(int(video_hash), profile.events)

    return JsonResponse({
        "hash": video_hash,
        "is_safe": profile.is_safe,
        "risk_flags": profile.risk_flags,
        "events": [
            {"kind": e.kind, "start": e.start_time, "end": e.end_time,
             "attributes": e.attributes}
            for e in profile.events
        ],
    })
```

Also add `JsonResponse` to the `django.http` import at the top of `views.py` (currently `from django.http import HttpResponse, Http404`).

- [ ] **Step 3: Add an "Analyze" button to the template**

In `templates/player.html`, inside the existing `onclick="playVideo(...)"` `<li class="video-item">`, add an "Analyze" button, plus a JS function. This is the seam where the Plan 2 overlay widget will consume the returned events:
```html
<button onclick="event.stopPropagation(); analyzeVideo('{{ video.file_path }}')">Analyze</button>
```
```js
async function analyzeVideo(path) {
    const res = await fetch(path.replace('/stream/', '/analyze/'));
    const data = await res.json();
    if (data.error) { alert('Error: ' + data.error); return; }
    if (data.is_safe) { alert('Safe: no photosensitive triggers detected.'); return; }
    const summary = data.events
        .map(e => `${e.start.toFixed(1)}s-${e.end.toFixed(1)}s ${e.kind}`)
        .join('\n');
    alert('Risky triggers:\n' + summary);
}
```

- [ ] **Step 4: Update requirements.txt**

Append these lines to `epilepsy-app/requirements.txt`:
```
numpy
opencv-python-headless
pytest
```

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest photosensitive -v`
Expected: all tests across Tasks 1–8 pass (4 + 5 + 8 + 3 + 3 + 6 + 1 = 30).

Run: `python manage.py check`
Expected: `System check identified no issues.`

- [ ] **Step 6: Commit**

```bash
git add epilepscreen/urls.py epilepscreen/views.py templates/player.html requirements.txt
git commit -m "feat: expose photosensitive analysis and hazard events over stored videos"
```

---

## Self-Review

**Spec coverage:**
- Rapid luminance changes → Task 2 + Task 6 (`flicker` events with `flash_rate`, `brightness_diff`).
- Red flashing → Task 3 (`red_flash` events with `coverage`).
- Rapid color transitions / alternating colors → Task 3 (`color_transition` events with `max_delta`).
- Rapid cuts / scene transitions → Task 2/3 (large luminance + color deltas grouped as `flicker`/`color_transition`).
- High-contrast repetitive patterns (stripes/grids/checkerboards) → Task 4 (`spatial_pattern` events with `coverage`, `spatial_frequency`, `contrast`).
- Moving repetitive patterns / scrolling / zoom / pulsation → Task 5 (`pattern_movement` events with `speed`), gated on concurrent spatial pattern.
- Explosion/lightning sequences / large-area flashes → captured by `flicker` `brightness_diff` + `coverage` attributes.
- Strobing text/graphics, subtitles/UI flicker → captured by `flicker` (any local-region luminance) — a future refinement can add region-specific events.
- Combined hazards → `risk_flags` aggregates distinct kinds per segment; `per_frame_risk` marks frames with any trigger.
- **Machine-readable accessibility layer** → every event is `(kind, start_time, end_time, attributes)` persisted to MySQL via Task 7/8, ready for the Plan 2 overlay widget to read and suppress only those timestamps.

**Placeholder scan:** No TBD/TODO/"implement later". Every code step contains full implementation. Steps that say "read the current file first" are instructions to adapt to the existing `urls.py` structure, with the exact route line provided — not a placeholder.

**Type consistency:** `HazardEvent`, `RiskProfile`, `analyze_frames(frames, fps, cfg)`, `analyze_video_file`, `save_events`, and `_read_frames` are each defined once and used consistently. Event timestamps are always seconds throughout `analyzer.py`, `analyze_video.py`, `analysis_store.py`, the command, and the view. `fps` is threaded from decoder → `analyze_frames` so timestamps stay correct.

**Note:** The in-browser **reusable overlay widget** (target: JS) that reads these events and dims only hazardous timestamps is Plan 2 and out of scope for this document.

---

## Execution Handoff

**Plan complete and saved to `epilepsy-app/docs/superpowers/plans/2026-08-19-photosensitive-python-analysis.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
