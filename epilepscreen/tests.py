"""Basic view tests that need no MySQL: the DB connection is mocked out."""
from unittest.mock import MagicMock, patch

import mysql.connector
from django.test import RequestFactory, TestCase

from epilepscreen.views import upload_video


DB_DOWN = mysql.connector.Error("mock: no database")


class IndexTests(TestCase):
    @patch("epilepscreen.views.get_db_connection", side_effect=DB_DOWN)
    def test_index_renders_empty_library_when_db_down(self, _mock):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No videos found")
        self.assertEqual(list(resp.context["videos"]), [])

    def test_index_marks_analyzed_videos(self):
        rows = [{"hash": 42, "title": "v", "time_uploaded": "2024-01-01",
                 "analyzed": 1, "category": "Movie",
                 "content_type": "video/mp4"}]
        mock_cnx = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_cnx.cursor.return_value = mock_cursor
        with patch("epilepscreen.views.get_db_connection",
                   return_value=mock_cnx):
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200)
            videos = list(resp.context["videos"])
            self.assertEqual(len(videos), 1)
            self.assertTrue(videos[0]["analyzed"])


class UploadTests(TestCase):
    def test_get_redirects_to_index(self):
        resp = self.client.get("/upload/")
        self.assertEqual(resp.status_code, 302)

    def test_oversized_file_rejected_without_touching_db(self):
        big = MagicMock()
        big.size = 101 * 1024 * 1024
        request = RequestFactory().post("/upload/", {"title": "big"})
        request.FILES["video_file"] = big
        with patch("epilepscreen.views.get_db_connection") as mock_cnx:
            resp = upload_video(request)
            self.assertEqual(resp.status_code, 413)
            mock_cnx.assert_not_called()


class StreamTests(TestCase):
    @patch("epilepscreen.views.get_db_connection", side_effect=DB_DOWN)
    def test_db_error_returns_500(self, _mock):
        resp = self.client.get("/stream/123/")
        self.assertEqual(resp.status_code, 500)


class EmbedTests(TestCase):
    @patch("epilepscreen.views.get_db_connection", side_effect=DB_DOWN)
    def test_unavailable_video_returns_500(self, _mock):
        resp = self.client.get("/embed/123/")
        self.assertEqual(resp.status_code, 500)
