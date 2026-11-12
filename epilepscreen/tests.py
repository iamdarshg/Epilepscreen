"""End-to-end tests for the Django side of Epilepscreen.

These run against a real (temporary) database, so they exercise the same SQL
the site uses: upload -> hash -> store -> screen -> events -> player -> order.
Synthetic clips are generated with OpenCV, so no fixture media is needed.
"""
import json
import lzma
import os
import tempfile

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase

from epilepscreen.analysis_store import save_analysis, save_events
from epilepscreen.views import VideoStore, sensitivity_from_request
from photosensitive.analyzer import HazardEvent, analyze_frames


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _write_clip(path, frames, fps=15, size=(160, 120)):
    """Encode RGB frames to an mp4 with OpenCV. Returns True on success."""
    import cv2

    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), fps, size)
    if not writer.isOpened():
        return False
    try:
        for frame in frames:
            writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    return True


def _solid(size, rgb):
    frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    frame[:, :] = rgb
    return frame


def clip_bytes(kind='strobe', frames=24, fps=15, size=(160, 120)):
    """Bytes of a generated clip, or None when this OpenCV cannot encode mp4."""
    if kind == 'strobe':
        sequence = [_solid(size, (255, 255, 255) if i % 2 else (0, 0, 0))
                    for i in range(frames)]
    elif kind == 'red':
        sequence = [_solid(size, (230, 10, 10) if 8 <= i < 12 else (15, 15, 18))
                    for i in range(frames)]
    else:
        sequence = [_solid(size, (60 + i, 60 + i, 60 + i)) for i in range(frames)]

    handle = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
    handle.close()
    try:
        if not _write_clip(handle.name, sequence, fps=fps, size=size):
            return None
        with open(handle.name, 'rb') as fh:
            return fh.read()
    finally:
        os.unlink(handle.name)


def store_video(raw, title='Clip', category='Other', content_type='video/mp4'):
    """Insert a video row the way the upload view does. Returns its hash."""
    import hashlib

    video_hash = int(hashlib.sha256(raw).hexdigest()[:15], 16)
    VideoStore().insert_video(video_hash, title, category, content_type,
                              lzma.compress(raw))
    return video_hash


def upload_file(raw, name='clip.mp4', content_type='video/mp4'):
    return SimpleUploadedFile(name, raw, content_type=content_type)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

