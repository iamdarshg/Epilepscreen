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
    mean_lums = [mean_luminance(f) for f in frames]
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
        # Transitions into frames a..b: mean_lums[i] - mean_lums[i-1], i in [a, b].
        # Frame 0 is never flagged, so a >= 1 and the range is non-empty.
        peak = max(abs(mean_lums[i] - mean_lums[i - 1])
                   for i in range(max(1, a), min(n, b + 1)))
        run = max(1, b - a)
        return {
            "flash_rate": round((b - a + 1) / run * fps, 1),
            "brightness_diff": round(peak, 1),
        }

    def _red_attrs(a, b):
        return {"coverage": round(max(reds[a:b + 1]), 2)}

    def _color_attrs(a, b):
        # color_deltas[k] is the transition INTO frame k+1, so a run over
        # frames a..b maps to indices a-1..b-1 (a >= 1, never empty).
        return {"max_delta": round(max(color_deltas[a - 1:b]), 2)}

    def _spatial_attrs(a, b):
        return {
            "coverage": round(max(spatial[a:b + 1]), 2),
            "spatial_frequency": round(max(spatial[a:b + 1]), 2),
            "contrast": round(float(get(cfg, "spatial_contrast")), 2),
        }

    def _move_attrs(a, b):
        # moves[k] is the change into frame k+1, so a run over frames a..b maps
        # to indices a-1..b-1.
        return {"speed": round(max(moves[a - 1:b]), 3)}

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
