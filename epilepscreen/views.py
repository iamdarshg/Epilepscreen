"""Epilepscreen views: library, screening, player and the demonstration store.

Layers, from the bottom up:

1. `VideoStore` and the module-level helpers talk to the database with plain
   SQL (`SELECT`, `INSERT`, `REPLACE`). The same statements run on SQLite and
   on MySQL because Django translates the `%s` placeholders.
2. `run_screening()` is the Python brain: it decompresses a stored file, hands
   it to the OpenCV decoder in `photosensitive/`, writes the resulting events
   and verdict back to `hazard_event` and `analysis`, and returns a report.
3. The views below render that report (player, screening page) or serve the
   bytes (`stream_video`). JavaScript only draws the overlay and drives the
   player; it never decides whether a frame is a hazard.
"""
import datetime
import hashlib
import json
import lzma
import os
import tempfile
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.clickjacking import xframe_options_exempt, xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from epilepscreen.analysis_store import save_analysis, save_events
from epilepscreen.media import (
    BUILTIN_CATEGORIES,
    content_type_for,
    is_audio_content,
    normalize_category,
    probe_media,
    suggest_category,
)
from epilepscreen.models import Purchase, StoreProduct
from epilepscreen.money import format_paise
from epilepscreen.orders import create_demo_order, spend_for
from epilepscreen.store_browser import (
    BrowserError,
    browser_context,
    fetch_asset,
    fetch_page,
    is_allowed_url,
)
from photosensitive.analyze_video import analyze_video_file

MAX_UPLOAD_BYTES = getattr(settings, 'MAX_UPLOAD_BYTES', 100 * 1024 * 1024)
ANALYSIS_FPS = float(getattr(settings, 'ANALYSIS_FPS', 15.0))


def max_upload_bytes():
    """Read the limit at call time so tests and deployments can override it."""
    return int(getattr(settings, 'MAX_UPLOAD_BYTES', MAX_UPLOAD_BYTES))


def analysis_fps():
    return float(getattr(settings, 'ANALYSIS_FPS', ANALYSIS_FPS))


# Above this many seconds of footage, screening is not run inside the upload
# request. The player's "Screen this video" button still runs it on demand.
INLINE_SCREENING_LIMIT_S = 15 * 60

VIDEO_EXTENSIONS = ('mp4', 'webm', 'mov', 'avi', 'mkv', 'flv', 'm4v', '3gp', 'ogv')

# Sensitivity knobs exposed in the UI: key -> (cast, minimum, maximum).
SENSITIVITY_SPEC = {
    'flash_delta': (float, 5.0, 150.0),
    'flash_window': (int, 1, 60),
    'flash_limit': (int, 1, 20),
    'red_floor': (float, 0.0, 1.0),
    'red_window': (int, 1, 120),
    'color_threshold': (float, 0.0, 1.8),
    'spatial_contrast': (float, 0.01, 1.0),
    'spatial_threshold': (float, 0.0, 1.0),
    'pattern_move_threshold': (float, 0.0, 1.0),
}

KIND_LABELS = {
    'flicker': 'Flash / flicker',
    'red_flash': 'Red flash',
    'color_transition': 'Colour transition',
    'spatial_pattern': 'High-contrast pattern',
    'pattern_movement': 'Moving pattern',
}


# --------------------------------------------------------------------------
# Database access (plain SQL on top of Django's connection)
# --------------------------------------------------------------------------

