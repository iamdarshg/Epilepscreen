"""
Epilepscreen Views - Video rental platform with SQLite/MySQL support.
"""

import hashlib
import datetime
import json
import os
import lzma
import mimetypes
from typing import Optional, Dict, Any, List
from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.conf import settings
from django.views.decorators.clickjacking import xframe_options_exempt
from django.db import connection


class VideoStore:
    """Database store using Django's DB connection (SQLite or MySQL)."""

    def __init__(self):
        pass

    def get_cursor(self):
        return connection.cursor()

    def get_videos(self, search_query=None, category=None, limit=20, offset=0):
        cursor = self.get_cursor()
        if category and search_query:
            cursor.execute(
                "SELECT hash, time_uploaded, title, category, content_type, movie FROM epilepsy "
                "WHERE LOWER(category) = LOWER(%s) AND LOWER(title) LIKE LOWER(%s) AND movie IS NOT NULL "
                "ORDER BY time_uploaded DESC LIMIT %s OFFSET %s",
                (category.lower(), f"%{search_query.lower()}%", limit, offset)
            )
        elif category:
            cursor.execute(
                "SELECT hash, time_uploaded, title, category, content_type, movie FROM epilepsy "
                "WHERE LOWER(category) = LOWER(%s) AND movie IS NOT NULL "
                "ORDER BY time_uploaded DESC LIMIT %s OFFSET %s",
                (category.lower(), limit, offset)
            )
        elif search_query:
            cursor.execute(
                "SELECT hash, time_uploaded, title, category, content_type, movie FROM epilepsy "
                "WHERE LOWER(title) LIKE LOWER(%s) AND movie IS NOT NULL "
                "ORDER BY time_uploaded DESC LIMIT %s OFFSET %s",
                (f"%{search_query.lower()}%", limit, offset)
            )
        else:
            cursor.execute(
                "SELECT hash, time_uploaded, title, category, content_type, movie FROM epilepsy "
                "WHERE movie IS NOT NULL ORDER BY time_uploaded DESC LIMIT %s OFFSET %s",
                (limit, offset)
            )
        columns = [col[0] for col in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_video_by_hash(self, video_hash):
        cursor = self.get_cursor()
        cursor.execute(
            "SELECT hash, time_uploaded, title, category, content_type, movie FROM epilepsy WHERE hash = %s",
            (video_hash,)
        )
        columns = [col[0] for col in cursor.description] if cursor.description else []
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None

    def get_products(self, active=True, product_type=None):
        cursor = self.get_cursor()
        if product_type:
            cursor.execute(
                "SELECT * FROM store_products WHERE active = %s AND product_type = %s ORDER BY price_cents ASC",
                (int(active), product_type)
            )
        else:
            cursor.execute(
                "SELECT * FROM store_products WHERE active = %s ORDER BY price_cents ASC",
                (int(active),)
            )
        columns = [col[0] for col in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def create_purchase(self, product_id, user_email, total_cents, status='completed'):
        cursor = self.get_cursor()
        now = datetime.datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO purchases (product_id, email, payment_method, card_last4, status, created_at, amount_cents, currency) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (product_id, user_email, 'card', '', status, now, total_cents, 'USD')
        )
        connection.commit()
        return cursor.lastrowid


_video_store = None


def get_video_store():
    global _video_store
    if _video_store is None:
        _video_store = VideoStore()
    return _video_store


class VideoFormatValidator:
    SUPPORTED_FORMATS = {
        'video/mp4': {'min_resolution': '480p', 'min_framerate': 30},
        'video/webm': {'min_resolution': '480p', 'min_framerate': 30},
        'video/quicktime': {'min_resolution': '480p', 'min_framerate': 30},
        'video/x-msvideo': {'min_resolution': '480p', 'min_framerate': 30},
    }

    def validate(self, video_file):
        errors = []
        file_name = getattr(video_file, 'name', '')
        mime_type = getattr(video_file, 'content_type', None)
        if not mime_type or mime_type.startswith('application/'):
            errors.append('Unsupported container format')
        if not self._validate_format_name(file_name):
            errors.append('Invalid video format name')
        if not mime_type or not mime_type.startswith('video/'):
            errors.append('File is not a video')
        if errors:
            return {'valid': False, 'format': None, 'mime_type': None, 'errors': errors}
        return {'valid': True, 'format': 'HD', 'mime_type': mime_type}

    def _validate_format_name(self, filename):
        if '.' not in filename:
            return False
        ext = filename.rsplit('.', 1)[-1].lower()
        return ext in ['mp4', 'webm', 'mov', 'avi', 'mkv', 'flv', 'm4v', '3gp', 'ogv']


video_format_validator = VideoFormatValidator()


def validate_video_format(filename, mime_type=None, content_type=None):
    mime_type = mime_type or content_type or 'video/mp4'
    extension_mimes = {
        'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
        'avi': 'video/x-msvideo', 'mkv': 'video/x-matroska', 'flv': 'video/x-flv',
        'm4v': 'video/x-m4v', '3gp': 'video/3gpp', 'ogv': 'video/ogg'
    }
    if '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower()
        mime_type = extension_mimes.get(ext, mime_type)
    return {'format_name': 'HD', 'mime_type': mime_type, 'is_video': mime_type.startswith('video/')}


# --- Views ---

def index(request):
    store = get_video_store()
    try:
        videos = store.get_videos(limit=20)
    except Exception:
        videos = []
    try:
        products = store.get_products(active=True)
    except Exception:
        products = []
    return render(request, 'browse.html', {
        'videos': videos,
        'products': products,
        'q': '',
        'category': '',
        'categories': [],
    })


def browse(request):
    store = get_video_store()
    q = (request.GET.get("q") or "").strip()
    category = (request.GET.get("category") or "").strip()
    try:
        videos = store.get_videos(search_query=q or None, category=category or None, limit=50)
    except Exception:
        videos = []
    try:
        products = store.get_products(active=True)
    except Exception:
        products = []
    categories = list(set(v.get('category') for v in videos if v.get('category')))
    return render(request, 'browse.html', {
        'videos': videos, 'q': q, 'category': category,
        'products': products, 'categories': categories,
    })


EXTERNAL_STORES = [
    {
        'name': 'Internet Archive',
        'url': 'https://archive.org/details/movies&and[]=subject%3A%22medical%22',
        'icon': '🏛',
        'description': 'Public domain medical and educational videos. Download MP4, AVI, OGG.',
    },
    {
        'name': 'NIH VideoCast',
        'url': 'https://videocast.nih.gov/',
        'icon': '🏥',
        'description': 'Official NIH medical video library. Lectures, procedures, and research footage.',
    },
    {
        'name': 'CDC Media Library',
        'url': 'https://www.cdc.gov/media/library/index.html',
        'icon': '📡',
        'description': 'Centers for Disease Control public health videos and B-roll footage.',
    },
    {
        'name': 'Pixabay Videos',
        'url': 'https://pixabay.com/videos/search/medical/',
        'icon': '🎞',
        'description': 'Free stock medical footage. No attribution required. HD and 4K clips.',
    },
    {
        'name': 'Pexels Videos',
        'url': 'https://www.pexels.com/search/videos/medical/',
        'icon': '📹',
        'description': 'Free medical stock videos. Downloadable in multiple resolutions.',
    },
    {
        'name': 'MedlinePlus',
        'url': 'https://medlineplus.gov/videolist.html',
        'icon': '🩺',
        'description': 'Patient education videos from the National Library of Medicine.',
    },
]


def store(request):
    return render(request, 'store.html', {
        'stores': EXTERNAL_STORES,
    })


def add_to_cart(request, product_id):
    s = get_video_store()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM store_products WHERE id = %s", (product_id,))
        columns = [col[0] for col in cursor.description] if cursor.description else []
        row = cursor.fetchone()
        product = dict(zip(columns, row)) if row else None
        if not product:
            return JsonResponse({'error': 'Product not found'}, status=404)
        user_email = request.GET.get('email', 'guest@example.com')
        s.create_purchase(product_id, user_email, product['price_cents'], 'completed')
        return JsonResponse({
            'success': True,
            'product': {'name': product.get('title', 'Product'), 'price': f"${product['price_cents']/100:.2f}"}
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def stream_video(request, video_hash):
    store = get_video_store()
    try:
        row = store.get_video_by_hash(video_hash)
        if not row:
            raise Http404("Video not found")
        video_data = lzma.decompress(row['movie'])
        mime_type = row.get('content_type') or "video/mp4"
        size = len(video_data)
        range_header = request.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                start_str, _, end_str = range_header[6:].partition("-")
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else size - 1
                end = min(end, size - 1)
                if start >= size or start > end:
                    return HttpResponse(status=416)
            except ValueError:
                return HttpResponse(status=416)
            return HttpResponse(
                video_data[start:end + 1], status=206, content_type=mime_type,
                headers={"Content-Range": f"bytes {start}-{end}/{size}",
                         "Content-Length": str(end - start + 1), "Accept-Ranges": "bytes"}
            )
        return HttpResponse(video_data, content_type=mime_type, headers={"Accept-Ranges": "bytes"})
    except Exception as e:
        return HttpResponse(str(e), status=500)


@xframe_options_exempt
def stream_as_file(request, video_hash):
    return stream_video(request, video_hash)


def upload_video(request):
    if request.method == 'POST' and request.FILES.get('video_file'):
        video_file = request.FILES['video_file']
        title = request.POST.get('title', 'Untitled')
        category = request.POST.get('category', '')
        mime_type, _ = mimetypes.guess_type(video_file.name)
        if mime_type is None:
            mime_type = 'video/mp4'
        video_format = validate_video_format(video_file.name, mime_type, video_file.content_type)
        now = datetime.datetime.now()
        hash_input = f"{title}{now}{os.urandom(8)}".encode('utf-8')
        video_hash = int(hashlib.sha256(hash_input).hexdigest()[:15], 16)
        movie_blob = lzma.compress(video_file.read())
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO epilepsy (hash, time_uploaded, title, category, content_type, movie) VALUES (?, ?, ?, ?, ?, ?)",
            (video_hash, now.isoformat(), title, category or 'Other', video_format['mime_type'], movie_blob)
        )
        connection.commit()
        return redirect('browse')
    return redirect('browse')


def events(request, video_hash):
    store = get_video_store()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id, kind, start_time, end_time, attributes FROM hazard_event WHERE video_hash = ? ORDER BY start_time ASC", (video_hash,))
        columns = [col[0] for col in cursor.description] if cursor.description else []
        evts = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        evts = []
    return JsonResponse({"events": evts})


def analyze(request, video_hash):
    store = get_video_store()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT video_hash, is_safe, risk_flags, checked_at FROM analysis WHERE video_hash = %s", (video_hash,))
        columns = [col[0] for col in cursor.description] if cursor.description else []
        row = cursor.fetchone()
        analysis = dict(zip(columns, row)) if row else None
        if not analysis:
            return JsonResponse({'is_safe': None, 'risk_flags': None, 'analyzed': False})
        return JsonResponse({
            'is_safe': bool(analysis['is_safe']),
            'risk_flags': json.loads(analysis['risk_flags']) if analysis.get('risk_flags') else [],
            'analyzed': True
        })
    except Exception:
        return JsonResponse({'error': 'Database error'}, status=500)


def player(request, video_hash):
    store = get_video_store()
    video = store.get_video_by_hash(video_hash)
    if not video:
        raise Http404("Video not found")
    return render(request, 'player.html', {
        'title': video.get('title', 'Untitled'),
        'video': video,
        'stream_url': f'/stream/{video_hash}/',
        'store_url': '/store/',
        'events_url': f'/events/{video_hash}/',
        'event_count': 0,
    })


def categories(request):
    store = get_video_store()
    category = request.GET.get('category', '')
    search = request.GET.get('q', '')
    try:
        videos = store.get_videos(search_query=search or None, category=category or None, limit=50)
    except Exception:
        videos = []
    return render(request, 'browse.html', {
        'videos': videos, 'q': search, 'category': category,
        'products': [], 'categories': [category] if category else [],
    })


def upload(request):
    if request.method == 'POST' and request.FILES.get('video_file'):
        return upload_video(request)
    return redirect('browse')


def get_db_connection():
    return connection


__all__ = [
    'index', 'stream_video', 'upload_video', 'browse', 'store',
    'add_to_cart', 'events', 'analyze', 'player', 'categories', 'upload',
]
