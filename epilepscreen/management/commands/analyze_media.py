"""python manage.py analyze_media <path> [--hash <n>] [--fps 15] -> JSON report.

Prints the risk profile as JSON. With --hash, the detected hazard events and the
verdict are also written to the database for that library item.
"""
import json

from django.core.management.base import BaseCommand

from photosensitive.analyze_video import DEFAULT_TARGET_FPS, analyze_video_file


class Command(BaseCommand):
    help = "Analyze a media file for photosensitive triggers and optionally store events."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str)
        parser.add_argument("--hash", type=int, required=False,
                            help="video_hash to persist events for")
        parser.add_argument("--fps", type=float, default=DEFAULT_TARGET_FPS,
                            help=f"frames per second to sample (default {DEFAULT_TARGET_FPS:g})")

    def handle(self, *args, **options):
        profile = analyze_video_file(options["path"], target_fps=options["fps"])
        stored = 0
        if options.get("hash") is not None:
            from epilepscreen.analysis_store import save_analysis, save_events
            stored = save_events(options["hash"], profile.events)
            save_analysis(options["hash"], profile)
        payload = {
            "is_safe": profile.is_safe,
            "risk_flags": profile.risk_flags,
            "stored_events": stored,
            "summary": profile.summary(),
            "events": [
                {"kind": e.kind, "start": round(e.start_time, 3),
                 "end": round(e.end_time, 3), "attributes": e.attributes}
                for e in profile.events
            ],
        }
        self.stdout.write(json.dumps(payload))