class VideoStore:
    """Reads and writes the `epilepsy` table."""

    COLUMNS = 'hash, time_uploaded, title, category, content_type'

    def cursor(self):
        return connection.cursor()

    def _rows(self, sql, params):
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_videos(self, search_query=None, category=None, limit=20, offset=0):
        """Newest first, optionally narrowed by title text and category."""
        sql = f"SELECT {self.COLUMNS} FROM epilepsy WHERE movie IS NOT NULL"
        params = []
        if category:
            sql += " AND LOWER(category) = LOWER(%s)"
            params.append(category)
        if search_query:
            sql += " AND LOWER(title) LIKE LOWER(%s)"
            params.append(f"%{search_query}%")
        sql += " ORDER BY time_uploaded DESC, hash DESC LIMIT %s OFFSET %s"
        params.extend([int(limit), int(offset)])
        return decorate_videos(self._rows(sql, params))

    def get_video_by_hash(self, video_hash):
        rows = self._rows(
            f"SELECT {self.COLUMNS}, movie FROM epilepsy WHERE hash = %s",
            (int(video_hash),))
        return rows[0] if rows else None

    def get_video_meta(self, video_hash):
        """Row without the (potentially huge) blob column."""
        rows = self._rows(
            f"SELECT {self.COLUMNS} FROM epilepsy WHERE hash = %s", (int(video_hash),))
        return rows[0] if rows else None

    def count_videos(self):
        with self.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM epilepsy WHERE movie IS NOT NULL")
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def categories(self):
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT category, COUNT(*) FROM epilepsy "
                "WHERE movie IS NOT NULL AND category IS NOT NULL "
                "GROUP BY category ORDER BY category")
            return [{'name': row[0], 'count': int(row[1])} for row in cursor.fetchall()]

    def insert_video(self, video_hash, title, category, content_type, blob, when=None):
        with self.cursor() as cursor:
            cursor.execute(
                "INSERT INTO epilepsy (hash, time_uploaded, title, category, "
                "content_type, movie) VALUES (%s, %s, %s, %s, %s, %s)",
                (video_hash, when or timezone.now(), title, category,
                 content_type, blob))
        return video_hash

    def hash_exists(self, video_hash):
        with self.cursor() as cursor:
            cursor.execute("SELECT title FROM epilepsy WHERE hash = %s", (video_hash,))
            row = cursor.fetchone()
        return row[0] if row else None

    def set_category(self, video_hash, category):
        with self.cursor() as cursor:
            cursor.execute("UPDATE epilepsy SET category = %s WHERE hash = %s",
                           (category, int(video_hash)))

    def delete_video(self, video_hash):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM hazard_event WHERE video_hash = %s",
                               (int(video_hash),))
                cursor.execute("DELETE FROM analysis WHERE video_hash = %s",
                               (int(video_hash),))
                cursor.execute("DELETE FROM epilepsy WHERE hash = %s",
                               (int(video_hash),))


def get_video_store():
    return VideoStore()


def get_db_connection():
    """The live Django connection. Kept as a named helper so tests can patch it."""
    return connection


def _analysis_rows(hashes):
    """`analysis` rows for a batch of hashes, keyed by hash."""
    if not hashes:
        return {}
    placeholders = ', '.join(['%s'] * len(hashes))
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT video_hash, is_safe, risk_flags, checked_at FROM analysis "
            f"WHERE video_hash IN ({placeholders})", list(hashes))
        return {row[0]: {'is_safe': bool(row[1]),
                         'risk_flags': _loads(row[2], []),
                         'checked_at': row[3]} for row in cursor.fetchall()}


def _event_stats(hashes):
    """How many hazard events each video has, and of which kind."""
    if not hashes:
        return {}
    placeholders = ', '.join(['%s'] * len(hashes))
    stats = {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT video_hash, kind, COUNT(*) FROM hazard_event "
            f"WHERE video_hash IN ({placeholders}) "
            "GROUP BY video_hash, kind", list(hashes))
        for video_hash, kind, count in cursor.fetchall():
            entry = stats.setdefault(video_hash, {'count': 0, 'counts': {}})
            entry['count'] += int(count)
            entry['counts'][kind] = int(count)
    return stats


def _loads(value, fallback):
    """JSON column -> Python value, tolerating NULL and plain strings."""
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def decorate_videos(videos):
    """Attach screening state to plain rows so templates stay simple."""
    hashes = [v['hash'] for v in videos]
    analysis = _analysis_rows(hashes)
    stats = _event_stats(hashes)
    for video in videos:
        row = analysis.get(video['hash'])
        stat = stats.get(video['hash'], {'count': 0, 'counts': {}})
        video['analyzed'] = row is not None
        video['is_safe'] = row['is_safe'] if row else None
        video['risk_flags'] = row['risk_flags'] if row else []
        video['checked_at'] = row['checked_at'] if row else None
        video['event_count'] = stat['count']
        video['kinds'] = sorted(stat['counts'])
        video['kind_labels'] = [KIND_LABELS.get(k, k) for k in video['kinds']]
        if row is None:
            video['rating'] = 'unknown'
        elif row['is_safe'] and not stat['count']:
            video['rating'] = 'safe'
        elif row['is_safe']:
            video['rating'] = 'caution'
        else:
            video['rating'] = 'risk'
    return videos


# --------------------------------------------------------------------------
# Screening: the Python pipeline
# --------------------------------------------------------------------------

