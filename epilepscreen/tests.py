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


class AnalysisStoreTests(TestCase):

    def test_save_analysis_replaces_state_row(self):
        from epilepscreen.analysis_store import save_analysis
        profile = MagicMock()
        profile.is_safe = True
        profile.risk_flags = []
        mock_cnx = MagicMock()
        mock_cursor = MagicMock()
        mock_cnx.cursor.return_value = mock_cursor
        with patch("epilepscreen.views.get_db_connection",
                   return_value=mock_cnx):
            save_analysis(42, profile)
            sql = mock_cursor.execute.call_args[0][0]
            self.assertIn("REPLACE INTO analysis", sql)
            mock_cnx.commit.assert_called_once()


def _mock_db(video_rows, stats_rows=(), cat_rows=()):
    """Fake mysql connection: fetchall returns one list per query."""
    mock_cnx = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [video_rows, stats_rows, cat_rows]
    mock_cnx.cursor.return_value = mock_cursor
    return mock_cnx, mock_cursor


class BrowseTests(TestCase):
    def test_browse_merges_stats_flags_and_search(self):
        video_rows = [{
            "hash": 7, "title": "Gig", "time_uploaded": "2024-01-01",
            "category": "Music Video", "content_type": "video/mp4",
            "is_safe": 0, "risk_flags": '["flicker"]',
        }]
        stats_rows = [{"video_hash": 7, "n": 3, "kinds": "flicker,red_flash"}]
        cat_rows = [{"category": "Music Video"}]
        mock_cnx, mock_cursor = _mock_db(video_rows, stats_rows, cat_rows)
        with patch("epilepscreen.views.get_db_connection",
                   return_value=mock_cnx):
            resp = self.client.get("/browse/?q=gig")
            self.assertEqual(resp.status_code, 200)
            videos = list(resp.context["videos"])
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0]["event_count"], 3)
            self.assertEqual(videos[0]["kinds"], ["flicker", "red_flash"])
            self.assertTrue(videos[0]["analyzed"])
            self.assertFalse(videos[0]["is_safe"])
            # Title search goes to SQL as a LIKE parameter.
            first_params = mock_cursor.execute.call_args_list[0][0][1]
            self.assertIn("%gig%", first_params)

    def test_browse_category_filter_reaches_sql(self):
        mock_cnx, mock_cursor = _mock_db([], [], [])
        with patch("epilepscreen.views.get_db_connection",
                   return_value=mock_cnx):
            resp = self.client.get("/browse/?category=Short")
            self.assertEqual(resp.status_code, 200)
            first_params = mock_cursor.execute.call_args_list[0][0][1]
            self.assertIn("Short", first_params)


def _mock_video_db():
    """Fake mysql connection serving one stored mp4 row."""
    import lzma
    mock_cnx = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "movie": lzma.compress(b"x" * 64),
        "content_type": "video/mp4",
        "category": "Movie",
        "title": "t",
    }
    mock_cnx.cursor.return_value = mock_cursor
    return mock_cnx


def _mock_profile():
    profile = MagicMock()
    profile.is_safe = False
    profile.risk_flags = ["flicker"]
    profile.events = []
    return profile


class AnalyzeSensitivityTests(TestCase):
    def test_valid_params_reach_analyzer_and_echo(self):
        with patch("epilepscreen.views.get_db_connection",
                   return_value=_mock_video_db()), \
             patch("epilepscreen.views.analyze_video_file",
                   return_value=_mock_profile()) as mock_analyze, \
             patch("epilepscreen.views.save_events"), \
             patch("epilepscreen.views.save_analysis"), \
             patch("epilepscreen.views._set_category"):
            resp = self.client.get(
                "/analyze/1/?flash_limit=2&flash_delta=25&red_floor=0.15")
            self.assertEqual(resp.status_code, 200)
            cfg = mock_analyze.call_args[1]["cfg"]
            self.assertEqual(
                cfg, {"flash_limit": 2, "flash_delta": 25.0,
                      "red_floor": 0.15})
            data = resp.json()
            self.assertEqual(data["sensitivity"], cfg)

    def test_bad_params_fall_back_to_defaults(self):
        with patch("epilepscreen.views.get_db_connection",
                   return_value=_mock_video_db()), \
             patch("epilepscreen.views.analyze_video_file",
                   return_value=_mock_profile()) as mock_analyze, \
             patch("epilepscreen.views.save_events"), \
             patch("epilepscreen.views.save_analysis"), \
             patch("epilepscreen.views._set_category"):
            resp = self.client.get(
                "/analyze/1/?flash_limit=999&flash_delta=nope")
            self.assertEqual(resp.status_code, 200)
            cfg = mock_analyze.call_args[1]["cfg"]
            self.assertEqual(
                cfg, {"flash_limit": 3, "flash_delta": 40.0,
                      "red_floor": 0.25})
