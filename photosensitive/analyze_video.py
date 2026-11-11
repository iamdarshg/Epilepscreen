"""Decode a video file into frames and run the detector core.

OpenCV is imported inside the functions on purpose: the rest of the package is
pure NumPy and can be unit-tested without an OpenCV build.

Sampling, not playback: we do not look at every frame. A 30 fps clip is read
every third frame to give a steady ~10 frames per second for analysis, which
keeps a two-minute film to about 1200 frames. The timestamps the analyser
reports therefore use the *effective* sampling rate (source fps / step), not
the rate we asked for.
"""
import numpy as np

from photosensitive.analyzer import RiskProfile, analyze_frames

DEFAULT_TARGET_FPS = 15.0

# Frames are shrunk before analysis. Detectors work on average brightness and
# stripe structure, both of which survive downscaling, and a 480 px long edge
# is roughly 20x less work than 1080p.
MAX_DIMENSION = 480

# Hard cap so a broken file cannot loop forever inside a web request.
MAX_FRAMES = 20000


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
    """Return RGB uint8 frames, subsampled to about `target_fps`."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("OpenCV could not open that file")
    try:
        src_fps = _source_fps(cap, fallback=target_fps)
        step = max(1, int(round(src_fps / float(target_fps))))
        frames: list[np.ndarray] = []
        index = 0
        while len(frames) < MAX_FRAMES:
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
                frames.append(rgb)
            index += 1
    finally:
        cap.release()
    return frames


def effective_fps(path: str, target_fps: float = DEFAULT_TARGET_FPS) -> float:
    """The rate the sampled frames actually represent, in frames per second."""
    src = source_frame_rate(path, fallback=target_fps)
    step = max(1, int(round(src / float(target_fps))))
    return src / step


def analyze_video_file(path: str, target_fps: float = DEFAULT_TARGET_FPS,
                       cfg: dict | None = None) -> RiskProfile:
    """Analyze a video file on disk and return its RiskProfile.

    Raises ValueError when the file yields fewer than two frames, which is the
    usual sign of an unsupported codec, an audio-only file, or a corrupt
    download.
    """
    frames = _read_frames(path, target_fps)
    if len(frames) < 2:
        raise ValueError(
            f"only {len(frames)} frame(s) could be decoded; the screener needs at least 2")
    return analyze_frames(frames, fps=effective_fps(path, target_fps), cfg=cfg)