class HomeTests(TestCase):
    def test_home_renders_with_empty_library(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No videos found')
        self.assertEqual(list(response.context['recent_videos']), [])

    def test_home_lists_a_stored_video(self):
        raw = clip_bytes('calm', frames=6)
        if raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        store_video(raw, title='Calm clip')
        response = self.client.get('/')
        self.assertContains(response, 'Calm clip')
        self.assertEqual(response.context['library_count'], 1)


class BrowseTests(TestCase):
    def setUp(self):
        self.raw = clip_bytes('calm', frames=6)
        if self.raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        self.video_hash = store_video(self.raw, title='Gig at the hall',
                                      category='Music Video')

    def test_search_filters_by_title(self):
        response = self.client.get('/browse/', {'q': 'gig'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['videos']), 1)
        self.assertEqual(response.context['videos'][0]['hash'], self.video_hash)

    def test_search_miss_returns_empty_state(self):
        response = self.client.get('/browse/', {'q': 'nothing-matches'})
        self.assertEqual(len(response.context['videos']), 0)
        self.assertContains(response, 'Nothing matches')

    def test_category_filter(self):
        self.assertEqual(len(self.client.get('/browse/', {'category': 'Music Video'})
                             .context['videos']), 1)
        self.assertEqual(len(self.client.get('/browse/', {'category': 'Movie'})
                             .context['videos']), 0)

    def test_unscreened_video_is_marked_unknown(self):
        video = self.client.get('/browse/').context['videos'][0]
        self.assertFalse(video['analyzed'])
        self.assertEqual(video['rating'], 'unknown')

    def test_categories_endpoint(self):
        payload = self.client.get('/categories/').json()
        self.assertEqual(payload['categories'][0]['name'], 'Music Video')
        self.assertEqual(payload['categories'][0]['count'], 1)


# --------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------

class UploadTests(TestCase):
    def test_get_renders_the_form(self):
        response = self.client.get('/upload/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload and screen')

    def test_wrong_extension_is_rejected(self):
        response = self.client.post('/upload/send/', {
            'title': 'notes',
            'video_file': upload_file(b'not a video', name='notes.txt',
                                      content_type='text/plain'),
        }, follow=True)
        self.assertContains(response, 'wrong bytes')
        self.assertEqual(VideoStore().count_videos(), 0)

    def test_empty_file_is_rejected(self):
        response = self.client.post('/upload/send/', {
            'video_file': upload_file(b'', name='empty.mp4'),
        }, follow=True)
        self.assertContains(response, 'empty')
        self.assertEqual(VideoStore().count_videos(), 0)

    def test_oversized_file_is_rejected(self):
        from django.test import override_settings
        with override_settings(MAX_UPLOAD_BYTES=10):
            response = self.client.post('/upload/send/', {
                'video_file': upload_file(b'x' * 64, name='big.mp4'),
            }, follow=True)
        self.assertContains(response, 'larger than')
        self.assertEqual(VideoStore().count_videos(), 0)

    def test_upload_stores_a_row_and_redirects_to_the_player(self):
        raw = clip_bytes('calm', frames=6)
        if raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        response = self.client.post('/upload/send/', {
            'title': 'My clip',
            'category': 'Short',
            'video_file': upload_file(raw),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VideoStore().count_videos(), 1)
        row = VideoStore().get_videos()[0]
        self.assertEqual(row['title'], 'My clip')
        self.assertEqual(row['category'], 'Short')
        self.assertIn(f"/player/{row['hash']}/", response['Location'])

    def test_identical_upload_is_not_stored_twice(self):
        raw = clip_bytes('calm', frames=6)
        if raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        self.client.post('/upload/send/', {'video_file': upload_file(raw)})
        response = self.client.post('/upload/send/', {'video_file': upload_file(raw)},
                                    follow=True)
        self.assertContains(response, 'already in the library')
        self.assertEqual(VideoStore().count_videos(), 1)

    def test_upload_can_screen_immediately(self):
        raw = clip_bytes('strobe', frames=24)
        if raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        self.client.post('/upload/send/', {'video_file': upload_file(raw), 'screen': '1'})
        video_hash = VideoStore().get_videos()[0]['hash']
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM hazard_event WHERE video_hash = %s',
                           (video_hash,))
            self.assertGreater(cursor.fetchone()[0], 0)


# --------------------------------------------------------------------------
# screening pipeline
# --------------------------------------------------------------------------

class ScreeningTests(TestCase):
    def setUp(self):
        self.raw = clip_bytes('strobe', frames=24)
        if self.raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        self.video_hash = store_video(self.raw, title='Strobe')

    def test_analyze_endpoint_flags_a_strobe_and_stores_events(self):
        response = self.client.get(f'/analyze/{self.video_hash}/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['analyzed'])
        self.assertFalse(payload['is_safe'])
        self.assertIn('flicker', payload['risk_flags'])
        self.assertGreater(payload['event_count'], 0)
        self.assertGreater(payload['frames'], 1)

        with connection.cursor() as cursor:
            cursor.execute('SELECT kind, start_time, end_time FROM hazard_event '
                           'WHERE video_hash = %s ORDER BY start_time', (self.video_hash,))
            rows = cursor.fetchall()
        self.assertTrue(rows)
        kinds = {row[0] for row in rows}
        self.assertIn('flicker', kinds)
        first = rows[0]
        self.assertGreaterEqual(first[1], 0.0)
        self.assertGreater(first[2], first[1])

    def test_analysis_row_is_written_once_per_video(self):
        self.client.get(f'/analyze/{self.video_hash}/')
        self.client.get(f'/analyze/{self.video_hash}/')
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM analysis WHERE video_hash = %s',
                           (self.video_hash,))
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_events_endpoint_uses_the_keys_the_overlay_reads(self):
        self.client.get(f'/analyze/{self.video_hash}/')
        payload = self.client.get(f'/events/{self.video_hash}/').json()
        self.assertTrue(payload['analyzed'])
        event = payload['events'][0]
        for key in ('kind', 'start', 'end', 'start_time', 'end_time', 'attributes'):
            self.assertIn(key, event)
        self.assertLessEqual(event['start'], event['end'])

    def test_player_page_renders_the_report(self):
        self.client.get(f'/analyze/{self.video_hash}/')
        response = self.client.get(f'/player/{self.video_hash}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hazard windows')
        self.assertContains(response, 'Guard while in a hazard')
        self.assertTrue(response.context['report']['analyzed'])

    def test_screening_page_renders(self):
        self.client.get(f'/analyze/{self.video_hash}/')
        response = self.client.get(f'/screening/{self.video_hash}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'How this was measured')
        self.assertContains(response, 'What this cannot promise')

    def test_embed_renders_without_site_chrome(self):
        response = self.client.get(f'/embed/{self.video_hash}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'is-embedded')
        self.assertContains(response, 'player-video')

    def test_analyze_missing_video_is_404(self):
        self.assertEqual(self.client.get('/analyze/999999/').status_code, 404)

    def test_analyze_audio_only_is_rejected(self):
        video_hash = store_video(b'ID3fakeaudio', title='Song',
                                 content_type='audio/mpeg')
        response = self.client.get(f'/analyze/{video_hash}/')
        self.assertEqual(response.status_code, 422)
        self.assertIn('Audio-only', response.json()['error'])

    def test_sensitivity_overrides_are_echoed(self):
        response = self.client.get(
            f'/analyze/{self.video_hash}/?flash_delta=25&flash_limit=2&red_floor=0.15')
        payload = response.json()
        self.assertEqual(payload['overrides'],
                         {'flash_delta': 25.0, 'flash_limit': 2, 'red_floor': 0.15})
        self.assertEqual(payload['sensitivity']['flash_delta'], 25.0)

    def test_out_of_range_sensitivity_falls_back_to_defaults(self):
        response = self.client.get(
            f'/analyze/{self.video_hash}/?flash_delta=9999&flash_limit=nope')
        payload = response.json()
        self.assertEqual(payload['overrides'], {})
        self.assertEqual(payload['sensitivity']['flash_delta'], 40.0)
        self.assertEqual(payload['sensitivity']['flash_limit'], 3)


class SensitivityParsingTests(TestCase):
    def test_unknown_keys_are_ignored(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/analyze/1/', {'nonsense': '1'})
        overrides, effective = sensitivity_from_request(request)
        self.assertEqual(overrides, {})
        self.assertIn('flash_delta', effective)

    def test_float_and_int_casts(self):
        from django.test import RequestFactory
        request = RequestFactory().get('/analyze/1/', {'flash_window': '12'})
        overrides, _ = sensitivity_from_request(request)
        self.assertEqual(overrides, {'flash_window': 12})
        self.assertIsInstance(overrides['flash_window'], int)


# --------------------------------------------------------------------------
# detector core (integration level)
# --------------------------------------------------------------------------

class DetectorTests(TestCase):
    def test_strobe_frames_produce_a_flicker_event_with_timestamps(self):
        frames = [_solid((8, 8), (255, 255, 255) if i % 2 else (0, 0, 0))
                  for i in range(8)]
        profile = analyze_frames(frames, fps=30.0)
        self.assertFalse(profile.is_safe)
        event = next(e for e in profile.events if e.kind == 'flicker')
        self.assertAlmostEqual(event.start_time, 1 / 30.0, places=6)
        self.assertAlmostEqual(event.end_time, 7 / 30.0, places=6)
        self.assertIn('flash_rate', event.attributes)

    def test_steady_frames_are_safe(self):
        frames = [_solid((8, 8), (100, 100, 100)) for _ in range(6)]
        profile = analyze_frames(frames, fps=10.0)
        self.assertTrue(profile.is_safe)
        self.assertEqual(profile.events, [])

    def test_summary_reports_counts_and_duration(self):
        frames = [_solid((8, 8), (255, 255, 255) if i % 2 else (0, 0, 0))
                  for i in range(8)]
        summary = analyze_frames(frames, fps=10.0).summary()
        self.assertEqual(summary['frames'], 8)
        self.assertAlmostEqual(summary['duration_s'], 0.8, places=2)
        self.assertGreaterEqual(summary['counts']['flicker'], 1)
        self.assertGreater(summary['max_flash_rate'], 0)

    def test_one_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze_frames([_solid((8, 8), (0, 0, 0))])


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

class AnalysisStoreTests(TestCase):
    def test_save_events_replaces_previous_rows(self):
        video_hash = store_video(b'fake-bytes', title='x')
        first = [HazardEvent('flicker', 0.0, 1.0, {'flash_rate': 5}),
                 HazardEvent('red_flash', 2.0, 3.0, {'coverage': 0.4})]
        self.assertEqual(save_events(video_hash, first), 2)
        self.assertEqual(save_events(video_hash, first[:1]), 1)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM hazard_event WHERE video_hash = %s',
                           (video_hash,))
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_save_analysis_keeps_one_row(self):
        video_hash = store_video(b'fake-bytes-2', title='y')

        class Profile:
            is_safe = False
            risk_flags = ['flicker']

        save_analysis(video_hash, Profile())
        Profile.is_safe = True
        Profile.risk_flags = []
        save_analysis(video_hash, Profile())
        with connection.cursor() as cursor:
            cursor.execute('SELECT is_safe, risk_flags FROM analysis WHERE video_hash = %s',
                           (video_hash,))
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), 1)
        self.assertEqual(json.loads(rows[0][1]), [])


class StreamTests(TestCase):
    def setUp(self):
        self.raw = clip_bytes('calm', frames=6)
        if self.raw is None:
            self.skipTest('OpenCV cannot encode mp4v here')
        self.video_hash = store_video(self.raw)

    def test_full_response(self):
        response = self.client.get(f'/stream/{self.video_hash}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Accept-Ranges'], 'bytes')
        self.assertEqual(response.content, self.raw)

    def test_range_request_returns_206(self):
        response = self.client.get(f'/stream/{self.video_hash}/',
                                   HTTP_RANGE='bytes=0-99')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response['Content-Range'], f'bytes 0-99/{len(self.raw)}')
        self.assertEqual(response.content, self.raw[:100])

    def test_unsatisfiable_range_returns_416(self):
        response = self.client.get(f'/stream/{self.video_hash}/',
                                   HTTP_RANGE=f'bytes={len(self.raw) + 10}-')
        self.assertEqual(response.status_code, 416)

    def test_missing_video_is_404(self):
        self.assertEqual(self.client.get('/stream/123456/').status_code, 404)


