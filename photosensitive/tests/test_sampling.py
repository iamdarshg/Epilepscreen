"""Sampling-rate correctness and reporting tests for the video decoder.

These build a tiny real mp4 with OpenCV (skipping if the encoder is missing)
so the frame-subsampling logic and the timestamps it produces are checked end
to end, not just on hand-made arrays.
"""
import os
import tempfile
import unittest

import numpy as np

from photosensitive.analyze_video import (
    analyze_video_file,
    effective_fps,
    source_frame_rate,
)


def write_clip(path, frames, fps, size=(96, 72)):
    import cv2

    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, size)
    if not writer.isOpened():
        return False
    try:
        for value in frames:
            frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            frame[:, :] = value
            writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    return True


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'clip.mp4')

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_frame_rate_is_read_from_the_container(self):
        if not write_clip(self.path, [0] * 8, 24):
            self.skipTest('mp4v encoder unavailable')
        self.assertAlmostEqual(source_frame_rate(self.path), 24.0, places=1)

    def test_effective_fps_divides_by_the_sampling_step(self):
        if not write_clip(self.path, [0] * 16, 30):
            self.skipTest('mp4v encoder unavailable')
        # 30 fps sampled at 15 fps reads every second frame -> 15 fps effective.
        self.assertAlmostEqual(effective_fps(self.path, 15), 15.0, places=1)
        # Asking for 10 fps from a 30 fps file steps by 3.
        self.assertAlmostEqual(effective_fps(self.path, 10), 10.0, places=1)

    def test_alternating_frames_are_not_lost_to_aliasing(self):
        """A 15 fps on/off clip sampled at 15 fps must still read as a flicker."""
        if not write_clip(self.path, [255 if i % 2 else 0 for i in range(20)], 15):
            self.skipTest('mp4v encoder unavailable')
        profile = analyze_video_file(self.path, target_fps=15)
        self.assertIn('flicker', profile.risk_flags)
        self.assertGreater(profile.event_count if hasattr(profile, 'event_count')
                           else len(profile.events), 0)

    def test_event_times_stay_inside_the_analysed_span(self):
        if not write_clip(self.path, [255 if i % 2 else 0 for i in range(20)], 15):
            self.skipTest('mp4v encoder unavailable')
        profile = analyze_video_file(self.path, target_fps=15)
        for event in profile.events:
            self.assertGreaterEqual(event.start_time, 0.0)
            self.assertLessEqual(event.end_time, profile.duration + 0.001)

    def test_calm_clip_is_safe_and_reports_its_length(self):
        if not write_clip(self.path, list(range(40, 60)), 20):
            self.skipTest('mp4v encoder unavailable')
        profile = analyze_video_file(self.path, target_fps=20)
        self.assertTrue(profile.is_safe)
        self.assertEqual(profile.events, [])
        summary = profile.summary()
        self.assertGreater(summary['frames'], 10)
        self.assertGreater(summary['duration_s'], 0.5)

    def test_unreadable_file_raises_value_error(self):
        path = os.path.join(self.tmp.name, 'broken.mp4')
        with open(path, 'wb') as handle:
            handle.write(b'not a video at all')
        with self.assertRaises(ValueError):
            analyze_video_file(path)


if __name__ == '__main__':
    unittest.main()