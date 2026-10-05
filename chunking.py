"""
chunking.py — Decodifica locale dell'audio e preparazione degli spezzoni da inviare a Gemini.

Qualsiasi formato leggibile da PyAV (m4a, mp3, wav, mp4 anche con video...) viene decodificato
leggendo solo la traccia audio, convertito in mono 16 kHz e ricodificato in AAC in memoria.
Il file sorgente non viene mai modificato.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

SAMPLE_RATE = 16000          # Gemini ricampiona comunque l'audio a 16 kHz mono
BIT_RATE = 64000
CHUNK_SECONDS = 600
OVERLAP_SECONDS = 30
MIN_LAST_SECONDS = 240


@dataclass
class AudioChunk:
    index: int        # 1-based
    n_chunks: int
    start: float      # secondi dall'inizio della lezione
    end: float
    data: bytes       # m4a (AAC mono)
    mime: str = "audio/mp4"


def chunk_bounds(duration: float, chunk: int = CHUNK_SECONDS, overlap: int = OVERLAP_SECONDS,
                 min_last: int = MIN_LAST_SECONDS) -> list[tuple[float, float]]:
    """Finestre [inizio, fine) con sovrapposizione; una coda più corta di min_last viene fusa con la precedente."""
    if duration <= chunk:
        return [(0, duration)]
    bounds: list[tuple[float, float]] = []
    start = 0
    while start < duration:
        bounds.append((start, min(start + chunk, duration)))
        if start + chunk >= duration:
            break
        start += chunk - overlap
    if len(bounds) > 1 and bounds[-1][1] - bounds[-1][0] < min_last:
        bounds[-2:] = [(bounds[-2][0], bounds[-1][1])]
    return bounds


def load_audio(path: Path) -> tuple[np.ndarray, float]:
    """Decodifica la prima traccia audio in PCM int16 mono a SAMPLE_RATE. Restituisce (pcm, durata in s)."""
    parts = []
    with av.open(str(path)) as c:
        if not c.streams.audio:
            raise ValueError(f"Il file {Path(path).name} non contiene una traccia audio.")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in c.decode(c.streams.audio[0]):
            for r in resampler.resample(frame):
                parts.append(r.to_ndarray().reshape(-1))
        for r in resampler.resample(None):
            parts.append(r.to_ndarray().reshape(-1))
    pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
    return pcm, len(pcm) / SAMPLE_RATE


def encode_aac(pcm: np.ndarray) -> bytes:
    """Codifica PCM int16 mono in un contenitore m4a (AAC) in memoria."""
    buf = io.BytesIO()
    with av.open(buf, "w", format="ipod") as out:
        stream = out.add_stream("aac", rate=SAMPLE_RATE)
        stream.layout = "mono"
        stream.bit_rate = BIT_RATE
        for i in range(0, len(pcm), 1024):
            frame = av.AudioFrame.from_ndarray(pcm[i:i + 1024].reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = SAMPLE_RATE
            frame.pts, frame.time_base = i, Fraction(1, SAMPLE_RATE)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def make_chunks(path: Path, chunk: int = CHUNK_SECONDS, overlap: int = OVERLAP_SECONDS,
                min_last: int = MIN_LAST_SECONDS) -> list[AudioChunk]:
    """Divide l'audio in spezzoni sovrapposti già codificati, pronti per l'upload."""
    pcm, duration = load_audio(path)
    bounds = chunk_bounds(duration, chunk, overlap, min_last)
    return [
        AudioChunk(i, len(bounds), s, e, encode_aac(pcm[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)]))
        for i, (s, e) in enumerate(bounds, start=1)
    ]


def whole_audio(path: Path) -> AudioChunk:
    """L'intera registrazione come unico spezzone (modalità Base)."""
    pcm, duration = load_audio(path)
    return AudioChunk(1, 1, 0, duration, encode_aac(pcm))