# --------------------------------------------------------------------------
# demonstration storefront
# --------------------------------------------------------------------------

class StoreTests(TestCase):
    def test_store_lists_the_seeded_packs(self):
        response = self.client.get('/store/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Screening pack')
        self.assertContains(response, 'simulated')

    def test_prices_are_seeded_in_rupees(self):
        from epilepscreen.models import StoreProduct
        pack = StoreProduct.objects.get(title='Screening pack')
        self.assertEqual(pack.price_paise, 49900)  # ₹499, stored in paise
        page = self.client.get('/store/')
        self.assertContains(page, '₹499')
        self.assertNotContains(page, '$19')

    def test_add_to_cart_then_checkout_page(self):
        from epilepscreen.models import StoreProduct
        product = StoreProduct.objects.first()
        response = self.client.post(f'/cart/add/{product.pk}/')
        self.assertEqual(response.status_code, 302)
        page = self.client.get('/checkout/')
        self.assertContains(page, 'DEMO CHECKOUT')
        self.assertContains(page, product.title)
        self.assertEqual(page.context['item_count'], 1)

    def test_checkout_creates_a_demo_purchase(self):
        from epilepscreen.models import Purchase, StoreProduct
        product = StoreProduct.objects.first()
        self.client.post(f'/cart/add/{product.pk}/')
        response = self.client.post('/checkout/', {'email': 'student@example.com'})
        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.payment_method, 'demo')
        self.assertEqual(purchase.status, 'completed')
        self.assertEqual(purchase.amount_paise, product.price_paise)
        self.assertEqual(purchase.currency, 'INR')
        self.assertIsNotNone(purchase.completed_at)

        receipt = self.client.get('/order/')
        self.assertContains(receipt, 'Order recorded')
        self.assertContains(receipt, 'no payment taken')
        self.assertContains(receipt, '₹')

    def test_checkout_stores_the_total_spend_per_email(self):
        """Two orders from one email accumulate in customer_spend."""
        from epilepscreen.models import CustomerSpend, StoreProduct
        product = StoreProduct.objects.get(title='Screening pack')

        for _ in range(2):
            self.client.post(f'/cart/add/{product.pk}/')
            self.client.post('/checkout/', {'email': 'spender@example.com'})

        spend = CustomerSpend.objects.get(email='spender@example.com')
        self.assertEqual(spend.order_count, 2)
        self.assertEqual(spend.total_paise, product.price_paise * 2)
        self.assertEqual(spend.currency, 'INR')
        self.assertEqual(spend.total_display, '₹998')
        self.assertIsNotNone(spend.first_order_at)
        self.assertIsNotNone(spend.last_order_at)

    def test_spend_is_tracked_per_email_not_globally(self):
        from epilepscreen.models import CustomerSpend, StoreProduct
        cheap = StoreProduct.objects.get(title='Screening pack')
        dear = StoreProduct.objects.get(title='Premium shelf')

        self.client.post(f'/cart/add/{cheap.pk}/')
        self.client.post('/checkout/', {'email': 'a@example.com'})
        self.client.post(f'/cart/add/{dear.pk}/')
        self.client.post('/checkout/', {'email': 'b@example.com'})

        self.assertEqual(CustomerSpend.objects.get(email='a@example.com').total_paise,
                         cheap.price_paise)
        self.assertEqual(CustomerSpend.objects.get(email='b@example.com').total_paise,
                         dear.price_paise)

    def test_receipt_shows_the_stored_total_for_that_email(self):
        from epilepscreen.models import StoreProduct
        product = StoreProduct.objects.get(title='Screening pack')
        for _ in range(3):
            self.client.post(f'/cart/add/{product.pk}/')
            self.client.post('/checkout/', {'email': 'repeat@example.com'})

        receipt = self.client.get('/order/')
        self.assertEqual(receipt.context['spend_total'], '₹1,497')
        self.assertEqual(receipt.context['spend_orders'], 3)
        self.assertContains(receipt, 'Total spend stored for repeat@example.com')

    def test_checkout_rejects_a_bad_email(self):
        from epilepscreen.models import CustomerSpend, Purchase, StoreProduct
        product = StoreProduct.objects.first()
        self.client.post(f'/cart/add/{product.pk}/')
        response = self.client.post('/checkout/', {'email': 'not-an-email'}, follow=True)
        self.assertContains(response, 'not valid')
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(CustomerSpend.objects.count(), 0)

    def test_checkout_with_empty_cart_redirects(self):
        response = self.client.post('/checkout/', {'email': 'a@b.com'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/store/', response['Location'])

    def test_checkout_page_never_asks_for_card_details(self):
        from epilepscreen.models import StoreProduct
        product = StoreProduct.objects.first()
        self.client.post(f'/cart/add/{product.pk}/')
        html = self.client.get('/checkout/').content.decode()
        for forbidden in ('card number', 'cvv', 'cvc', 'expiry', 'card_last4'):
            self.assertNotIn(forbidden, html.lower())

    def test_remove_from_cart(self):
        from epilepscreen.models import StoreProduct
        product = StoreProduct.objects.first()
        self.client.post(f'/cart/add/{product.pk}/')
        self.client.post(f'/cart/remove/{product.pk}/')
        self.assertEqual(self.client.get('/checkout/').context['item_count'], 0)


class MoneyTests(TestCase):
    def test_format_paise(self):
        from epilepscreen.money import format_paise
        self.assertEqual(format_paise(49900), '₹499')
        self.assertEqual(format_paise(49950), '₹499.50')
        self.assertEqual(format_paise(0), '₹0')
        self.assertEqual(format_paise(None), '₹0')

    def test_indian_grouping(self):
        from epilepscreen.money import format_paise
        self.assertEqual(format_paise(199900), '₹1,999')
        self.assertEqual(format_paise(100000 * 100), '₹1,00,000')
        self.assertEqual(format_paise(12345678 * 100 + 90), '₹1,23,45,678.90')

    def test_rupees_to_paise_round_trip(self):
        from epilepscreen.money import format_paise, rupees_to_paise
        self.assertEqual(rupees_to_paise('499'), 49900)
        self.assertEqual(rupees_to_paise('₹1,999'), 199900)
        self.assertEqual(rupees_to_paise('19.5'), 1950)
        self.assertEqual(format_paise(rupees_to_paise('1,23,456.70')), '₹1,23,456.70')

    def test_rupees_to_paise_rejects_junk(self):
        from epilepscreen.money import rupees_to_paise
        for junk in ('', 'abc', '1.2.3', '12.345'):
            with self.assertRaises(ValueError):
                rupees_to_paise(junk)


class HealthTests(TestCase):
    def test_health_reports_the_engine(self):
        payload = self.client.get('/health/').json()
        self.assertEqual(payload['status'], 'ok')
        self.assertIn(payload['engine'], ('sqlite', 'mysql'))


class AdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_superuser('teacher', 't@example.com', 'pw-for-tests')
        self.client.force_login(self.user)

    def test_admin_lists_the_screening_tables(self):
        video_hash = store_video(b'admin-bytes', title='Admin clip')
        save_analysis(video_hash, type('P', (), {'is_safe': True, 'risk_flags': []})())
        for url in ('/admin/epilepscreen/videorecord/',
                    '/admin/epilepscreen/hazardevent/',
                    '/admin/epilepscreen/analysis/',
                    '/admin/epilepscreen/storeproduct/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
        self.assertContains(self.client.get('/admin/epilepscreen/videorecord/'),
                            'Admin clip')

