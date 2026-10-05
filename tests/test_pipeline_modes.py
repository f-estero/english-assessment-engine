"""Pipeline Base / Avanzata con un Gemini finto (nessuna rete)."""
import itertools
from pathlib import Path

import pytest

import chunking
import generate_report
from schema import (AssessmentReport, ChunkAnalysis, GrammarEntry, ProsodyAndToneAnalysis,
                    SynthesisOutput)
from tests.audio_helpers import make_mp4


class FakeGemini:
    def __init__(self, sample_report, fail_on_chunk=None):
        self.sample = sample_report
        self.fail_on_chunk = fail_on_chunk
        self.calls = []          # nome dello schema richiesto
        self.uploads = 0
        self.counter = itertools.count(1)
        outer = self

        class _F:
            def __init__(self):
                self.name, self.state = f"files/{next(outer.counter)}", type("S", (), {"name": "ACTIVE"})()

        class Files:
            def upload(self, file, config=None):
                outer.uploads += 1
                assert config is not None and config.mime_type == "audio/mp4"
                return _F()

            def get(self, name):
                raise AssertionError("non dovrebbe servire")

            def delete(self, name):
                pass

        class Models:
            def generate_content(self, model, contents, config):
                schema = config.response_schema
                outer.calls.append(schema.__name__)
                if schema is ChunkAnalysis:
                    n = sum(1 for c in outer.calls if c == "ChunkAnalysis")
                    if outer.fail_on_chunk == n:
                        raise Exception("400 INVALID_ARGUMENT")
                    return _resp(ChunkAnalysis(
                        grammar_table=[GrammarEntry(entry_id="x", audio_quote=["she go to work", "I has two brothers", "they was very happy"][(n - 1) % 3],
                                                    correction="ok", error_type="T", l1_interference="-",
                                                    rule_and_example="-", timestamp_derived="00:03")],
                        prosody_notes="p", fluency_notes="f"))
                if schema is SynthesisOutput:
                    return _resp(SynthesisOutput(**{k: v for k, v in outer.sample.model_dump().items()
                                                    if k in SynthesisOutput.model_fields}))
                return _resp(outer.sample)

        self.files, self.models = Files(), Models()


def _resp(model):
    return type("R", (), {"text": model.model_dump_json()})()


@pytest.fixture
def audio25(tmp_path, monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_SECONDS", 10)
    monkeypatch.setattr(chunking, "OVERLAP_SECONDS", 2)
    monkeypatch.setattr(chunking, "MIN_LAST_SECONDS", 4)
    return make_mp4(tmp_path / "Lezione inglese 12.09.mp4", with_video=True, seconds=25)


def _install(monkeypatch, fake):
    monkeypatch.setattr(generate_report.genai, "Client", lambda api_key: fake)


def test_advanced_mode_chunks_then_synthesis(audio25, monkeypatch, sample_report):
    fake = FakeGemini(sample_report)
    _install(monkeypatch, fake)
    steps = []
    r = generate_report.analyze_audio(audio25, "k", "m", "Stud", log=lambda m: None,
                                      mode="avanzata", progress=steps.append)
    assert sorted(fake.calls) == ["ChunkAnalysis"] * 3 + ["SynthesisOutput"]
    assert fake.calls[-1] == "SynthesisOutput" and fake.uploads == 3
    assert (r.analysis_mode, r.n_chunks, r.student_name) == ("avanzata", 3, "Stud")
    assert [g.timestamp_derived for g in r.grammar_table] == ["00:03", "00:11", "00:19"]
    assert r.audio_sample_duration == "0m 25s"
    assert "Sintesi" in steps and any(s.startswith("Spezzone") for s in steps)


def test_base_mode_single_call(audio25, monkeypatch, sample_report):
    fake = FakeGemini(sample_report)
    _install(monkeypatch, fake)
    r = generate_report.analyze_audio(audio25, "k", "m", "Stud", log=lambda m: None, mode="base")
    assert fake.calls == ["AssessmentReport"] and fake.uploads == 1
    assert (r.analysis_mode, r.n_chunks, r.audio_sample_duration) == ("base", None, "0m 25s")


def test_failed_chunk_fails_lesson_without_report(audio25, monkeypatch, sample_report, tmp_path):
    _install(monkeypatch, FakeGemini(sample_report, fail_on_chunk=2))
    out = tmp_path / "out"
    with pytest.raises(Exception, match="INVALID_ARGUMENT"):
        generate_report.process_single_audio(audio25, "Stud", "m", out, api_key="k",
                                             log=lambda m: None, mode="avanzata")
    assert not list(out.rglob("report.json"))


def test_force_reanalyzes_existing_report(audio25, monkeypatch, sample_report, tmp_path):
    fake = FakeGemini(sample_report)
    _install(monkeypatch, fake)
    monkeypatch.setattr(generate_report, "_render_pdf", lambda *a, **k: False)
    out = tmp_path / "out"
    kw = dict(api_key="k", log=lambda m: None, mode="base")
    generate_report.process_single_audio(audio25, "Stud", "m", out, **kw)
    generate_report.process_single_audio(audio25, "Stud", "m", out, **kw)
    assert len(fake.calls) == 1
    d = generate_report.process_single_audio(audio25, "Stud", "m", out, force=True, **kw)
    assert len(fake.calls) == 2
    assert AssessmentReport.model_validate_json((Path(d) / "report.json").read_text(encoding="utf-8")).analysis_mode == "base"
