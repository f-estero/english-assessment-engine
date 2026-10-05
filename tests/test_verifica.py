"""Test aggiuntivi della verifica finale (casi del piano non coperti)."""

import json
import os
from pathlib import Path

import pytest

import app_config
import generate_report
import session_store

APP_DIR = Path(generate_report.__file__).resolve().parent


def _snapshot(root: Path) -> dict:
    skip = {"__pycache__", ".pytest_cache", "build", "dist"}
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip]
        for f in fns:
            p = Path(dp) / f
            out[str(p)] = p.stat().st_mtime
    return out


@pytest.fixture
def lesson(tmp_path, monkeypatch, sample_report):
    audio = tmp_path / "in" / "Lezione inglese 12.09.m4a"
    audio.parent.mkdir()
    audio.write_bytes(b"fake")
    os.utime(audio, (1790000000, 1790000000))  # settembre 2026
    calls = []

    def fake_analyze(**kw):
        calls.append(kw)
        return sample_report.model_copy(deep=True)

    monkeypatch.setattr(generate_report, "analyze_audio", fake_analyze)
    orig_render = generate_report.render_report
    monkeypatch.setattr(generate_report.os.path, "exists",
                        lambda p, _e=os.path.exists: False if "msedge" in str(p) else _e(p))
    monkeypatch.setattr(generate_report.shutil, "which", lambda name: None)
    return audio, tmp_path / "out", calls, orig_render


def test_nothing_written_in_app_dir_and_reuse(lesson):
    audio, out, calls, _ = lesson
    before = _snapshot(APP_DIR)
    d1 = generate_report.process_single_audio(audio, "Stud", "m", out, api_key="k", log=lambda m: None)
    d2 = generate_report.process_single_audio(audio, "Stud", "m", out, api_key="k", log=lambda m: None)
    assert _snapshot(APP_DIR) == before
    assert d1 == d2 and len(calls) == 1          # secondo giro: riuso senza analisi
    assert Path(d1).parent.name == "Settembre 26"
    rep = json.loads((Path(d1) / "report.json").read_text(encoding="utf-8"))
    assert rep["session_date"] == "12 Settembre 2026"
    assert len((out / "sessions.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_missing_key_raises_clear_error(lesson, monkeypatch):
    audio, out, _, _ = lesson
    monkeypatch.setattr(generate_report, "get_api_key", lambda: (None, ""))
    with pytest.raises(ValueError, match="Chiave API"):
        generate_report.process_single_audio(audio, "Stud", "m", out, log=lambda m: None)


def test_render_from_json_does_not_touch_sessions(lesson):
    audio, out, _, _ = lesson
    d = Path(generate_report.process_single_audio(audio, "Stud", "m", out, api_key="k", log=lambda m: None))
    (out / "sessions.jsonl").unlink()
    generate_report.render_from_json(d / "report.json", log=lambda m: None)
    assert not (out / "sessions.jsonl").exists()


def test_stale_pdf_not_reported_as_new(lesson, tmp_path, sample_report):
    """Se il PDF non viene rigenerato, quello vecchio non deve restare spacciato per aggiornato."""
    _, _, _, orig_render = lesson
    base = tmp_path / "Report_x"
    base.with_suffix(".pdf").write_bytes(b"%PDF-vecchio")
    logs = []
    orig_render(sample_report, base, None, log=logs.append)
    assert not base.with_suffix(".pdf").exists()
    assert any("PDF non generato" in m for m in logs)


class _Err(Exception):
    pass


class _FakeModels:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _FakeClient:
    def __init__(self, script):
        self.models = _FakeModels(script)


def test_retry_fallback_and_invalid_key(monkeypatch):
    monkeypatch.setattr(generate_report.time, "sleep", lambda s: None)
    logs = []
    c = _FakeClient([_Err("404 NOT_FOUND"), "ok"])
    assert generate_report.call_gemini_with_retry(c, app_config.MODELS[0], [], "", log=logs.append) == "ok"
    assert c.models.calls == app_config.MODELS[:2]
    assert logs, "i messaggi devono passare dal log"

    c = _FakeClient([_Err("503 UNAVAILABLE"), "ok"])
    assert generate_report.call_gemini_with_retry(c, app_config.MODELS[0], [], "", log=logs.append) == "ok"

    c = _FakeClient([_Err("400 API_KEY_INVALID")])
    with pytest.raises(ValueError, match="Chiave API Gemini non valida"):
        generate_report.call_gemini_with_retry(c, app_config.MODELS[0], [], "", log=logs.append)


def test_legacy_session_record_without_lesson_date(tmp_path, sample_report):
    f = tmp_path / "sessions.jsonl"
    legacy = {"session_id": "s", "date": "x", "timestamp_iso": "2026-09-01T10:00:00",
              "audio_file": "vecchia.m4a", "student_name": "S", "cefr_level": "B1"}
    f.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    assert len(session_store.load_sessions(f)) == 1
    session_store.upsert_session(sample_report, f, "nuova 12.09.m4a", "2026-09-12")
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    assert [r["audio_file"] for r in rows] == ["vecchia.m4a", "nuova 12.09.m4a"]


def test_rejected_key_on_upload_gives_clear_message(tmp_path, monkeypatch):
    class _Files:
        def upload(self, file, config=None):
            raise Exception("401 UNAUTHENTICATED. Request had invalid authentication credentials.")

        def delete(self, name):
            pass

    class _Client:
        def __init__(self, api_key):
            self.files = _Files()

    monkeypatch.setattr(generate_report.genai, "Client", _Client)
    from tests.audio_helpers import make_mp4
    audio = make_mp4(tmp_path / "lezione.mp4", with_video=False)
    with pytest.raises(ValueError, match="Chiave API Gemini non valida"):
        generate_report.analyze_audio(audio, "k", "m", "Stud", log=lambda m: None)
    c = _FakeClient([_Err("401 UNAUTHENTICATED")])
    with pytest.raises(ValueError, match="Chiave API Gemini non valida"):
        generate_report.call_gemini_with_retry(c, app_config.MODELS[0], [], "", log=lambda m: None)
