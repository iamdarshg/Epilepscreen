"""Tests for bulk ingest. File discovery needs no DB; inserts are mocked."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import mysql.connector
from django.test import TestCase

from epilepscreen.management.commands.ingest_media import (
    ingest_file,
    iter_media_files,
)


class DiscoverTests(TestCase):
    def _make_tree(self, root):
        files = ["a.mp4", "b.mp3", "c.txt", os.path.join("sub", "d.mkv"),
                 os.path.join("sub", "e.txt")]
        for name in files:
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"data")

    def test_non_recursive_lists_known_types_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_tree(tmp)
            found = {os.path.basename(p)
                     for p in iter_media_files(tmp)}
            self.assertEqual(found, {"a.mp4", "b.mp3"})

    def test_recursive_descends(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_tree(tmp)
            found = {os.path.basename(p)
                     for p in iter_media_files(tmp, recursive=True)}
            self.assertEqual(found, {"a.mp4", "b.mp3", "d.mkv"})

    def test_extension_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_tree(tmp)
            found = list(iter_media_files(tmp, recursive=True,
                                          extensions=["mp3"]))
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].endswith("b.mp3"))


class IngestFileTests(TestCase):
    def _write(self, directory, name, data=b"fake-bytes"):
        path = os.path.join(directory, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _mock_cnx(self):
        mock_cnx = MagicMock()
        mock_cnx.cursor.return_value = MagicMock()
        return mock_cnx

    def test_insert_uses_detected_type_and_fixed_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "song.flac")
            mock_cnx = self._mock_cnx()
            with patch("epilepscreen.views.get_db_connection",
                       return_value=mock_cnx):
                hash_val, title, status = ingest_file(path, category="Music")
                self.assertEqual(status, "stored")
                self.assertEqual(title, "song")
                _sql, params = mock_cnx.cursor.return_value.execute.call_args[0]
                self.assertEqual(params[0], hash_val)
                self.assertEqual(params[3], "Music")
                self.assertEqual(params[4], "audio/flac")

    def test_content_hash_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "clip.mp4")
            with patch("epilepscreen.views.get_db_connection",
                       return_value=self._mock_cnx()):
                first = ingest_file(path)
                with patch("epilepscreen.views.get_db_connection",
                           return_value=self._mock_cnx()):
                    second = ingest_file(path)
                self.assertEqual(first[0], second[0])

    def test_duplicate_primary_key_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "clip.mp4")
            mock_cnx = self._mock_cnx()
            mock_cnx.cursor.return_value.execute.side_effect = \
                mysql.connector.errors.IntegrityError("Duplicate entry")
            with patch("epilepscreen.views.get_db_connection",
                       return_value=mock_cnx):
                _hash, _title, status = ingest_file(path)
                self.assertTrue(status.startswith("duplicate"))

    def test_oversized_file_skipped_before_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "clip.mp4")
            with patch("epilepscreen.views.get_db_connection") as mock_cnx, \
                 patch("epilepscreen.management.commands.ingest_media"
                       ".MAX_BYTES", 4):
                _hash, _title, status = ingest_file(path)
                self.assertTrue(status.startswith("skipped"))
                mock_cnx.assert_not_called()

    def test_auto_category_from_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "clip.mp4")
            mock_cnx = self._mock_cnx()
            with patch("epilepscreen.views.get_db_connection",
                       return_value=mock_cnx), \
                 patch("epilepscreen.management.commands.ingest_media"
                       ".probe_media",
                       return_value={"duration_s": 30, "width": 720,
                                     "height": 1280}):
                _hash, _title, status = ingest_file(path, auto_category=True)
                self.assertEqual(status, "stored")
                _sql, params = mock_cnx.cursor.return_value.execute.call_args[0]
                self.assertEqual(params[3], "Short")

    def test_missing_file_reported(self):
        _hash, title, status = ingest_file("/no/such/file.mp4")
        self.assertEqual(title, "file")
        self.assertTrue(status.startswith("unreadable"))


if __name__ == "__main__":
    unittest.main()
