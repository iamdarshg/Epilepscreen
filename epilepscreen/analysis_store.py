"""Persist detected hazard events into MySQL."""
import datetime
import json

from photosensitive.analyzer import HazardEvent, RiskProfile


def save_events(video_hash: int, events: list[HazardEvent]) -> int:
    """Insert hazard events for a video into MySQL. Returns count inserted."""
    if not events:
        return 0
    from epilepscreen.views import get_db_connection

    cnx = None
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        # Delete existing events for this video to prevent duplicates
        cursor.execute(
            "DELETE FROM hazard_event WHERE video_hash = %s",
            (video_hash,),
        )
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
        return len(events)
    except Exception as err:
        print(f"Error saving events: {err}")
        return 0
    finally:
        if cnx:
            cnx.close()


def save_analysis(video_hash: int, profile: RiskProfile) -> None:
    """Record that a video was analyzed, even when it came back safe.

    Safe videos store no hazard events, so without this row the site
    could never tell "analyzed and safe" apart from "never analyzed".
    """
    from epilepscreen.views import get_db_connection

    cnx = None
    try:
        cnx = get_db_connection()
        cursor = cnx.cursor()
        cursor.execute(
            "REPLACE INTO analysis (video_hash, is_safe, risk_flags, "
            "checked_at) VALUES (%s, %s, %s, %s)",
            (video_hash, int(profile.is_safe),
             json.dumps(profile.risk_flags), datetime.datetime.now()),
        )
        cnx.commit()
        cursor.close()
    except Exception as err:
        print(f"Error saving analysis: {err}")
    finally:
        if cnx:
            cnx.close()
