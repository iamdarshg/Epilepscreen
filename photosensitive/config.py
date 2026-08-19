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
