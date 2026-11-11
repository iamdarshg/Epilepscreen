"""Epilepscreen views - video library and storefront, backed by MySQL."""

import hashlib
import datetime
import json
import os
import lzma
from urllib.parse import urlparse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import render, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.clickjacking import xframe_options_exempt, xframe_options_sameorigin
from django.views.decorators.http import require_POST
from django.db import connection, DatabaseError

from epilepscreen.media import BUILTIN_CATEGORIES, content_type_for, normalize_category
from epilepscreen.models import Purchase, StoreProduct
from epilepscreen.store_browser import (
    BrowserError,
    browser_context,
    fetch_asset,
    fetch_page,
    is_allowed_url,
)


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
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _money(cents):
    """Render a cent amount as a short dollar string."""
    cents = int(cents or 0)
    amount = f"{cents / 100:,.2f}".rstrip('0').rstrip('.')
    return f"${amount}"


def _decorate_product(product):
    cents = int(product.price_cents or 0)
    amount = f"{cents / 100:,.2f}".rstrip('0').rstrip('.')
    product.price_amount = amount
    product.price_display = f"${amount}"
    product.kind_label = PRODUCT_TYPE_LABELS.get(product.product_type, product.product_type)
    return product


def _recent_videos(limit=4):
    """The newest library items, without reading their compressed blobs."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT hash, time_uploaded, title, category, content_type "
                "FROM epilepsy WHERE movie IS NOT NULL "
                "ORDER BY time_uploaded DESC LIMIT %s",
                (limit,),
            )
            columns = [col[0] for col in cursor.description] if cursor.description else []
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except DatabaseError:
        return []


def _library_count():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM epilepsy WHERE movie IS NOT NULL")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
    except DatabaseError:
        return 0


def _store_context(request, selected_product_id=None):
    try:
        products = [_decorate_product(p) for p in
                    StoreProduct.objects.filter(active=True).order_by('price_cents')]
    except DatabaseError:
        products = []

    product_ids = {p.pk for p in products}
    if selected_product_id not in product_ids:
        selected_product_id = products[0].pk if products else None
    selected_product = next(
        (p for p in products if p.pk == selected_product_id), None)

    recent_order = None
    raw_order = (request.GET.get('order') or '').strip()
    if raw_order.isdigit():
        try:
            recent_order = (Purchase.objects.select_related('product')
                            .filter(pk=int(raw_order)).first())
        except DatabaseError:
            recent_order = None

    return {
        'products': products,
        'hero_product': products[0] if products else None,
        'selected_product': selected_product,
        'selected_product_id': selected_product_id,
        'stores': EXTERNAL_STORES,
        'categories': BUILTIN_CATEGORIES,
        'max_upload_mb': MAX_UPLOAD_BYTES // (1024 * 1024),
        'recent_videos': _recent_videos(),
        'library_count': _library_count(),
        'recent_order': recent_order,
    }


def store(request):
    raw_product = (request.GET.get('product') or '').strip()
    selected_product_id = int(raw_product) if raw_product.isdigit() else None
    return render(request, 'store.html', _store_context(request, selected_product_id))


def _source_for(url):
    """Name the store source a proxied address belongs to."""
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
    context.update({
        'mode': 'page',
        'title': '',
        'body_html': '',
        'error': '',
    })

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
    """Proxy one image, font, or stylesheet for the reader shell."""
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


def product_detail(request, product_id):
    product = StoreProduct.objects.filter(pk=product_id, active=True).first()
    if not product:
        raise Http404("Product not found")
    return redirect(f"{reverse('store')}?product={product.pk}#order")


@require_POST
def checkout(request):
    product_id = (request.POST.get('product_id') or '').strip()
    email = (request.POST.get('email') or '').strip()
    product = StoreProduct.objects.filter(
        pk=product_id, active=True).first() if product_id.isdigit() else None

    errors = []
    if not product:
        errors.append('Choose a pack from the catalog.')
    if not email:
        errors.append('Enter an email address for the invoice.')
    else:
        try:
            validate_email(email)
        except ValidationError:
            errors.append('Enter a valid email address.')

    if errors:
        for error in errors:
            messages.error(request, error)
        target = f"{reverse('store')}?product={product.pk}#order" if product else f"{reverse('store')}#order"
        return redirect(target)

    try:
        purchase = Purchase.objects.create(
            product=product,
            email=email,
            payment_method='invoice',
            status='pending',
            amount_cents=product.price_cents,
            currency='USD',
        )
    except DatabaseError:
        messages.error(request, 'The order could not be recorded. Try again.')
        return redirect(f"{reverse('store')}?product={product.pk}#order")

    return redirect(f"{reverse('store')}?order={purchase.pk}#order")


@require_POST
def add_to_cart(request, product_id):
    product = StoreProduct.objects.filter(pk=product_id, active=True).first()
    if not product:
        return JsonResponse({'error': 'Product not found'}, status=404)

    email = (request.POST.get('email') or '').strip()
    if not email:
        return JsonResponse({'error': 'Email is required'}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'error': 'Enter a valid email address'}, status=400)

    try:
        purchase = Purchase.objects.create(
            product=product,
            email=email,
            payment_method='invoice',
            status='pending',
            amount_cents=product.price_cents,
            currency='USD',
        )
    except DatabaseError:
        return JsonResponse({'error': 'The order could not be recorded'}, status=500)

    return JsonResponse({
        'success': True,
        'order_id': purchase.pk,
        'product': {'name': product.title, 'price': _money(product.price_cents)},
    })


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


def _upload_target(request):
    return 'store' if request.POST.get('next') == 'store' else 'browse'


def _store_with_status(request, status):
    return render(request, 'store.html', _store_context(request), status=status)


def upload_video(request):
    if request.method != 'POST' or not request.FILES.get('video_file'):
        messages.error(request, 'Choose a video file to upload.')
        return redirect(_upload_target(request))

    video_file = request.FILES['video_file']
    if video_file.size > MAX_UPLOAD_BYTES:
        messages.error(request, f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        return _store_with_status(request, 413)

    title = (request.POST.get('title') or os.path.splitext(os.path.basename(video_file.name))[0]).strip()[:200]
    category = normalize_category(request.POST.get('category')) or 'Other'
    mime_type = content_type_for(video_file.name, getattr(video_file, 'content_type', None))
    if not mime_type.startswith('video/'):
        messages.error(request, 'That file is not a video. Upload MP4, WebM, MOV, AVI, or MKV.')
        return redirect(_upload_target(request))

    video_format = validate_video_format(video_file.name, mime_type, video_file.content_type)
    now = datetime.datetime.now()
    hash_input = f"{title}{now}{os.urandom(8)}".encode('utf-8')
    video_hash = int(hashlib.sha256(hash_input).hexdigest()[:15], 16)

    try:
        movie_blob = lzma.compress(video_file.read())
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO epilepsy (hash, time_uploaded, title, category, content_type, movie) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (video_hash, now, title, category, video_format['mime_type'], movie_blob)
        )
        connection.commit()
    except Exception:
        messages.error(request, 'The upload could not be stored. Try again.')
        return redirect(_upload_target(request))

    messages.success(request, f"Uploaded {title}. It is ready in Browse.")
    return redirect(_upload_target(request))


def events(request, video_hash):
    store = get_video_store()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id, kind, start_time, end_time, attributes FROM hazard_event WHERE video_hash = %s ORDER BY start_time ASC", (video_hash,))
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
    'browser_page', 'browser_asset',
    'product_detail', 'checkout', 'add_to_cart', 'events', 'analyze',
    'player', 'categories', 'upload',
]
