"""Orchestrates the detectors into timestamped hazard events.

`analyze_frames` is the whole brain of the project: it takes an iterable of RGB
frames (NumPy arrays, shape H x W x 3), runs five measurements per frame,
groups the flagged frames into runs, and turns each run into a `HazardEvent`
with a start and end time in seconds.

Nothing in here touches a video file, Django or the database, which is why it
can be unit-tested with hand-built arrays of pixels.
"""
from collections.abc import Iterable
from dataclasses import dataclass, field
from math import isfinite
from photosensitive.config import thresholds_for_fps
from photosensitive.spatial import luminance_map, pattern_change, spatial_pattern_score
from photosensitive.temporal import flicker_runs, mean_color_delta, red_coverage

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
        rates = [e.attributes.get('flash_rate', 0.0) for e in self.events if e.kind == 'flicker']
        return round(max(rates), 2) if rates else 0.0

    def summary(self) -> dict:
        """Structured, JSON-ready statistics for the report and the API."""
        return {'frames': self.frame_count, 'fps': round(self.fps, 3), 'duration_s': round(self.duration, 2), 'event_count': len(self.events), 'counts': self.counts, 'risk_flags': self.risk_flags, 'is_safe': self.is_safe, 'max_flash_rate': self.max_flash_rate, 'peak_luminance': round(max(self.luminance_curve), 1) if self.luminance_curve else 0.0, 'min_luminance': round(min(self.luminance_curve), 1) if self.luminance_curve else 0.0, 'peak_pattern_coverage': round(max(self.spatial_curve), 3) if self.spatial_curve else 0.0, 'risky_frame_share': round(sum((1 for flag in self.per_frame_risk if flag)) / len(self.per_frame_risk), 3) if self.per_frame_risk else 0.0}

    def to_dict(self) -> dict:
        payload = self.summary()
        payload['events'] = [{'kind': e.kind, 'start': round(e.start_time, 3), 'end': round(e.end_time, 3), 'attributes': e.attributes} for e in self.events]
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

def analyze_frames(frames: Iterable, fps: float=30.0, cfg: dict | None=None) -> RiskProfile:
    """Analyze RGB frames (H, W, 3) uint8 into timestamped hazard events.

    Raises ValueError if fewer than 2 frames are provided: one frame has no
    predecessor, so nothing can be compared.

    Event times are in seconds: frame index / fps.
    """
    fps = float(fps)
    if not isfinite(fps) or fps <= 0:
        raise ValueError('fps must be finite and positive')
    thresholds = thresholds_for_fps(cfg, fps)
    spatial_contrast = float(thresholds['spatial_contrast'])
    mean_lums: list[float] = []
    reds: list[float] = []
    color_deltas: list[float] = []
    spatial: list[float] = []
    moves: list[float] = []
    prev_frame = None
    prev_lum = None
    n = 0
    for frame in frames:
        lum = luminance_map(frame)
        mean_lums.append(float(lum.mean() * 255.0))
        reds.append(red_coverage(frame))
        spatial.append(spatial_pattern_score(lum, contrast=spatial_contrast))
        if prev_lum is not None:
            color_deltas.append(mean_color_delta(prev_frame, frame))
            moves.append(pattern_change(prev_lum, lum))
        prev_frame, prev_lum = (frame, lum)
        n += 1
    if n < 2:
        raise ValueError('analyze_frames requires at least 2 frames')
    flash_delta = float(thresholds['flash_delta'])
    flash_window = int(thresholds['flash_window'])
    flash_limit = int(thresholds['flash_limit'])
    red_window = int(thresholds['red_window'])
    red_floor = float(thresholds['red_floor'])
    color_thr = float(thresholds['color_threshold'])
    spatial_floor = float(thresholds['spatial_threshold'])
    move_floor = float(thresholds['pattern_move_threshold'])
    deltas = [0.0] + [current - previous for previous, current in zip(mean_lums, mean_lums[1:])]
    flash_runs = flicker_runs(deltas, flash_delta, flash_window, flash_limit)
    flash_flag = [False] * n
    for a, b in flash_runs:
        flash_flag[a:b + 1] = [True] * (b - a + 1)
    red_flag = [False] * n
    for a, b in _group_runs([c >= red_floor for c in reds]):
        if a > 0 and b < n - 1 and (b - a + 1 < 2 * red_window):
            red_flag[a:b + 1] = [True] * (b - a + 1)
    color_flag = [False] + [d >= color_thr for d in color_deltas]
    spatial_flag = [s >= spatial_floor for s in spatial]
    move_flag = [False] + [m >= move_floor for m in moves]
    events: list[HazardEvent] = []

    def _add(kind, flags, attrs_fn):
        for a, b in _group_runs(flags):
            events.append(HazardEvent(kind, a / fps, b / fps, attrs_fn(a, b)))

    def _flash_attrs(a, b):
        """Count peak transitions within one second of the event."""
        indices = [i for i in range(a, b + 1) if abs(deltas[i]) >= flash_delta]
        left = 0
        peak_count = 0
        for right, index in enumerate(indices):
            while index - indices[left] >= fps:
                left += 1
            peak_count = max(peak_count, right - left + 1)
        return {'brightness_diff': round(max((abs(deltas[i]) for i in indices)), 1), 'flash_rate': peak_count, 'flashes_per_second': peak_count // 2}

    def _red_attrs(a, b):
        return {'coverage': round(max(reds[a:b + 1]), 2), 'duration_s': round((b - a + 1) / fps, 2)}

    def _color_attrs(a, b):
        return {'max_delta': round(max(color_deltas[a - 1:b]), 2), 'duration_s': round((b - a + 1) / fps, 2)}

    def _spatial_attrs(a, b):
        coverage = max(spatial[a:b + 1])
        return {'coverage': round(coverage, 2), 'spatial_frequency': round(coverage, 2), 'contrast': round(spatial_contrast, 2), 'duration_s': round((b - a + 1) / fps, 2)}

    def _move_attrs(a, b):
        return {'speed': round(max(moves[a - 1:b]), 3), 'duration_s': round((b - a + 1) / fps, 2)}
    for a, b in flash_runs:
        events.append(HazardEvent('flicker', a / fps, b / fps, _flash_attrs(a, b)))
    _add('red_flash', red_flag, _red_attrs)
    _add('color_transition', color_flag, _color_attrs)
    _add('spatial_pattern', spatial_flag, _spatial_attrs)
    _add('pattern_movement', [m and s for m, s in zip(move_flag, spatial_flag)], _move_attrs)
    events.sort(key=lambda e: (e.start_time, e.kind))
    flags = sorted({e.kind for e in events})
    per_frame_risk = [flash_flag[i] or red_flag[i] or color_flag[i] or spatial_flag[i] or move_flag[i] for i in range(n)]
    return RiskProfile(is_safe=not flags, risk_flags=flags, luminance_curve=mean_lums, spatial_curve=spatial, per_frame_risk=per_frame_risk, events=events, fps=fps, frame_count=n)
