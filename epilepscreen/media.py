"""Media helpers: categories, content types, and file probing.

Everything here is pure Python with no database access, so it is easy to
test. Storage itself is lossless: uploads are kept byte-for-byte (lzma
compressed blob) and streamed back unchanged, never transcoded.
"""
import os

import cv2


# Built-in categories shown as suggestions. Users may type anything;
# anything not in this list is a user-defined category.
BUILTIN_CATEGORIES = ["Short", "Movie", "Music Video", "Music", "Other"]

# Movies count as long-form from 20 minutes up.
MOVIE_MIN_SECONDS = 20 * 60

MUSIC_KEYWORDS = (
    "official video",
    "official music video",
    "music video",
    "lyric video",
    "visualizer",
    " mv ",
    " m/v",
)

EXT_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}


def content_type_for(filename, uploaded_type=None):
    """Pick a MIME type for an upload: extension map first, then the
    browser-provided type, then a safe download fallback."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in EXT_CONTENT_TYPES:
        return EXT_CONTENT_TYPES[ext]
    if uploaded_type and (uploaded_type.startswith("video/")
                          or uploaded_type.startswith("audio/")):
        return uploaded_type
    return "application/octet-stream"


def is_audio_content(content_type):
    """True for audio uploads (music), which carry no visual triggers."""
    return (content_type or "").startswith("audio/")


def normalize_category(raw):
    """Clean up a user-typed category. Blank becomes None (unknown),
    which later steps may auto-fill."""
    text = (raw or "").strip()
    return text[:40] or None


def suggest_category(duration_s=None, width=None, height=None,
                     title="", audio_only=False):
    """Auto-classify a file when the user gave no category."""
    if audio_only:
        return "Music"
    lowered = f" {(title or '').lower()} "
    if any(k in lowered for k in MUSIC_KEYWORDS):
        return "Music Video"
    if duration_s is not None and duration_s >= MOVIE_MIN_SECONDS:
        return "Movie"
    if width and height and height > width:
        return "Short"
    return "Other"


def probe_media(path):
    """Read duration/dimensions of a video file with OpenCV.

    Returns {"duration_s", "width", "height"} or None if the file has no
    readable video track (e.g. audio-only uploads) or cannot be opened.
    """
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if not width or not height:
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = (frames / fps) if fps > 0 else None
        return {"duration_s": duration, "width": width, "height": height}
    except Exception:
        return None
    finally:
        cap.release()
