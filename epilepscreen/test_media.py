"""Tests for media helpers. No database needed."""
import os
import tempfile
import unittest

import cv2
import numpy as np

from epilepscreen.media import (
    BUILTIN_CATEGORIES,
    content_type_for,
    is_audio_content,
    normalize_category,
    probe_media,
    suggest_category,
)


class ContentTypeTests(unittest.TestCase):
    def test_video_extension(self):
        self.assertEqual(content_type_for("clip.mp4"), "video/mp4")

    def test_lossless_audio_extension(self):
        self.assertEqual(content_type_for("song.flac"), "audio/flac")
        self.assertEqual(content_type_for("song.wav"), "audio/wav")

    def test_lossy_audio_extension(self):
        self.assertEqual(content_type_for("song.mp3"), "audio/mpeg")

    def test_unknown_extension_falls_back_to_uploaded_type(self):
        self.assertEqual(content_type_for("clip.xyz", "video/webm"),
                         "video/webm")

    def test_unknown_everything_falls_back_to_octet_stream(self):
        self.assertEqual(content_type_for("clip.xyz"),
                         "application/octet-stream")

    def test_is_audio_content(self):
        self.assertTrue(is_audio_content("audio/flac"))
        self.assertFalse(is_audio_content("video/mp4"))
        self.assertFalse(is_audio_content(None))


class CategoryTests(unittest.TestCase):
    def test_builtin_categories_cover_the_kinds(self):
        for name in ("Short", "Movie", "Music Video", "Music", "Other"):
            self.assertIn(name, BUILTIN_CATEGORIES)

    def test_normalize_blank_is_none(self):
        self.assertIsNone(normalize_category(""))
        self.assertIsNone(normalize_category("   "))
        self.assertIsNone(normalize_category(None))

    def test_normalize_truncates_and_strips(self):
        self.assertEqual(normalize_category("  My Cat  "), "My Cat")
        self.assertEqual(len(normalize_category("x" * 100)), 40)

    def test_user_defined_category_passes_through(self):
        self.assertEqual(normalize_category("Skate Edit"), "Skate Edit")

    def test_portrait_suggests_short(self):
        self.assertEqual(suggest_category(width=720, height=1280), "Short")

    def test_long_landscape_suggests_movie(self):
        self.assertEqual(
            suggest_category(duration_s=3600, width=1920, height=1080),
            "Movie")

    def test_music_keywords_suggest_music_video(self):
        self.assertEqual(
            suggest_category(title="Artist - Song (Official Video)"),
            "Music Video")

    def test_audio_only_suggests_music(self):
        self.assertEqual(suggest_category(audio_only=True), "Music")

    def test_plain_clip_suggests_other(self):
        self.assertEqual(
            suggest_category(duration_s=90, width=1280, height=720,
                             title="vlog ep 3"),
            "Other")


class ProbeTests(unittest.TestCase):
    def _make_clip(self, directory, width=160, height=120, frames=12):
        path = os.path.join(directory, "clip.mp4")
        writer = cv2.VideoWriter(
            path, cv2.VideoWriter_fourcc(*"mp4v"), 12, (width, height))
        if not writer.isOpened():
            self.skipTest("mp4v encoder unavailable in this OpenCV build")
        try:
            for _ in range(frames):
                writer.write(np.zeros((height, width, 3), dtype=np.uint8))
        finally:
            writer.release()
        return path

    def test_probe_reads_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = probe_media(self._make_clip(tmp))
            self.assertIsNotNone(info)
            self.assertEqual(info["width"], 160)
            self.assertEqual(info["height"], 120)
            self.assertAlmostEqual(info["duration_s"], 1.0, places=1)

    def test_probe_of_non_video_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.txt")
            with open(path, "w") as fh:
                fh.write("not a video")
            self.assertIsNone(probe_media(path))

    def test_probe_of_missing_file_is_none(self):
        self.assertIsNone(probe_media("/no/such/file.mp4"))
