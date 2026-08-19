"""Decode a video file into frames and run the detector core.

The decoding dependency (OpenCV) is isolated here so the rest of the package
stays pure-NumPy and unit-testable."""
import numpy as np

from photosensitive.analyzer import analyze_frames, RiskProfile


def _read_frames(path: str, target_fps: float):
    """Return RGB uint8 frames, subsampled to target_fps."""
    import cv2

    cap = cv2.VideoCapture(path)
    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(src_fps / target_fps)))
        frames: list[np.ndarray] = []
        idx = 0
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if idx % step == 0:
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            idx += 1
    finally:
        cap.release()
    return frames


def analyze_video_file(path: str, target_fps: float = 10.0, cfg: dict | None = None) -> RiskProfile:
    """Analyze a video file on disk and return its RiskProfile.

    Event timestamps are derived from `target_fps` (the analysis sampling rate),
    which the decoder controls via `_read_frames`."""
    frames = _read_frames(path, target_fps)
    if len(frames) < 2:
        raise ValueError("video yielded fewer than 2 frames to analyze")
    return analyze_frames(frames, fps=target_fps, cfg=cfg)