def sensitivity_from_request(request):
    """Read detector thresholds from the query string or POST body.

    Unknown keys are ignored and out-of-range values fall back to the default
    in `photosensitive/config.py`, so a bad parameter can never make the
    detector stricter or looser than the documented range.
    """
    from photosensitive.config import DEFAULTS

    source = request.POST if request.method == 'POST' else request.GET
    cfg = {}
    for key, (cast, low, high) in SENSITIVITY_SPEC.items():
        if key not in source:
            continue
        try:
            value = cast(source.get(key))
        except (TypeError, ValueError):
            continue
        if low <= value <= high:
            cfg[key] = value
    effective = {key: cfg.get(key, DEFAULTS[key]) for key in SENSITIVITY_SPEC}
    return cfg, effective


def _suffix_for(content_type):
    mapping = {
        'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov',
        'video/x-matroska': '.mkv', 'video/x-msvideo': '.avi',
        'video/x-m4v': '.m4v', 'video/ogg': '.ogv', 'video/x-flv': '.flv',
    }
    return mapping.get((content_type or '').lower(), '.mp4')


def _write_stored_blob(blob, filename):
    """Write an lzma blob to disk in chunks.

    `lzma.decompress()` returns the whole film at once, which is enough to push
    a small server into swap on a large upload. Streaming keeps peak memory at
    the compressed blob plus one chunk of output.
    """
    view = memoryview(blob)
    chunk_size = 4 * 1024 * 1024
    try:
        decompressor = lzma.LZMADecompressor()
        with open(filename, 'wb') as handle:
            for offset in range(0, len(view), chunk_size):
                handle.write(decompressor.decompress(
                    view[offset:offset + chunk_size]))
                if decompressor.eof:
                    break
    except lzma.LZMAError:
        # Compatibility with rows written before the format was fixed: if the
        # blob is not compressed, store the bytes as they are.
        with open(filename, 'wb') as handle:
            for offset in range(0, len(view), chunk_size):
                handle.write(view[offset:offset + chunk_size])


def materialise_video(video_hash):
    """Decompress a stored blob into a temporary file. Returns (path, ctx)."""
    row = get_video_store().get_video_by_hash(video_hash)
    if not row:
        raise Http404('Video not found')
    blob = row.pop('movie', None)
    if blob is None:
        raise Http404('That library item has no file stored.')
    handle = tempfile.NamedTemporaryFile(
        delete=False, suffix=_suffix_for(row.get('content_type')))
    handle.close()
    try:
        _write_stored_blob(blob, handle.name)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return handle.name, row


def run_screening(video_hash, cfg=None):
    """Screen one stored video and persist the result. Returns a report dict.

    Raises Http404 for a missing video, ValueError when the file yields too
    few frames to compare.
    """
    path, row = materialise_video(video_hash)
    try:
        if is_audio_content(row.get('content_type')):
            raise ValueError('Audio-only uploads carry no visual triggers.')
        profile = analyze_video_file(path, target_fps=analysis_fps(), cfg=cfg)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    stored = save_events(video_hash, profile.events)
    save_analysis(video_hash, profile)

    counts = {}
    for event in profile.events:
        counts[event.kind] = counts.get(event.kind, 0) + 1

    report = {
        'video_hash': video_hash,
        'title': row.get('title'),
        'is_safe': profile.is_safe,
        'risk_flags': profile.risk_flags,
        'flags': [{'kind': k, 'label': KIND_LABELS.get(k, k), 'count': counts.get(k, 0)}
                  for k in profile.risk_flags],
        'counts': counts,
        'event_count': len(profile.events),
        'stored_events': stored,
        'frames': getattr(profile, 'frame_count', 0),
        'duration_s': round(getattr(profile, 'duration', 0.0), 2),
        'fps': getattr(profile, 'fps', analysis_fps()),
        'max_flash_rate': _max_flash_rate(profile),
        'events': [event_for_json(e) for e in profile.events],
        'checked_at': datetime.datetime.now().isoformat(timespec='seconds'),
    }
    return report


def _max_flash_rate(profile):
    rates = [e.attributes.get('flash_rate', 0) for e in profile.events
             if e.kind == 'flicker']
    return round(max(rates), 2) if rates else 0.0


