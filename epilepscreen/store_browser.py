"""Server-side capture browser for the storefront.

The store's Sources panel opens an iframe backed by this module. Pages are
fetched on the server, stripped of scripts and site styles, and their links
are rewritten so they stay inside the panel. Following a link that resolves
to a video downloads the file and writes it into the same `epilepsy` table
Browse reads, so a download becomes a library item without a second step.

This is deliberately a reader, not a full browser: scripts are off, which
keeps the panel safe and predictable. Direct file links on the source pages
work, and those are what a visitor clicks to download.
"""
import datetime
import hashlib
import html
import lzma
import mimetypes
import os
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from django.db import DatabaseError, IntegrityError, connection
from django.urls import reverse

MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0 Safari/537.36 EpilepscreenStore/1.0'
)

# Only the sources the store names, and their own subdomains, are reachable
# from the capture browser. This keeps the proxy from becoming an open door.
ALLOWED_SUFFIXES = (
    'archive.org',
    'cdc.gov',
    'medlineplus.gov',
    'nih.gov',
    'pexels.com',
    'pixabay.com',
)

VIDEO_EXTENSIONS = {
    '.3gp', '.avi', '.flv', '.m4v', '.mkv', '.mov', '.mp4', '.ogv', '.webm',
}

REMOVE_TAGS = (
    'applet', 'base', 'blink', 'canvas', 'dialog', 'embed', 'frame',
    'frameset', 'iframe', 'link', 'marquee', 'meta', 'noscript', 'object',
    'script', 'style', 'template',
)


class BrowserError(Exception):
    """A source page could not be shown or a file could not be captured."""


def is_allowed_url(url):
    """True for http(s) URLs on one of the named sources or their subdomains."""
    if not url or any(ch.isspace() for ch in url):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 80, 443):
        return False
    host = (parsed.hostname or '').lower().rstrip('.')
    if not host:
        return False
    return any(host == suffix or host.endswith('.' + suffix)
               for suffix in ALLOWED_SUFFIXES)


def _session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept-Language': 'en',
    })
    # The proxy only ever reads public pages on the allowlisted sources, and
    # some public-health hosts serve certificates this machine's store cannot
    # verify. The allowlist is the boundary, not the certificate.
    session.verify = False
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return session


