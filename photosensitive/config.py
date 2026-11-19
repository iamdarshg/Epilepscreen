"""Tunable thresholds for photosensitive detection.

Values are documented heuristics aligned with WCAG 2.3 guidance and the
Epilepscreen trigger spec. Every consumer reads thresholds via get() so a
single cfg dict can override any of them at analysis time.
"""
from math import ceil
DEFAULTS: dict = {'flash_delta': 40.0, 'flash_window': 30, 'flash_limit': 3, 'red_floor': 0.25, 'red_window': 15, 'color_threshold': 0.4, 'spatial_contrast': 0.3, 'spatial_threshold': 0.15, 'pattern_move_threshold': 0.1}

def get(cfg: dict | None, key: str) -> float | int:
    """Return cfg[key] if provided, else the default for key."""
    if cfg is not None and key in cfg:
        return cfg[key]
    return DEFAULTS[key]

def thresholds_for_fps(cfg: dict | None, fps: float) -> dict:
    """Use time-based default windows and preserve explicit frame counts."""
    return {**DEFAULTS, 'flash_window': max(1, ceil(fps)), 'red_window': max(1, ceil(fps / 2)), **(cfg or {})}