def event_for_json(event):
    """One hazard event, shaped for both the API and the player JavaScript."""
    return {
        'kind': event.kind,
        'label': KIND_LABELS.get(event.kind, event.kind),
        'start': round(event.start_time, 3),
        'end': round(event.end_time, 3),
        'start_time': round(event.start_time, 3),
        'end_time': round(event.end_time, 3),
        'attributes': event.attributes,
    }


def screening_report(video_hash):
    """Everything the player page needs about a video's screening."""
    analysis = _analysis_rows([video_hash]).get(video_hash)
    stats = _event_stats([video_hash]).get(video_hash, {'count': 0, 'counts': {}})
    events = []
    if analysis:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT kind, start_time, end_time, attributes FROM hazard_event "
                "WHERE video_hash = %s ORDER BY start_time ASC", (video_hash,))
            for kind, start, end, attributes in cursor.fetchall():
                events.append({
                    'kind': kind,
                    'label': KIND_LABELS.get(kind, kind),
                    'start': round(float(start), 3),
                    'end': round(float(end), 3),
                    'start_time': round(float(start), 3),
                    'end_time': round(float(end), 3),
                    'attributes': _loads(attributes, {}),
                })
    return {
        'analyzed': analysis is not None,
        'is_safe': analysis['is_safe'] if analysis else None,
        'checked_at': analysis['checked_at'] if analysis else None,
        'risk_flags': analysis['risk_flags'] if analysis else [],
        'counts': stats['counts'],
        'event_count': stats['count'],
        'flags': [{'kind': k, 'label': KIND_LABELS.get(k, k),
                   'count': stats['counts'].get(k, 0)} for k in (analysis or {}).get('risk_flags', [])],
        'events': events,
    }


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------

def index(request):
    store = get_video_store()
    try:
        recent = store.get_videos(limit=6)
        total = store.count_videos()
    except DatabaseError:
        recent, total = [], 0
    return render(request, 'home.html', {
        'recent_videos': recent,
        'library_count': total,
        'categories': BUILTIN_CATEGORIES,
        'products': _products(),
        'max_upload_mb': max_upload_bytes() // (1024 * 1024),
    })


def browse(request):
    store = get_video_store()
    q = (request.GET.get('q') or '').strip()
    category = (request.GET.get('category') or '').strip()
    try:
        videos = store.get_videos(search_query=q or None,
                                  category=category or None, limit=60)
        counts = store.categories()
        total = store.count_videos()
    except DatabaseError:
        videos, counts, total = [], [], 0
    return render(request, 'browse.html', {
        'videos': videos,
        'q': q,
        'category': category,
        'categories': counts,
        'library_count': total,
        'result_count': len(videos),
    })


@require_GET
def categories(request):
    try:
        data = get_video_store().categories()
    except DatabaseError:
        data = []
    return JsonResponse({'categories': data})


def upload(request):
    """The upload form page; POST is handled by `upload_video`."""
    if request.method == 'POST':
        return upload_video(request)
    return render(request, 'upload.html', {
        'categories': BUILTIN_CATEGORIES,
        'max_upload_mb': max_upload_bytes() // (1024 * 1024),
    })


def _upload_error(request, message, status_redirect='upload'):
    messages.error(request, message)
    return redirect(status_redirect)


