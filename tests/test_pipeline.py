"""
tests/test_pipeline.py — Test per la pipeline di elaborazione audio (senza chiamate di rete).
"""

from pathlib import Path
import pytest
from schema import AssessmentReport, GrammarEntry
import generate_report


def _dummy_report_factory():
    return AssessmentReport(
        session_date="Data placeholder",
        student_name="Placeholder",
        teacher_name="Tutor",
        audio_sample_duration="30:00",
        main_topic="Topic",
        session_focus="Focus",
        cefr_level="B1",
        executive_summary="Summary",
        score_phonetics=6.0,
        desc_phonetics="Desc",
        score_grammar=6.0,
        desc_grammar="Desc",
        score_lexicon=6.0,
        desc_lexicon="Desc",
        score_fluency=6.0,
        desc_fluency="Desc",
        score_autonomy=6.0,
        desc_autonomy="Desc",
        grammar_table=[
            GrammarEntry(
                entry_id="G1",
                audio_quote="Quote",
                correction="Correction",
                error_type="Grammar Error",
                l1_interference="L1",
                rule_and_example="Rule",
            )
        ],
        phonetics_table=[],
        lexical_table=[],
        critical_matrix=[],
        protocol_notes=[],
    )


def test_process_single_audio_pipeline(tmp_path, monkeypatch):
    out_dir = tmp_path / "Report"
    out_dir.mkdir()

    # Creiamo un file audio fittizio
    audio_file = tmp_path / "Lezione inglese 12.09.m4a"
    audio_file.write_text("dummy audio data")

    analysis_called_count = 0

    def mock_analyze_audio(audio_path, api_key, model, student_name, log=print, **kwargs):
        nonlocal analysis_called_count
        analysis_called_count += 1
        return _dummy_report_factory()

    monkeypatch.setattr(generate_report, "analyze_audio", mock_analyze_audio)

    # Disattivazione subprocess per PDF per velocizzare il test
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)

    # 1. Prima esecuzione
    lesson_dir_str = generate_report.process_single_audio(
        audio_path=audio_file,
        student_name="Mario",
        model_name="gemini-3.5-flash",
        output_dir=out_dir,
        api_key="dummy_key",
        log=lambda msg: None,
    )

    lesson_dir = Path(lesson_dir_str)
    assert lesson_dir.exists()
    assert analysis_called_count == 1

    # Verifica struttura: tmp/<Mese AA>/<data>_<chiave>/
    assert lesson_dir.parent.name == "Settembre 26"
    assert "2026-09-12_Mario_Lezione_inglese_12_09" in lesson_dir.name

    # Verifica file generati nella cartella lezione
    assert (lesson_dir / "report.json").exists()
    assert (lesson_dir / "errori.csv").exists()
    assert (lesson_dir / f"Report_{lesson_dir.name}.html").exists()
    assert (lesson_dir / audio_file.name).exists()

    # Verifica che sessions.jsonl sia stato creato in output_dir
    assert (out_dir / "sessions.jsonl").exists()

    # Verifica session_date derivata dal nome file (12 Settembre 2026)
    loaded_report = generate_report.load_report(lesson_dir / "report.json")
    assert loaded_report.session_date == "12 Settembre 2026"
    assert loaded_report.student_name == "Mario"

    # 2. Seconda esecuzione: deve riutilizzare report.json senza richiamare analyze_audio!
    lesson_dir_2 = generate_report.process_single_audio(
        audio_path=audio_file,
        student_name="Mario",
        model_name="gemini-3.5-flash",
        output_dir=out_dir,
        api_key="dummy_key",
        log=lambda msg: None,
    )
    assert lesson_dir_2 == lesson_dir_str
    assert analysis_called_count == 1  # NON deve essere incrementato
