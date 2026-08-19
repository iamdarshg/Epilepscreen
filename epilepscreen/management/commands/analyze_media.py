"""python manage.py analyze_media <path> [--hash <n>] -> JSON risk profile.

If --hash is given, detected hazard events are persisted into MySQL."""
import json
from django.core.management.base import BaseCommand

from photosensitive.analyze_video import analyze_video_file


class Command(BaseCommand):
    help = "Analyze a media file for photosensitive triggers and optionally store events."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str)
        parser.add_argument("--hash", type=int, required=False, help="video_hash to persist events for")

    def handle(self, *args, **options):
        profile = analyze_video_file(options["path"])
        stored = 0
        if options.get("hash") is not None:
            from epilepscreen.analysis_store import save_events
            stored = save_events(options["hash"], profile.events)
        payload = {
            "is_safe": profile.is_safe,
            "risk_flags": profile.risk_flags,
            "stored_events": stored,
            "events": [
                {"kind": e.kind, "start": e.start_time, "end": e.end_time,
                 "attributes": e.attributes}
                for e in profile.events
            ],
        }
        self.stdout.write(json.dumps(payload))