def upload_video(request):
    """Validate, hash, store and (optionally) screen an uploaded file."""
    upload_file = request.FILES.get('video_file')
    if request.method != 'POST' or not upload_file:
        return _upload_error(request, 'Choose a video file to upload.')

    if upload_file.size == 0:
        return _upload_error(request, 'That file is empty.')
    if upload_file.size > max_upload_bytes():
        return _upload_error(
            request, f'The file is larger than {max_upload_bytes() // (1024 * 1024)} MB.')

    extension = os.path.splitext(upload_file.name or '')[1].lower().lstrip('.')
    if extension not in VIDEO_EXTENSIONS:
        return _upload_error(
            request,
            'Those are the wrong bytes. Upload MP4, WebM, MOV, AVI or MKV.')

    mime_type = content_type_for(upload_file.name, getattr(upload_file, 'content_type', None))
    if not mime_type.startswith('video/'):
        return _upload_error(request, 'That file is not a video.')

    raw = upload_file.read()
    video_hash = int(hashlib.sha256(raw).hexdigest()[:15], 16)
    store = get_video_store()

    try:
        existing_title = store.hash_exists(video_hash)
    except DatabaseError:
        return _upload_error(request, 'The library could not be read. Try again.')

    if existing_title:
        messages.info(request, f'"{existing_title}" is already in the library '
                               '(identical file), so nothing was uploaded twice.')
        return redirect('player', video_hash=video_hash)

    title = (request.POST.get('title') or
             os.path.splitext(os.path.basename(upload_file.name))[0]).strip()[:200]
    category = normalize_category(request.POST.get('category'))

    info = _probe_bytes(raw, upload_file.name)
    if category is None:
        category = suggest_category(
            duration_s=(info or {}).get('duration_s'),
            width=(info or {}).get('width'),
            height=(info or {}).get('height'),
            title=title,
            audio_only=is_audio_content(mime_type))

    try:
        store.insert_video(video_hash, title, category, mime_type, lzma.compress(raw))
    except IntegrityError:
        messages.info(request, 'That file is already in the library.')
        return redirect('player', video_hash=video_hash)
    except DatabaseError:
        return _upload_error(request, 'The upload could not be stored. Try again.')

    duration = (info or {}).get('duration_s') or 0
    screened = False
    if request.POST.get('screen') and duration <= INLINE_SCREENING_LIMIT_S:
        try:
            report = run_screening(video_hash)
            screened = True
            verdict = 'no triggers found' if report['is_safe'] else \
                f"{report['event_count']} hazard event(s) found"
            messages.success(request, f'Uploaded "{title}" and screened it: {verdict}.')
        except ValueError as exc:
            messages.warning(request, f'Uploaded "{title}", but it could not be screened: {exc}')
        except Exception:  # noqa: BLE001 - a decode failure must not lose the upload
            messages.warning(request, f'Uploaded "{title}". The screener could not read it.')
    elif request.POST.get('screen'):
        messages.success(request, f'Uploaded "{title}". It is long, so screen it from the player page.')
    else:
        messages.success(request, f'Uploaded "{title}". Run the screener when you are ready.')

    return redirect('player', video_hash=video_hash)


def _probe_bytes(raw, name):
    """Write bytes to a temp file so OpenCV can read duration and dimensions."""
    handle = tempfile.NamedTemporaryFile(delete=False,
                                         suffix=os.path.splitext(name or '')[1] or '.mp4')
    try:
        handle.write(raw)
        handle.close()
        return probe_media(handle.name)
    except Exception:  # noqa: BLE001 - metadata is best effort
        return None
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Playback and screening endpoints
# --------------------------------------------------------------------------

def _video_or_404(video_hash):
    video = get_video_store().get_video_meta(video_hash)
    if not video:
        raise Http404('Video not found')
    return video


@ensure_csrf_cookie
def player(request, video_hash):
    return render(request, 'player.html', _player_context(video_hash))


def _player_context(video_hash):
    video = _video_or_404(video_hash)
    report = screening_report(video_hash)
    return {
        'video': video,
        'title': video.get('title') or 'Untitled',
        'stream_url': reverse('stream_video', args=[video_hash]),
        'events_url': reverse('events', args=[video_hash]),
        'analyze_url': reverse('analyze', args=[video_hash]),
        'screening_url': reverse('screening', args=[video_hash]),
        'report': report,
        'events_json': mark_safe(json.dumps(report['events'])),
        'kind_labels': KIND_LABELS,
        'sensitivity_spec': SENSITIVITY_SPEC,
        'analysis_fps': analysis_fps(),
    }


def embed(request, video_hash):
    """Chromeless player for dropping a screened video into another page."""
    context = _player_context(video_hash)
    context['embedded'] = True
    return render(request, 'player.html', context)


def screening(request, video_hash):
    """The written report: what was found, where, and how it was measured."""
    video = _video_or_404(video_hash)
    report = screening_report(video_hash)
    return render(request, 'screening.html', {
        'video': video,
        'title': video.get('title') or 'Untitled',
        'report': report,
        'kind_labels': KIND_LABELS,
        'analysis_fps': analysis_fps(),
    })


