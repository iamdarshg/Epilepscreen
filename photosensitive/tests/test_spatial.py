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
