"""Persist screening results: hazard events plus one verdict row per video.

The writes are plain SQL against the tables migration 0003 creates, so the
same code path works on SQLite and MySQL. Both writers are called from
`epilepscreen.views.run_screening` inside one request.
"""
import datetime
import json

from django.db import DatabaseError, connection, transaction

from photosensitive.analyzer import HazardEvent, RiskProfile


def save_events(video_hash: int, events: list[HazardEvent]) -> int:
    """Replace the stored events for a video. Returns how many were written.

    Deleting first keeps a re-screening from stacking duplicate rows on top of
    yesterday's result.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM hazard_event WHERE video_hash = %s", (video_hash,))
            if not events:
                return 0
            now = datetime.datetime.now()
            rows = [
                (video_hash, event.kind, float(event.start_time),
                 float(event.end_time), json.dumps(event.attributes), now)
                for event in events
            ]
            cursor.executemany(
                "INSERT INTO hazard_event "
                "(video_hash, kind, start_time, end_time, attributes, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)", rows)
        return len(rows)


def save_analysis(video_hash: int, profile: RiskProfile) -> None:
    """Record the verdict, so 'screened and safe' is distinguishable from
    'never screened'. REPLACE keeps exactly one row per video."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "REPLACE INTO analysis (video_hash, is_safe, risk_flags, checked_at) "
                "VALUES (%s, %s, %s, %s)",
                (int(video_hash), int(bool(profile.is_safe)),
                 json.dumps(profile.risk_flags), datetime.datetime.now()))
    except DatabaseError as exc:
        raise DatabaseError(f'Could not store the analysis: {exc}') from exc


def clear_analysis(video_hash: int) -> None:
    """Forget a screening (used when a video is re-uploaded under a new hash)."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM hazard_event WHERE video_hash = %s", (video_hash,))
            cursor.execute("DELETE FROM analysis WHERE video_hash = %s", (video_hash,))