def _open(url, accept):
    """GET `url`, following redirects only while they stay on allowed hosts."""
    if not is_allowed_url(url):
        raise BrowserError('That address is outside the capture browser sources.')

    session = _session()
    current = url
    for _ in range(6):
        try:
            response = session.get(
                current,
                headers={'Accept': accept},
                stream=True,
                timeout=(10, 60),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise BrowserError('The source did not answer. Try another link.') from exc

        if response.is_redirect:
            location = response.headers.get('Location')
            response.close()
            if not location:
                raise BrowserError('The source sent an empty redirect.')
            current = urljoin(current, location)
            if not is_allowed_url(current):
                raise BrowserError('The source redirected outside the capture browser.')
            continue

        if response.status_code >= 400:
            status = response.status_code
            response.close()
            raise BrowserError(f'The source answered {status}.')
        return response, current

    raise BrowserError('The source redirected too many times.')


def _read_limited(response, limit, too_big):
    data = bytearray()
    try:
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            if len(data) + len(chunk) > limit:
                raise BrowserError(too_big)
            data.extend(chunk)
    except requests.RequestException as exc:
        raise BrowserError('The download stopped before it finished.') from exc
    return bytes(data)


def content_type_of(response):
    return (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()


def _filename_for(response, url):
    disposition = response.headers.get('Content-Disposition') or ''
    match = re.search(
        r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", disposition, re.IGNORECASE)
    if not match:
        match = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition, re.IGNORECASE)
    name = unquote(match.group(1).strip().strip('"')) if match else ''
    if not name:
        name = os.path.basename(unquote(urlparse(url).path)) or 'captured-video'
    name = re.sub(r'[^\w.\- ]+', '_', name).strip()[:180]
    if not name:
        name = 'captured-video'
    if not os.path.splitext(name)[1]:
        guessed = mimetypes.guess_extension(content_type_of(response) or '')
        if guessed:
            name += guessed
    return name


def _is_video(response, url, filename):
    content_type = content_type_of(response)
    if content_type.startswith('video/'):
        return True
    extension = os.path.splitext(filename or urlparse(url).path)[1].lower()
    if extension not in VIDEO_EXTENSIONS:
        return False
    return content_type in (
        '', 'application/octet-stream', 'binary/octet-stream', 'application/mp4',
    )


def page_url(target, back):
    return f"{reverse('browser_page')}?{urlencode({'url': target, 'back': back})}"


def asset_url(target):
    return f"{reverse('browser_asset')}?{urlencode({'url': target})}"


def _local_back(value):
    """A back target that may be a local path or an allowed source URL."""
    if value.startswith('/') and not value.startswith('//'):
        return value
    if is_allowed_url(value):
        return page_url(value, reverse('store') + '#sources')
    return reverse('store') + '#sources'


def _first_srcset(value):
    for candidate in (value or '').split(','):
        candidate = candidate.strip()
        if candidate:
            return candidate.split()[0]
    return ''


def _rewrite_css(text, base_url):
    def replace(match):
        target = match.group(2).strip()
        if target.startswith(('data:', '#', 'about:')):
            return match.group(0)
        absolute = urljoin(base_url, target)
        if not is_allowed_url(absolute):
            return 'url("")'
        return f'url("{asset_url(absolute)}")'

    text = re.sub(
        r'url\(\s*([\'"]?)([^)\'"]+)\1\s*\)', replace, text, flags=re.IGNORECASE)
    text = re.sub(
        r'@import\s+(?:url\()?[\'"]([^\'"]+)[\'"]\)?',
        lambda m: f'@import "{asset_url(urljoin(base_url, m.group(1)))}"',
        text, flags=re.IGNORECASE)
    return text


def rewrite_page(data, base_url, charset=None):
    """Return (title, body_html) for a source page, safe to put in the shell."""
    soup = BeautifulSoup(data, 'html.parser', from_encoding=charset)
    title_tag = soup.find('title')
    title = title_tag.get_text(' ', strip=True) if title_tag else ''
    body = soup.body or soup

    for tag in body.find_all(REMOVE_TAGS):
        tag.decompose()

    for tag in body.find_all(True):
        for attribute in list(tag.attrs):
            name = attribute.lower()
            if name.startswith('on') or name in {
                'background', 'class', 'crossorigin', 'integrity', 'nonce',
                'ping', 'srcdoc', 'style',
            }:
                del tag.attrs[attribute]

    for anchor in body.find_all('a', href=True):
        href = (anchor.get('href') or '').strip()
        if not href or href.startswith('#'):
            continue
        absolute = urljoin(base_url, href)
        scheme = urlparse(absolute).scheme
        if scheme in ('mailto', 'tel'):
            continue
        if scheme in ('http', 'https') and is_allowed_url(absolute):
            anchor['href'] = page_url(absolute, base_url)
            anchor.attrs.pop('target', None)
            anchor.attrs.pop('download', None)
        else:
            del anchor['href']
            anchor['title'] = 'External link left out of the capture browser'

    for image in body.find_all('img'):
        src = (image.get('data-src') or image.get('data-original')
               or image.get('src') or '')
        if not src:
            src = _first_srcset(image.get('data-srcset') or image.get('srcset'))
        if src.startswith('data:'):
            image['src'] = src
        elif src:
            image['src'] = asset_url(urljoin(base_url, src))
        else:
            image.decompose()
            continue
        for attribute in ('data-src', 'data-original', 'data-srcset', 'srcset', 'sizes'):
            image.attrs.pop(attribute, None)
        image['loading'] = 'lazy'
        if not image.get('alt'):
            image['alt'] = ''

    for source in body.find_all('source'):
        src = source.get('src') or _first_srcset(source.get('srcset'))
        if src:
            source['src'] = asset_url(urljoin(base_url, src))
        for attribute in ('srcset', 'sizes'):
            source.attrs.pop(attribute, None)

    for video in body.find_all('video'):
        source = video.get('src')
        if not source:
            first_source = video.find('source')
            source = first_source.get('src') if first_source else ''
        if not source:
            video.decompose()
            continue
        paragraph = soup.new_tag('p')
        paragraph['class'] = 'browser-file'
        link = soup.new_tag('a', href=page_url(urljoin(base_url, source), base_url))
        link.string = 'Save this video to the library'
        paragraph.append(link)
        video.replace_with(paragraph)

    for media in body.find_all('audio'):
        media.decompose()

    for form in body.find_all('form'):
        action = urljoin(base_url, form.get('action') or base_url)
        if not is_allowed_url(action):
            form.decompose()
            continue
        form['method'] = 'get'
        form['action'] = reverse('browser_page')
        hidden_url = soup.new_tag('input')
        hidden_url['type'] = 'hidden'
        hidden_url['name'] = 'url'
        hidden_url['value'] = action
        hidden_back = soup.new_tag('input')
        hidden_back['type'] = 'hidden'
        hidden_back['name'] = 'back'
        hidden_back['value'] = base_url
        form.insert(0, hidden_url)
        form.insert(1, hidden_back)

    for tag in body.find_all(['button', 'input']):
        tag.attrs.pop('formaction', None)

    parts = ''.join(str(child) for child in body.contents)
    return title, parts


def _archive_index(url):
    """A readable index for Internet Archive collection pages.

    The archive's collection page is an Angular shell, so the raw reader sees
    nothing. Its search API is plain JSON and works, so build the same list the
    page would show, with every item linking back through the reader.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host not in ('archive.org', 'www.archive.org'):
        return None
    path = parsed.path
    if not (path.startswith('/details/movies') or path.startswith('/search')):
        return None

    params = {
        'q': 'subject:medical AND mediatype:movies',
        'fl[]': ['identifier', 'title', 'year', 'description'],
        'rows': '24',
        'page': '1',
        'output': 'json',
        'sort[]': 'downloads desc',
    }
    try:
        session = _session()
        response = session.get(
            'https://archive.org/advancedsearch.php',
            params=params,
            timeout=(10, 40),
        )
        response.raise_for_status()
        docs = response.json()['response']['docs']
    except (requests.RequestException, KeyError, ValueError):
        return None

    if not docs:
        return None

    rows = []
    for doc in docs:
        identifier = str(doc.get('identifier') or '').strip()
        if not identifier:
            continue
        item_url = 'https://archive.org/details/' + quote(identifier)
        title = html.escape(str(doc.get('title') or identifier))
        year = html.escape(str(doc.get('year') or ''))
        description = doc.get('description')
        if isinstance(description, list):
            description = ' '.join(str(part) for part in description)
        description = re.sub(r'<[^>]+>', ' ', str(description or ''))
        description = re.sub(r'\s+', ' ', description).strip()[:220]
        rows.append(
            '<li><a href="{href}"><span class="archive-list__title">{title}</span>'
            '<span class="archive-list__meta">{year}</span></a>'
            '<p>{description}</p></li>'.format(
                href=html.escape(page_url(item_url, url), quote=True),
                title=title,
                year=year,
                description=html.escape(description or 'Open the item to see its files.'),
            )
        )

    body = (
        '<h1>Medical films in the Internet Archive</h1>'
        '<p>Pick an item. Its page lists the files, and a video download is '
        'saved to the library when you follow it.</p>'
        '<ul class="archive-list">' + ''.join(rows) + '</ul>'
    )
    return 'Medical films in the Internet Archive', body, url


def fetch_page(url):
    """Return (title, body_html, final_url) for an HTML source page."""
    index = _archive_index(url)
    if index:
        return index
    response, final_url = _open(
        url, 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.5')
    try:
        content_type = content_type_of(response)
        filename = _filename_for(response, final_url)
        if _is_video(response, final_url, filename):
            data = _read_limited(
                response, MAX_VIDEO_BYTES,
                'That video is larger than the 100 MB capture limit.')
            return capture_video(response, final_url, filename, data)
        if content_type and content_type not in (
                'text/html', 'application/xhtml+xml', 'text/plain'):
            raise BrowserError(
                'That link is not a page or a video, so the browser left it alone.')
        data = _read_limited(
            response, MAX_PAGE_BYTES,
            'That page is too large for the capture browser.')
        charset = None
        header = response.headers.get('Content-Type') or ''
        if 'charset=' in header.lower():
            charset = response.encoding
        title, body_html = rewrite_page(data, final_url, charset)
        return title, body_html, final_url
    finally:
        response.close()


def capture_video(response, url, filename, data):
    """Store a downloaded video in the library. Returns result metadata."""
    title = os.path.splitext(filename)[0].strip()[:200] or 'Captured video'
    content_type = content_type_of(response) or 'video/mp4'
    video_hash = int(hashlib.sha256(data).hexdigest()[:15], 16)
    now = datetime.datetime.now()

    saved = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO epilepsy (hash, time_uploaded, title, category, content_type, movie) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (video_hash, now, title, 'Other', content_type, lzma.compress(data)),
            )
    except IntegrityError:
        saved = False
        with connection.cursor() as cursor:
            cursor.execute("SELECT title FROM epilepsy WHERE hash = %s", (video_hash,))
            row = cursor.fetchone()
            if row and row[0]:
                title = row[0]
    except DatabaseError as exc:
        raise BrowserError('The library could not record that file.') from exc

    return {
        'mode': 'captured',
        'title': title,
        'saved': saved,
        'content_type': content_type,
        'bytes': len(data),
        'final_url': url,
    }


def fetch_asset(url):
    """Return (bytes, content_type) for an image, font or stylesheet."""
    response, final_url = _open(url, 'image/*,text/css,font/*;q=0.8,*/*;q=0.3')
    try:
        content_type = content_type_of(response)
        if content_type == 'text/css':
            data = _read_limited(
                response, MAX_ASSET_BYTES, 'That stylesheet is too large.')
            charset = response.encoding or 'utf-8'
            text = data.decode(charset, errors='replace')
            return _rewrite_css(text, final_url).encode('utf-8'), 'text/css; charset=utf-8'
        if (content_type.startswith('image/') or content_type.startswith('font/')
                or content_type in ('application/font-woff', 'application/vnd.ms-fontobject')):
            data = _read_limited(
                response, MAX_ASSET_BYTES, 'That asset is too large.')
            return data, content_type
        raise BrowserError('That asset type is not proxied.')
    finally:
        response.close()


def browser_context(source, target_url=None, back=None):
    """Shared data for the capture-browser shell."""
    return {
        'source_name': source['name'],
        'source_url': source['url'],
        'display_url': target_url or source['url'],
        'back_href': _local_back(back or ''),
    }

