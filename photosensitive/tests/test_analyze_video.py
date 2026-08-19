import numpy as np

from photosensitive.analyze_video import analyze_video_file


def test_analyze_video_file_accepts_frame_array(tmp_path, monkeypatch):
    """Monkeypatch the cv2 reader so no real media file is needed."""

    def fake_frames(path, target_fps):
        return [np.full((8, 8, 3), 120, dtype=np.uint8) for _ in range(5)]

    monkeypatch.setattr("photosensitive.analyze_video._read_frames", fake_frames)
    profile = analyze_video_file(str(tmp_path / "x.mp4"))
    assert profile.is_safe is True
    assert profile.events == []
