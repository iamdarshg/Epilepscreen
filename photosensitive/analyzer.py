"""Orchestrates the detectors into timestamped hazard events.

`analyze_frames` is the whole brain of the project: it takes a list of RGB
frames (NumPy arrays, shape H x W x 3), runs five measurements per frame,
groups the flagged frames into runs, and turns each run into a `HazardEvent`
with a start and end time in seconds.

Nothing in here touches a video file, Django or the database, which is why it
can be unit-tested with hand-built arrays of pixels.
"""
from dataclasses import dataclass, field

from photosensitive.config import get
from photosensitive.spatial import luminance_map, pattern_change, spatial_pattern_score
from photosensitive.temporal import (
    mean_color_delta,
    mean_luminance,
    red_coverage,
)


@dataclass
class HazardEvent:
    """A single detected hazard over a time range, with its measurements."""

    kind: str
    start_time: float
    end_time: float
    attributes: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass
class RiskProfile:
    """The result of screening one video."""

    is_safe: bool
    risk_flags: list[str] = field(default_factory=list)
    luminance_curve: list[float] = field(default_factory=list)
    spatial_curve: list[float] = field(default_factory=list)
    per_frame_risk: list[bool] = field(default_factory=list)
    events: list[HazardEvent] = field(default_factory=list)
    fps: float = 30.0
    frame_count: int = 0

    # -- derived numbers ---------------------------------------------------
    @property
    def duration(self) -> float:
        """Seconds of footage actually looked at."""
        return self.frame_count / self.fps if self.fps else 0.0

    @property
    def counts(self) -> dict:
        counts: dict[str, int] = {}
        for event in self.events:
            counts[event.kind] = counts.get(event.kind, 0) + 1
        return counts

    @property
    def max_flash_rate(self) -> float:
        rates = [e.attributes.get('flash_rate', 0.0)
                 for e in self.events if e.kind == 'flicker']
        return round(max(rates), 2) if rates else 0.0

    def summary(self) -> dict:
        """Structured, JSON-ready statistics for the report and the API."""
        return {
            'frames': self.frame_count,
            'fps': round(self.fps, 3),
            'duration_s': round(self.duration, 2),
            'event_count': len(self.events),
            'counts': self.counts,
            'risk_flags': self.risk_flags,
            'is_safe': self.is_safe,
            'max_flash_rate': self.max_flash_rate,
            'peak_luminance': round(max(self.luminance_curve), 1) if self.luminance_curve else 0.0,
            'min_luminance': round(min(self.luminance_curve), 1) if self.luminance_curve else 0.0,
            'peak_pattern_coverage': round(max(self.spatial_curve), 3) if self.spatial_curve else 0.0,
            'risky_frame_share': (
                round(sum(1 for flag in self.per_frame_risk if flag)
                      / len(self.per_frame_risk), 3)
                if self.per_frame_risk else 0.0),
        }

    def to_dict(self) -> dict:
        payload = self.summary()
        payload['events'] = [
            {'kind': e.kind, 'start': round(e.start_time, 3),
             'end': round(e.end_time, 3), 'attributes': e.attributes}
            for e in self.events
        ]
        return payload


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

    Raises ValueError if fewer than 2 frames are provided: one frame has no
    predecessor, so nothing can be compared.

    Event times are in seconds: frame index / fps.
    """
    if len(frames) < 2:
        raise ValueError("analyze_frames requires at least 2 frames")
    n = len(frames)
    fps = float(fps)

    # --- measurements, one pass over the frames ---------------------------
    lum_maps = [luminance_map(f) for f in frames]
    mean_lums = [mean_luminance(f) for f in frames]
    reds = [red_coverage(f) for f in frames]
    color_deltas = [mean_color_delta(frames[i - 1], frames[i]) for i in range(1, n)]
    spatial = [spatial_pattern_score(m, contrast=get(cfg, "spatial_contrast"))
               for m in lum_maps]
    moves = [pattern_change(lum_maps[i - 1], lum_maps[i]) for i in range(1, n)]

    # --- thresholds, all overridable through cfg --------------------------
    flash_delta = float(get(cfg, "flash_delta"))
    red_floor = float(get(cfg, "red_floor"))
    color_thr = float(get(cfg, "color_threshold"))
    spatial_floor = float(get(cfg, "spatial_threshold"))
    move_floor = float(get(cfg, "pattern_move_threshold"))

    # --- per-frame flags --------------------------------------------------
    # A flash is a jump in average brightness between neighbouring frames.
    # Frame 0 can never be flagged: there is nothing before it to compare to.
    deltas = [0.0] + [abs(mean_lums[i] - mean_lums[i - 1]) for i in range(1, n)]
    flash_flag = [i > 0 and deltas[i] >= flash_delta for i in range(n)]
    red_flag = [c >= red_floor for c in reds]
    color_flag = [False] + [d >= color_thr for d in color_deltas]
    spatial_flag = [s >= spatial_floor for s in spatial]
    move_flag = [False] + [m >= move_floor for m in moves]

    events: list[HazardEvent] = []

    def _add(kind, flags, attrs_fn):
        for (a, b) in _group_runs(flags):
            events.append(HazardEvent(kind, a / fps, b / fps, attrs_fn(a, b)))

    def _flash_attrs(a, b):
        """Brightness change per frame inside the run, plus a flash rate.

        `flash_rate` counts brightness transitions per second (a full
        on/off/on flicker is two transitions); `flashes_per_second` is the
        WCAG-style figure you would compare against a 3-per-second limit.
        """
        peak = max(deltas[a:b + 1])
        span = max(1e-6, (b - a + 1) / fps)
        transitions = sum(1 for i in range(a, b + 1) if flash_flag[i])
        rate = transitions / span
        return {
            'brightness_diff': round(peak, 1),
            'flash_rate': round(rate, 1),
            'flashes_per_second': round(rate / 2, 1),
        }

    def _red_attrs(a, b):
        return {
            'coverage': round(max(reds[a:b + 1]), 2),
            'duration_s': round((b - a + 1) / fps, 2),
        }

    def _color_attrs(a, b):
        # color_deltas[k] is the transition INTO frame k+1, so a run over
        # frames a..b maps to indices a-1..b-1 (a >= 1, so never empty).
        return {
            'max_delta': round(max(color_deltas[a - 1:b]), 2),
            'duration_s': round((b - a + 1) / fps, 2),
        }

    def _spatial_attrs(a, b):
        coverage = max(spatial[a:b + 1])
        return {
            'coverage': round(coverage, 2),
            'spatial_frequency': round(coverage, 2),
            'contrast': round(spatial_contrast, 2),
            'duration_s': round((b - a + 1) / fps, 2),
        }

    def _move_attrs(a, b):
        return {
            'speed': round(max(moves[a - 1:b]), 3),
            'duration_s': round((b - a + 1) / fps, 2),
        }

    spatial_contrast = float(get(cfg, "spatial_contrast"))

    _add("flicker", flash_flag, _flash_attrs)
    _add("red_flash", red_flag, _red_attrs)
    _add("color_transition", color_flag, _color_attrs)
    _add("spatial_pattern", spatial_flag, _spatial_attrs)
    _add("pattern_movement",
         [m and s for m, s in zip(move_flag, spatial_flag)], _move_attrs)

    events.sort(key=lambda e: (e.start_time, e.kind))
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
        fps=fps,
        frame_count=n,
    )