def stream_video(request, video_hash):
    """Serve the stored blob with HTTP range support so the scrubber works."""
    try:
        row = get_video_store().get_video_by_hash(video_hash)
    except DatabaseError:
        return HttpResponse('The library could not be read.', status=503)
    if not row:
        raise Http404('Video not found')

    blob = row.get('movie')
    if blob is None:
        raise Http404('That item has no file stored.')
    try:
        data = lzma.decompress(blob)
    except lzma.LZMAError:
        data = bytes(blob)

    mime_type = row.get('content_type') or 'video/mp4'
    size = len(data)
    range_header = request.headers.get('Range')

    if range_header and range_header.startswith('bytes='):
        try:
            start_str, _, end_str = range_header[6:].partition('-')
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else size - 1
        except ValueError:
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        end = min(end, size - 1)
        if start >= size or start > end or start < 0:
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        return HttpResponse(
            data[start:end + 1], status=206, content_type=mime_type,
            headers={
                'Content-Range': f'bytes {start}-{end}/{size}',
                'Content-Length': str(end - start + 1),
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'private, max-age=60',
            })

    return HttpResponse(data, content_type=mime_type, headers={
        'Accept-Ranges': 'bytes',
        'Content-Length': str(size),
        'Cache-Control': 'private, max-age=60',
    })


@xframe_options_exempt
def stream_as_file(request, video_hash):
    return stream_video(request, video_hash)


def events(request, video_hash):
    """Timestamped hazard events for the overlay. Shape matches the JS widget."""
    _video_or_404(video_hash)
    report = screening_report(video_hash)
    return JsonResponse({
        'video_hash': video_hash,
        'analyzed': report['analyzed'],
        'is_safe': report['is_safe'],
        'events': report['events'],
        'counts': report['counts'],
    })


def analyze(request, video_hash):
    """Run the Python screener now and return its report as JSON.

    Accepts POST (buttons in the UI) and GET (so the pipeline can be exercised
    from a browser address bar or from a test).
    """
    _video_or_404(video_hash)
    cfg, effective = sensitivity_from_request(request)
    try:
        report = run_screening(video_hash, cfg=cfg)
    except ValueError as exc:
        return JsonResponse({'analyzed': False, 'error': str(exc)}, status=422)
    except DatabaseError:
        return JsonResponse({'analyzed': False, 'error': 'Database error'}, status=500)
    except Exception as exc:  # noqa: BLE001 - report, do not 500 the demo
        return JsonResponse({'analyzed': False, 'error': str(exc)}, status=500)

    report['analyzed'] = True
    report['sensitivity'] = effective
    report['overrides'] = cfg
    return JsonResponse(report)


@require_GET
def health(request):
    database_ok = True
    detail = 'ok'
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError as exc:
        database_ok, detail = False, str(exc)
    payload = {
        'status': 'ok' if database_ok else 'degraded',
        'database': detail,
        'engine': connection.vendor,
    }
    return JsonResponse(payload, status=200 if database_ok else 503)


# --------------------------------------------------------------------------
# Demonstration storefront
# --------------------------------------------------------------------------

EXTERNAL_STORES = [
    {
        'name': 'Internet Archive',
        'url': 'https://archive.org/details/movies&and[]=subject%3A%22medical%22',
        'note': 'Public-domain medical film',
        'description': 'Public domain medical and educational videos. Download MP4, AVI, OGG.',
    },
    {
        'name': 'NIH VideoCast',
        'url': 'https://videocast.nih.gov/',
        'note': 'NIH lectures and procedures',
        'description': 'Official NIH medical video library. Lectures, procedures, and research footage.',
    },
    {
        'name': 'CDC Media Library',
        'url': 'https://www.cdc.gov/media/library/index.html',
        'note': 'Public-health footage',
        'description': 'Centers for Disease Control public health videos and B-roll footage.',
    },
    {
        'name': 'Pixabay Videos',
        'url': 'https://pixabay.com/videos/search/medical/',
        'note': 'Free stock medical clips',
        'description': 'Free stock medical footage. No attribution required. HD and 4K clips.',
    },
    {
        'name': 'Pexels Videos',
        'url': 'https://www.pexels.com/search/videos/medical/',
        'note': 'Free stock medical clips',
        'description': 'Free medical stock videos. Downloadable in multiple resolutions.',
    },
    {
        'name': 'MedlinePlus',
        'url': 'https://medlineplus.gov/videolist.html',
        'note': 'Patient-education video',
        'description': 'Patient education videos from the National Library of Medicine.',
    },
]

PRODUCT_TYPE_LABELS = dict(StoreProduct.PRODUCT_TYPES)
CART_SESSION_KEY = 'cart'
ORDER_SESSION_KEY = 'last_order'


def _money(paise):
    """Render a paise amount as ₹, e.g. 49900 -> ₹499 (Indian grouping)."""
    return format_paise(paise)


