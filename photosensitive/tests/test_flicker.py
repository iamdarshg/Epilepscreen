import numpy as np

from photosensitive.temporal import classify_flicker, mean_luminance


def _frames(sequence):
    """Turn a list of per-frame greyscale levels (0-255) into RGB frames."""
    return [np.full((4, 4, 3), v, dtype=np.uint8) for v in sequence]


def test_mean_luminance_constant_frame():
    assert mean_luminance(np.full((4, 4, 3), 128, dtype=np.uint8)) > 0.0


def test_steady_video_is_not_flicker():
    frames = _frames([100, 100, 100, 100, 100])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums) is False


def test_alternating_high_contrast_is_flicker():
    frames = _frames([0, 255, 0, 255, 0, 255, 0, 255, 0, 255, 0, 255])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums) is True


def test_single_flash_is_not_flicker():
    frames = _frames([100, 100, 100, 255, 100, 100, 100])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums) is False


def test_flicker_thresholds_are_configurable():
    frames = _frames([100, 110, 100, 110, 100, 110])
    lums = [mean_luminance(f) for f in frames]
    assert classify_flicker(lums, flash_delta=5.0, window=3, limit=2) is True
