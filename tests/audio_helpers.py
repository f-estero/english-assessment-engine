"""Generazione di file audio/video sintetici per i test (nessun dato reale)."""
from fractions import Fraction
from pathlib import Path

import av
import numpy as np


def make_mp4(path: Path, with_video: bool, seconds: float = 2.0) -> Path:
    """MP4 sintetico: AAC mono 16 kHz con tono a 440 Hz, opzionalmente con traccia video."""
    sr = 16000
    with av.open(str(path), "w", format="mp4") as c:
        a = c.add_stream("aac", rate=sr)
        a.layout = "mono"
        v = None
        if with_video:
            v = c.add_stream("mpeg4", rate=10)
            v.width, v.height, v.pix_fmt = 64, 64, "yuv420p"
        n = int(sr * seconds)
        tone = (np.sin(np.arange(n) * 2 * np.pi * 440 / sr) * 8000).astype(np.int16)
        for i in range(0, n, 1024):
            fr = av.AudioFrame.from_ndarray(tone[i:i + 1024].reshape(1, -1), format="s16", layout="mono")
            fr.sample_rate = sr
            fr.pts, fr.time_base = i, Fraction(1, sr)
            for p in a.encode(fr):
                c.mux(p)
        for p in a.encode(None):
            c.mux(p)
        if v:
            for k in range(int(seconds * 10)):
                img = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), np.uint8), format="rgb24")
                img.pts = k
                for p in v.encode(img):
                    c.mux(p)
            for p in v.encode(None):
                c.mux(p)
    return path