def _decorate_product(product):
    product.price_amount = format_paise(product.price_paise)
    product.price_display = product.price_amount
    product.kind_label = PRODUCT_TYPE_LABELS.get(product.product_type, product.product_type)
    return product


def _products():
    try:
        return [_decorate_product(p) for p in
                StoreProduct.objects.filter(active=True).order_by('price_paise')]
    except DatabaseError:
        return []


def _cart_ids(request):
    raw = request.session.get(CART_SESSION_KEY, [])
    return [int(v) for v in raw if str(v).isdigit()]


def _cart_context(request):
    ids = _cart_ids(request)
    products = list(StoreProduct.objects.filter(pk__in=ids, active=True)
                    .order_by('price_paise')) if ids else []
    if ids and not products:
        request.session[CART_SESSION_KEY] = []
    by_id = {p.pk: _decorate_product(p) for p in products}
    ordered = [by_id[i] for i in ids if i in by_id]
    total = sum(int(p.price_paise or 0) for p in ordered)
    return {
        'cart_items': ordered,
        'cart_count': len(ordered),
        'cart_total_paise': total,
        'cart_total': _money(total),
    }


def _recent_videos(limit=4):
    try:
        return get_video_store().get_videos(limit=limit)
    except DatabaseError:
        return []


def _library_count():
    try:
        return get_video_store().count_videos()
    except DatabaseError:
        return 0


def _store_context(request, selected_product_id=None):
    products = _products()
    product_ids = {p.pk for p in products}
    if selected_product_id not in product_ids:
        selected_product_id = products[0].pk if products else None
    selected_product = next((p for p in products if p.pk == selected_product_id), None)

    recent_order = None
    raw_order = (request.GET.get('order') or '').strip()
    if raw_order.isdigit():
        try:
            recent_order = (Purchase.objects.select_related('product')
                            .filter(pk=int(raw_order)).first())
        except DatabaseError:
            recent_order = None

    context = {
        'products': products,
        'hero_product': products[0] if products else None,
        'selected_product': selected_product,
        'selected_product_id': selected_product_id,
        'stores': EXTERNAL_STORES,
        'categories': BUILTIN_CATEGORIES,
        'max_upload_mb': max_upload_bytes() // (1024 * 1024),
        'recent_videos': _recent_videos(),
        'library_count': _library_count(),
        'recent_order': recent_order,
        'demo_store': getattr(settings, 'DEMO_STORE', True),
    }
    context.update(_cart_context(request))
    return context


def store(request):
    raw_product = (request.GET.get('product') or '').strip()
    selected = int(raw_product) if raw_product.isdigit() else None
    return render(request, 'store.html', _store_context(request, selected))


def product_detail(request, product_id):
    product = StoreProduct.objects.filter(pk=product_id, active=True).first()
    if not product:
        raise Http404('Product not found')
    return redirect(f"{reverse('store')}?product={product.pk}#order")


def add_to_cart(request, product_id):
    """Add a pack to the session cart, then send the buyer to the checkout."""
    product = StoreProduct.objects.filter(pk=product_id, active=True).first()
    if not product:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Product not found'}, status=404)
        raise Http404('Product not found')

    ids = _cart_ids(request)
    if product.pk not in ids:
        ids.append(product.pk)
        request.session[CART_SESSION_KEY] = ids
        request.session.modified = True

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'cart_count': len(ids),
            'product': {'name': product.title, 'price': _money(product.price_paise)},
        })
    messages.success(request, f'"{product.title}" is in the demo cart.')
    return redirect('checkout')


@require_POST
def remove_from_cart(request, product_id):
    ids = [i for i in _cart_ids(request) if i != int(product_id)]
    request.session[CART_SESSION_KEY] = ids
    request.session.modified = True
    messages.info(request, 'Removed that pack from the demo cart.')
    return redirect('checkout')


def _source_for(url):
    host = (urlparse(url).hostname or '').lower() if url else ''
    for source in EXTERNAL_STORES:
        source_host = (urlparse(source['url']).hostname or '').lower()
        if host == source_host or host.endswith('.' + source_host):
            return source
    if host:
        return {'name': host, 'url': url, 'note': '', 'description': ''}
    return EXTERNAL_STORES[0]


