"""python manage.py make_samples [--out samples]

Write a handful of short synthetic clips with OpenCV so the project can be
demonstrated (and tested) without hunting for footage. Each clip targets one
detector:

    calm.mp4        steady grey ramp      -> should screen clean
    strobe.mp4      hard on/off flashes   -> flicker
    redflash.mp4    red frames in black   -> red flash
    stripes.mp4     stationary bars       -> high-contrast pattern
    colour.mp4      blue/green sweeps     -> colour transition

They are generated, not downloaded, so they are safe to ship with the project.

OpenCV writes MPEG-4 Part 2, which OpenCV reads happily but browsers do not.
When `ffmpeg` is on PATH the clips are re-encoded to H.264 so the same files
play in the player page as well as through the screener.
"""
import os
import shutil
import subprocess

import numpy as np
from django.core.management.base import BaseCommand


class Clip:
    def __init__(self, name, frames, fps=15):
        self.name = name
        self.frames = frames
        self.fps = fps


def _solid(height, width, rgb):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = rgb
    return frame


def _stripes(height, width, bar=16, a=240, b=10):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(0, width, bar * 2):
        frame[:, x:x + bar, :] = a
        frame[:, x + bar:x + 2 * bar, :] = b
    return frame


def build_clips(width=320, height=240, fps=15):
    clips = []

    calm = [_solid(height, width, (40 + i, 40 + i, 40 + i)) for i in range(40)]
    clips.append(Clip('calm', calm, fps))

    strobe = [_solid(height, width, (255, 255, 255) if i % 2 else (0, 0, 0))
              for i in range(30)]
    clips.append(Clip('strobe', strobe, fps))

    redflash = []
    for i in range(40):
        if 12 <= i < 16 or 26 <= i < 30:
            redflash.append(_solid(height, width, (230, 12, 12)))
        else:
            redflash.append(_solid(height, width, (18, 18, 22)))
    clips.append(Clip('redflash', redflash, fps))

    clips.append(Clip('stripes', [_stripes(height, width) for _ in range(30)], fps))

    colour = []
    for i in range(40):
        phase = (i // 10) % 3
        colours = [(10, 20, 220), (20, 210, 40), (220, 40, 10)]
        colour.append(_solid(height, width, colours[phase]))
    clips.append(Clip('colour', colour, fps))

    return clips


class Command(BaseCommand):
    help = 'Write synthetic demo clips (calm/strobe/redflash/stripes/colour) with OpenCV.'

    def add_arguments(self, parser):
        parser.add_argument('--out', default='samples', help='output directory')
        parser.add_argument('--width', type=int, default=320)
        parser.add_argument('--height', type=int, default=240)
        parser.add_argument('--no-transcode', action='store_true',
                            help='keep the raw mp4v files even if ffmpeg is available')

    def handle(self, *args, **options):
        import cv2

        out_dir = options['out']
        os.makedirs(out_dir, exist_ok=True)
        ffmpeg = None if options['no_transcode'] else shutil.which('ffmpeg')
        written = []
        for clip in build_clips(options['width'], options['height']):
            path = os.path.join(out_dir, f'{clip.name}.mp4')
            writer = cv2.VideoWriter(
                path, cv2.VideoWriter_fourcc(*'mp4v'), clip.fps,
                (clip.frames[0].shape[1], clip.frames[0].shape[0]))
            if not writer.isOpened():
                self.stderr.write('This OpenCV build cannot write mp4v.')
                return
            try:
                for frame in clip.frames:
                    writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            finally:
                writer.release()
            if ffmpeg:
                self._to_h264(ffmpeg, path)
            written.append(path)
            self.stdout.write(f'{path}  ({len(clip.frames)} frames @ {clip.fps} fps)')

        if not ffmpeg:
            self.stdout.write(self.style.WARNING(
                'ffmpeg was not found, so the clips are MPEG-4 Part 2. OpenCV can '
                'screen them, but browsers cannot play them.'))
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {len(written)} clips to {out_dir}/. Upload one to try the screener.'))

    def _to_h264(self, ffmpeg, path):
        """Re-encode in place so the browser player can decode the clip."""
        temp = f'{path}.h264.mp4'
        result = subprocess.run(
            [ffmpeg, '-y', '-loglevel', 'error', '-i', path,
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast',
             '-movflags', '+faststart', temp],
            capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(temp):
            os.replace(temp, path)
        else:
            if os.path.exists(temp):
                os.unlink(temp)
            self.stderr.write(f'ffmpeg could not re-encode {path}: {result.stderr.strip()[:200]}')