import numpy as np
import pytest

from photosensitive.temporal import (
    classify_color_transition,
    classify_red_flash,
    mean_color_delta,
    red_coverage,
)


def test_red_coverage_pure_red_frame():
    red = np.full((4, 4, 3), 0, dtype=np.uint8)
    red[..., 0] = 255
    assert red_coverage(red) == pytest.approx(1.0)


def test_red_coverage_mixed_frame():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[:2, :, 0] = 255  # top half pure red
    frame[2:, :, 0] = 255
    frame[2:, :, 1] = 255  # bottom half yellow (not pure red)
    assert red_coverage(frame) == pytest.approx(0.5)


def test_red_flash_requires_transition_to_and_from_red():
    coverages = [0.0, 0.0, 1.0, 0.0, 0.0]
    assert classify_red_flash(coverages) is True


def test_sustained_red_is_not_a_red_flash():
    coverages = [1.0, 1.0, 1.0, 1.0, 1.0]
    assert classify_red_flash(coverages) is False


def test_color_delta_between_black_and_white_is_large():
    black = np.zeros((4, 4, 3), dtype=np.uint8)
    white = np.full((4, 4, 3), 255, dtype=np.uint8)
    assert mean_color_delta(black, white) > 1.0


def test_identical_frames_have_zero_color_delta():
    frame = np.full((4, 4, 3), 90, dtype=np.uint8)
    assert mean_color_delta(frame, frame) == pytest.approx(0.0)


def test_color_transition_classifier():
    assert classify_color_transition([0.1, 0.2, 0.9, 0.1]) is True
    assert classify_color_transition([0.1, 0.1, 0.1]) is False
