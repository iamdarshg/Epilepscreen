"""Bulk-import a folder of media files using a thread pool.

Usage:
    python manage.py ingest_media <directory> [--recursive] [--workers 4]
        [--category "Movie"] [--auto-category] [--analyze]
        [--extensions mp4,mkv,mp3,flac]

Every file gets its own mysql.connector connection (connections are never
shared between threads). Hashes are content-based, so re-running ingest on
the same folder skips files that are already stored.
"""
import concurrent.futures
import datetime
import hashlib
import lzma
import os

import mysql.connector
from django.core.management.base import BaseCommand, CommandError

from epilepscreen.media import (
    EXT_CONTENT_TYPES,
    content_type_for,
    is_audio_content,
    normalize_category,
    probe_media,
    suggest_category,
)

MAX_BYTES = 100 * 1024 * 1024


def iter_media_files(directory, recursive=False, extensions=None):
    """Yield media file paths under a directory. Pure: no database."""
    if extensions is None:
        wanted = set(EXT_CONTENT_TYPES)
    else:
        wanted = {e if e.startswith(".") else f".{e}"
                  for e in (x.strip().lower() for x in extensions)}
    if recursive:
        walker = (os.path.join(root, f)
                  for root, _, files in os.walk(directory) for f in files)
    else:
        walker = (os.path.join(directory, f)
                  for f in sorted(os.listdir(directory)))
    for path in walker:
        if os.path.isfile(path) \
                and os.path.splitext(path)[1].lower() in wanted:
            yield path


def ingest_file(path, category=None, auto_category=False, do_analyze=False):
    """Import one file. Opens its own DB connection, so threads are safe.

    Returns (hash, title, status) where status is a short human string.
    """
    from epilepscreen.views import get_db_connection

    title = os.path.splitext(os.path.basename(path))[0] or "Untitled"
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return (None, title, f"unreadable: {exc}")
    if len(raw) > MAX_BYTES:
        return (None, title, "skipped: over 100MB")
    content_type = content_type_for(path)
    cat = normalize_category(category)
    if cat is None and auto_category:
        info = probe_media(path) or {}
        cat = suggest_category(
            duration_s=info.get("duration_s"),
            width=info.get("width"), height=info.get("height"),
            title=title,
            audio_only=is_audio_content(content_type))
    # Content hash: the same file always maps to the same PRIMARY KEY,
    # so duplicates are rejected by MySQL instead of stored twice.
    hash_val = int(hashlib.sha256(raw).hexdigest()[:15], 16)
    blob = lzma.compress(raw)
    try:
        cnx = get_db_connection()
        try:
            cursor = cnx.cursor()
            cursor.execute(
                "INSERT INTO epilepsy (hash, time_uploaded, title, "
                "category, content_type, movie) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (hash_val, datetime.datetime.now(), title, cat,
                 content_type, blob),
            )
            cnx.commit()
            cursor.close()
        finally:
            cnx.close()
    except mysql.connector.errors.IntegrityError:
        return (hash_val, title, "duplicate: already stored")
    except mysql.connector.Error as err:
        return (None, title, f"db error: {err}")

    if do_analyze and not is_audio_content(content_type):
        from photosensitive.analyze_video import analyze_video_file
        from epilepscreen.analysis_store import save_analysis, save_events
        try:
            profile = analyze_video_file(path)
        except Exception as exc:
            return (hash_val, title, f"stored, analysis failed: {exc}")
        save_events(hash_val, profile.events)
        save_analysis(hash_val, profile)
        verdict = "safe" if profile.is_safe else "risky"
        return (hash_val, title, f"stored, analyzed: {verdict}")
    return (hash_val, title, "stored")


class Command(BaseCommand):
    help = "Bulk-import a folder of video/audio files with a thread pool."

    def add_arguments(self, parser):
        parser.add_argument("directory", type=str)
        parser.add_argument("--recursive", action="store_true",
                            help="descend into subdirectories")
        parser.add_argument("--workers", type=int, default=4,
                            help="thread pool size (default 4)")
        parser.add_argument("--category", type=str, required=False,
                            help="fixed category for every file")
        parser.add_argument("--auto-category", action="store_true",
                            help="guess Short/Movie/Music Video from footage")
        parser.add_argument("--analyze", action="store_true",
                            help="run photosensitive analysis per file")
        parser.add_argument("--extensions", type=str, required=False,
                            help="comma-separated, e.g. mp4,mkv,mp3,flac")

    def handle(self, *args, **options):
        directory = options["directory"]
        if not os.path.isdir(directory):
            raise CommandError(f"not a directory: {directory}")
        exts = options["extensions"].split(",") \
            if options["extensions"] else None
        files = list(iter_media_files(directory, options["recursive"], exts))
        if not files:
            self.stdout.write("No media files found.")
            return
        workers = max(1, options["workers"])
        counts = {}
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers) as pool:
            futures = {pool.submit(
                ingest_file, p,
                options["category"], options["auto_category"],
                options["analyze"]): p for p in files}
            for fut in concurrent.futures.as_completed(futures):
                _hash, title, status = fut.result()
                group = status.split(",")[0].split(":")[0].strip()
                counts[group] = counts.get(group, 0) + 1
                self.stdout.write(f"{title}: {status}")
        summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        self.stdout.write(f"Done: {summary}.")
