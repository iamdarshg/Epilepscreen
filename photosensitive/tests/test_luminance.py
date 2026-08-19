import numpy as np

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
