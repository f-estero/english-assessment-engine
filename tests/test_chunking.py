import hashlib
import io

import av
import pytest

import chunking
from tests.audio_helpers import make_mp4


def _duration(data: bytes) -> float:
    with av.open(io.BytesIO(data)) as c:
        assert len(c.streams.video) == 0 and len(c.streams.audio) == 1
        return sum(f.samples for f in c.decode(audio=0)) / c.streams.audio[0].rate


def test_chunk_bounds():
    b = chunking.chunk_bounds(2664)
    assert len(b) == 5 and b[0] == (0, 600) and b[1][0] == 570 and b[-1] == (2280, 2664)
    assert chunking.chunk_bounds(500) == [(0, 500)]
    assert chunking.chunk_bounds(1300) == [(0, 600), (570, 1300)]   # coda 1140-1300 (<240 s) fusa


def test_make_chunks_from_video_mp4(tmp_path):
    src = make_mp4(tmp_path / "Lezione 16.09.mp4", with_video=True, seconds=25)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    chunks = chunking.make_chunks(src, chunk=10, overlap=2, min_last=4)
    assert [c.index for c in chunks] == [1, 2, 3] and all(c.n_chunks == 3 for c in chunks)
    assert [c.start for c in chunks] == [0, 8, 16]
    assert [c.end for c in chunks] == pytest.approx([10, 18, 25], abs=0.1)
    for c in chunks:
        assert c.mime == "audio/mp4"
        assert _duration(c.data) == pytest.approx(c.end - c.start, abs=0.2)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == sha


def test_whole_audio_single_chunk(tmp_path):
    src = make_mp4(tmp_path / "breve.mp4", with_video=False, seconds=3)
    ch = chunking.whole_audio(src)
    assert (ch.index, ch.n_chunks, ch.start) == (1, 1, 0)
    assert ch.end == pytest.approx(3, abs=0.1)
    assert _duration(ch.data) == pytest.approx(3, abs=0.2)
