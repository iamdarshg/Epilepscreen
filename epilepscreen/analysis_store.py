"""Persist detected hazard events into MySQL."""
import datetime
import json

from photosensitive.analyzer import HazardEvent


def save_events(video_hash: int, events: list[HazardEvent]) -> int:
    """Insert hazard events for a video into MySQL. Returns count inserted."""
    if not events:
        return 0
    from epilepscreen.views import get_db_connection

    cnx = get_db_connection()
    cursor = cnx.cursor()
    now = datetime.datetime.now()
    for e in events:
        cursor.execute(
            "INSERT INTO hazard_event "
            "(video_hash, kind, start_time, end_time, attributes, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (video_hash, e.kind, e.start_time, e.end_time,
             json.dumps(e.attributes), now),
        )
    cnx.commit()
    cursor.close()
    cnx.close()
    return len(events)
