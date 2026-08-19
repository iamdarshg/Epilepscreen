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
