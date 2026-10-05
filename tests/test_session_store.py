"""
tests/test_session_store.py — Test per memoria longitudinale e calcolo trend.
"""

from pathlib import Path
from schema import AssessmentReport, GrammarEntry, PhoneticEntry, LexicalEntry
from session_store import (
    upsert_session,
    load_sessions,
    get_session_summary,
)


def _make_dummy_report(date_str: str, student: str = "Mario", error_types=None):
    report = AssessmentReport(
        session_date=date_str,
        student_name=student,
        teacher_name="Tutor",
        audio_sample_duration="30:00",
        main_topic="General conversation",
        session_focus="Fluency",
        cefr_level="B1",
        executive_summary="Summary",
        score_phonetics=6.0,
        desc_phonetics="Good",
        score_grammar=5.5,
        desc_grammar="Fair",
        score_lexicon=6.0,
        desc_lexicon="Good",
        score_fluency=6.0,
        desc_fluency="Smooth",
        score_autonomy=6.5,
        desc_autonomy="High",
        grammar_table=[
            GrammarEntry(
                entry_id=f"G{i+1}",
                audio_quote="He go",
                correction="He goes",
                error_type=etype,
                l1_interference="Omissione -s",
                rule_and_example="Third person -s",
            )
            for i, etype in enumerate(error_types or ["Accordo Soggetto-Verbo"])
        ],
        phonetics_table=[],
        lexical_table=[],
        critical_matrix=[],
        protocol_notes=[],
    )
    return report


def test_upsert_deduplication(tmp_path):
    sessions_file = tmp_path / "sessions.jsonl"
    report = _make_dummy_report("12 Settembre 2026")

    # Primo inserimento
    upsert_session(report, sessions_file, "Lezione 12.09.m4a", "2026-09-12")
    records = load_sessions(sessions_file)
    assert len(records) == 1
    assert records[0].audio_file == "Lezione 12.09.m4a"

    # Secondo inserimento per lo stesso file audio (aggiorna la riga, non duplica)
    report.score_grammar = 7.0
    upsert_session(report, sessions_file, "Lezione 12.09.m4a", "2026-09-12")
    records_after = load_sessions(sessions_file)
    assert len(records_after) == 1
    assert records_after[0].score_grammar == 7.0


def test_date_ordering(tmp_path):
    sessions_file = tmp_path / "sessions.jsonl"

    r1 = _make_dummy_report("12 Settembre 2026")
    r2 = _make_dummy_report("01 Settembre 2026")
    r3 = _make_dummy_report("26 Settembre 2026")

    # Inserimento disordinato
    upsert_session(r1, sessions_file, "Lezione 12.09.m4a", "2026-09-12")
    upsert_session(r3, sessions_file, "Lezione 26.09.m4a", "2026-09-26")
    upsert_session(r2, sessions_file, "Lezione 01.09.m4a", "2026-09-01")

    sessions = load_sessions(sessions_file)
    assert len(sessions) == 3
    # Verifico ordinamento per lesson_date
    assert sessions[0].lesson_date == "2026-09-01"
    assert sessions[1].lesson_date == "2026-09-12"
    assert sessions[2].lesson_date == "2026-09-26"


def test_recurring_errors_only_from_previous(tmp_path):
    sessions_file = tmp_path / "sessions.jsonl"

    # Lezione 1: Errore A
    r1 = _make_dummy_report("01 Settembre 2026", error_types=["Errore A"])
    rec1 = upsert_session(r1, sessions_file, "Lezione 01.09.m4a", "2026-09-01")
    assert rec1.recurring_error_types == []

    # Lezione 2: Errore A + Errore B (Errore A e ricorrente rispetto a Lezione 1)
    r2 = _make_dummy_report("05 Settembre 2026", error_types=["Errore A", "Errore B"])
    rec2 = upsert_session(r2, sessions_file, "Lezione 05.09.m4a", "2026-09-05")
    assert "Errore A" in rec2.recurring_error_types
    assert "Errore B" not in rec2.recurring_error_types

    # Lezione 0 inserita retroattivamente con data 25 Agosto: non deve considerare le lezioni successive
    r0 = _make_dummy_report("25 Agosto 2026", error_types=["Errore B"])
    rec0 = upsert_session(r0, sessions_file, "Lezione 25.08.m4a", "2026-08-25")
    assert rec0.recurring_error_types == []


def test_session_summary_centered_on_current(tmp_path):
    sessions_file = tmp_path / "sessions.jsonl"

    r1 = _make_dummy_report("01 Settembre 2026")
    r1.score_phonetics = 5.0
    r1.score_grammar = 5.0
    r1.score_lexicon = 5.0
    r1.score_fluency = 5.0
    r1.score_autonomy = 5.0

    r2 = _make_dummy_report("05 Settembre 2026")
    r2.score_phonetics = 5.5
    r2.score_grammar = 5.5
    r2.score_lexicon = 5.5
    r2.score_fluency = 5.5
    r2.score_autonomy = 5.5

    r3 = _make_dummy_report("10 Settembre 2026")
    r3.score_phonetics = 6.0
    r3.score_grammar = 6.0
    r3.score_lexicon = 6.0
    r3.score_fluency = 6.0
    r3.score_autonomy = 6.0

    upsert_session(r1, sessions_file, "L1.m4a", "2026-09-01")
    upsert_session(r2, sessions_file, "L2.m4a", "2026-09-05")
    upsert_session(r3, sessions_file, "L3.m4a", "2026-09-10")

    # Sommario centrato su L2 (deve avere delta contro L1 e non vedere L3 come corrente)
    summary_l2 = get_session_summary(sessions_file, current_audio_file="L2.m4a")
    assert summary_l2 is not None
    assert summary_l2["delta"]["weighted"] == 0.5  # 5.5 - 5.0
    # Lo storico si ferma a L2
    assert summary_l2["scores_history"][-1]["date"] == "05 Settembre 2026"
