import numpy as np
import pytest

from photosensitive.analyzer import analyze_frames


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
    # The first flash is only detectable at frame 1 (frame 0 has no predecessor).
    assert ev.start_time == pytest.approx(1 / 30.0)
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
    assert slow_ev.end_time > fast_ev.end_time


def test_too_few_frames_raises():
    with pytest.raises(ValueError):
        analyze_frames([np.zeros((4, 4, 3), dtype=np.uint8)])