@xframe_options_sameorigin
def browser_page(request):
    """Reader shell for the store's in-page source browser."""
    raw_url = (request.GET.get('url') or '').strip()
    source = _source_for(raw_url)
    target = raw_url if is_allowed_url(raw_url) else source['url']
    back = (request.GET.get('back') or '').strip()
    context = browser_context(source, target, back)
    context.update({'mode': 'page', 'title': '', 'body_html': '', 'error': ''})

    try:
        result = fetch_page(target)
    except BrowserError as exc:
        context['error'] = str(exc)
    else:
        if isinstance(result, dict):
            context.update(result)
            context['mode'] = 'captured'
            context['display_url'] = result.get('final_url', target)
        else:
            title, body_html, final_url = result
            context.update({
                'title': title,
                'body_html': mark_safe(body_html if body_html.strip() else ''),
                'display_url': final_url,
            })
    return render(request, 'store_browser.html', context)


@xframe_options_sameorigin
def browser_asset(request):
    target = (request.GET.get('url') or '').strip()
    if not is_allowed_url(target):
        return HttpResponse('Not an allowed asset.', status=404)
    try:
        data, content_type = fetch_asset(target)
    except BrowserError as exc:
        return HttpResponse(str(exc), status=502, content_type='text/plain; charset=utf-8')
    response = HttpResponse(data, content_type=content_type)
    response['Cache-Control'] = 'private, max-age=300'
    return response


def _checkout_email_error(email):
    if not email:
        return 'Add an email so the receipt can be addressed.'
    try:
        validate_email(email)
    except ValidationError:
        return 'That email address is not valid.'
    return None


def checkout(request):
    """The demo checkout. No card fields exist, by design."""
    cart = _cart_context(request)
    single = None
    raw_product = (request.POST.get('product_id') or request.GET.get('product') or '').strip()
    if not cart['cart_items'] and raw_product.isdigit():
        single = StoreProduct.objects.filter(pk=int(raw_product), active=True).first()
    items = cart['cart_items'] or ([_decorate_product(single)] if single else [])
    total_paise = (cart['cart_total_paise'] if cart['cart_items']
                   else int(single.price_paise or 0) if single else 0)

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        error = _checkout_email_error(email)
        if not items:
            messages.error(request, 'The demo cart is empty. Choose a pack first.')
            return redirect('store')
        if error:
            messages.error(request, error)
        else:
            # orders.create_demo_order writes the purchase rows *and* updates the
            # per-email total in customer_spend, in one transaction.
            purchases, _spend = create_demo_order(email, items)
            request.session[ORDER_SESSION_KEY] = [p.pk for p in purchases]
            request.session[CART_SESSION_KEY] = []
            request.session.modified = True
            return redirect('order_confirmation')

    return render(request, 'checkout.html', {
        'items': items,
        'item_count': len(items),
        'total_paise': total_paise,
        'total': _money(total_paise),
        'cart_count': len(items),
        'demo_store': getattr(settings, 'DEMO_STORE', True),
    })


def order_confirmation(request):
    """Receipt for the demo order just placed."""
    ids = request.session.get(ORDER_SESSION_KEY) or []
    purchases = list(Purchase.objects.select_related('product')
                     .filter(pk__in=ids).order_by('pk')) if ids else []
    if not purchases:
        raw_order = (request.GET.get('order') or '').strip()
        if raw_order.isdigit():
            purchase = Purchase.objects.select_related('product').filter(pk=int(raw_order)).first()
            purchases = [purchase] if purchase else []
    if not purchases:
        messages.info(request, 'No demo order to show. Choose a pack to start one.')
        return redirect('store')

    total = sum(int(p.amount_paise or 0) for p in purchases)
    email = purchases[0].email
    spend = spend_for(email)
    return render(request, 'order_confirmation.html', {
        'purchases': purchases,
        'order_number': purchases[0].pk,
        'email': email,
        'total': _money(total),
        'total_paise': total,
        'placed_at': purchases[0].created_at,
        'spend': spend,
        'spend_total': spend.total_display if spend else _money(0),
        'spend_orders': spend.order_count if spend else 0,
        'cart_count': 0,
    })


__all__ = [
    'index', 'browse', 'categories', 'upload', 'upload_video',
    'player', 'embed', 'screening', 'stream_video', 'stream_as_file',
    'events', 'analyze', 'health',
    'store', 'product_detail', 'add_to_cart', 'remove_from_cart',
    'checkout', 'order_confirmation',
    'browser_page', 'browser_asset',
    'run_screening', 'screening_report', 'sensitivity_from_request',
    'get_db_connection', 'get_video_store', 'decorate_videos',
]




