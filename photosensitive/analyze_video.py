"""Decode a video file into frames and run the detector core.

OpenCV is imported inside the functions on purpose: the rest of the package is
pure NumPy and can be unit-tested without an OpenCV build.

Sampling, not playback: we do not look at every frame. A 30 fps clip is read
every third frame to give a steady ~10 frames per second for analysis, which
keeps a two-minute film to about 1200 frames. The timestamps the analyser
reports therefore use the *effective* sampling rate (source fps / step), not
the rate we asked for.
"""
import json
import os
import shutil
import subprocess
import tempfile

import numpy as np

from photosensitive.analyzer import RiskProfile, analyze_frames

DEFAULT_TARGET_FPS = 15.0

# Frames are shrunk before analysis. Detectors work on average brightness and
# stripe structure, both of which survive downscaling, and a 480 px long edge
# is roughly 20x less work than 1080p.
MAX_DIMENSION = 480

# Hard cap so a broken file cannot loop forever inside a web request.
MAX_FRAMES = 20000

# ffmpeg gets a generous ceiling because a feature-length film takes a while to
# transcode. The analysis request is synchronous, but it should finish rather
# than leave a half-written proxy behind.
PROXY_TIMEOUT_S = 30 * 60


def _remove(path: str):
    """Best-effort removal of a temporary file."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _video_dimensions(path: str):
    """Width/height via ffprobe, without asking OpenCV to decode a frame."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe or not os.path.exists(path):
        return None
    try:
        completed = subprocess.run(
            [ffprobe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height', '-of', 'json', str(path)],
            capture_output=True, text=True, timeout=120, check=False)
        stream = json.loads(completed.stdout)['streams'][0]
        width, height = int(stream['width']), int(stream['height'])
    except (OSError, KeyError, IndexError, TypeError, ValueError,
            subprocess.SubprocessError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _low_res_proxy(path: str):
    """Return a temporary 480 px copy for OpenCV, or None if none is needed.

    Decoding a 4K film at full size is what exhausts memory on a small store;
    the detector only ever needs a small frame. ffmpeg does the one expensive
    decode, then OpenCV reads only the compact copy. If the source is already
    small it is safe to open directly.
    """
    if not os.path.exists(path):
        return None

    dimensions = _video_dimensions(path)
    if dimensions and max(dimensions) <= MAX_DIMENSION:
        return None

    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        if dimensions:
            raise ValueError(
                'This video is too large to screen without ffmpeg installed.')
        return None

    handle = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    handle.close()
    proxy_path = handle.name
    scale = (
        f'scale={MAX_DIMENSION}:{MAX_DIMENSION}:'
        'force_original_aspect_ratio=decrease:force_divisible_by=2'
    )
    command = [
        ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
        '-i', str(path), '-map', '0:v:0', '-an', '-vf', scale,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28',
        '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart',
        proxy_path,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True,
            timeout=PROXY_TIMEOUT_S, check=False)
        if completed.returncode != 0 or not os.path.getsize(proxy_path):
            detail = (completed.stderr or '').strip().splitlines()
            reason = detail[-1] if detail else 'ffmpeg could not read the video'
            raise ValueError(f'Could not make a low-resolution copy: {reason}')
    except (OSError, subprocess.SubprocessError) as exc:
        _remove(proxy_path)
        raise ValueError(f'Could not make a low-resolution copy: {exc}') from exc
    except Exception:
        _remove(proxy_path)
        raise
    return proxy_path


def _source_fps(cap, fallback: float = DEFAULT_TARGET_FPS) -> float:
    """Frame rate reported by the container, with sane guards."""
    import cv2

    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        return fallback
    if not fps or fps != fps or fps <= 0 or fps > 480:  # 0, NaN or nonsense
        return fallback
    return fps


def source_frame_rate(path: str, fallback: float = DEFAULT_TARGET_FPS) -> float:
    """Read the container frame rate without decoding frames."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return fallback
        return _source_fps(cap, fallback)
    finally:
        cap.release()


def _read_frames(path: str, target_fps: float = DEFAULT_TARGET_FPS,
                 max_dimension: int | None = MAX_DIMENSION):
    """Yield RGB uint8 frames, subsampled to about `target_fps`.

    This is a generator so a long film does not keep every frame alive at
    once. The analyser consumes one frame at a time and retains only scalars.
    """
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("OpenCV could not open that file")
    try:
        src_fps = _source_fps(cap, fallback=target_fps)
        step = max(1, int(round(src_fps / float(target_fps))))
        index = 0
        yielded = 0
        while yielded < MAX_FRAMES:
            ok, bgr = cap.read()
            if not ok:
                break
            if index % step == 0:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                if max_dimension and max(rgb.shape[0], rgb.shape[1]) > max_dimension:
                    scale = max_dimension / max(rgb.shape[0], rgb.shape[1])
                    rgb = cv2.resize(
                        rgb,
                        (max(1, int(rgb.shape[1] * scale)),
                         max(1, int(rgb.shape[0] * scale))),
                        interpolation=cv2.INTER_AREA)
                yielded += 1
                yield rgb
            index += 1
    finally:
        cap.release()


def effective_fps(path: str, target_fps: float = DEFAULT_TARGET_FPS) -> float:
    """The rate the sampled frames actually represent, in frames per second."""
    src = source_frame_rate(path, fallback=target_fps)
    step = max(1, int(round(src / float(target_fps))))
    return src / step


def analyze_video_file(path: str, target_fps: float = DEFAULT_TARGET_FPS,
                       cfg: dict | None = None) -> RiskProfile:
    """Analyze a video file on disk and return its RiskProfile.

    OpenCV sees a 480 px ffmpeg proxy when the source is larger. Raises
    ValueError when the file yields fewer than two frames, which is the usual
    sign of an unsupported codec, an audio-only file, or a corrupt download.
    """
    proxy_path = _low_res_proxy(path)
    analysis_path = proxy_path or path
    try:
        fps = effective_fps(analysis_path, target_fps)
        frames = _read_frames(analysis_path, target_fps)
        try:
            return analyze_frames(frames, fps=fps, cfg=cfg)
        except ValueError as exc:
            if 'at least 2 frames' in str(exc):
                raise ValueError(
                    'fewer than 2 frames could be decoded; the screener needs at least 2'
                ) from exc
            raise
    finally:
        if proxy_path:
            _remove(proxy_path)
