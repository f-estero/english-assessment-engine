import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema import (  # noqa: E402
    AssessmentReport, GrammarEntry, PhoneticEntry, LexicalEntry,
    CriticalRule, ProtocolNote, ProsodyAndToneAnalysis,
)


@pytest.fixture
def sample_report() -> AssessmentReport:
    """Report inventato: nessun dato reale."""
    return AssessmentReport(
        session_date="01 Gennaio 2000",
        cefr_level="B1",
        teacher_name="Docente Test",
        student_name="Studente Test",
        audio_sample_duration="10m 00s",
        main_topic="Vacanze",
        session_focus="Present simple",
        executive_summary="Sintesi di prova.",
        prosody_and_tone=ProsodyAndToneAnalysis(
            intonation_pattern="-", speech_rhythm="-", tone_confidence="-", pause_profile="-"),
        score_phonetics=6.0, desc_phonetics="-",
        score_grammar=5.5, desc_grammar="-",
        score_lexicon=6.0, desc_lexicon="-",
        score_fluency=5.0, desc_fluency="-",
        score_autonomy=6.5, desc_autonomy="-",
        grammar_table=[
            GrammarEntry(entry_id="gram_1", audio_quote="she go to work", correction="she goes to work",
                         error_type="Terza persona", l1_interference="-", rule_and_example="-",
                         llm_confidence=0.9),
            GrammarEntry(entry_id="gram_2", audio_quote="I go in Spain", correction="I went to Spain",
                         error_type="Preposizioni", l1_interference="-", rule_and_example="-",
                         llm_confidence=0.8),
        ],
        phonetics_table=[
            PhoneticEntry(entry_id="phon_1", term="think", perceived_ipa="tink", category="Altro",
                          practical_drill="-", llm_confidence=0.9),
        ],
        lexical_table=[
            LexicalEntry(entry_id="lex_1", used_term="actually", calque_or_error="attualmente",
                         target_term="currently", language_register="Neutral", context_note="-"),
        ],
        critical_matrix=[CriticalRule(priority="ALTA", title="Terza persona", description="-")],
        protocol_notes=[ProtocolNote(category="Azione Correttiva", title="Drill", details="-")],
    )


@pytest.fixture
def tmp_appdata(monkeypatch, tmp_path) -> Path:
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata


@pytest.fixture
def fake_keyring(monkeypatch) -> dict:
    import keyring
    store: dict = {}
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))
    monkeypatch.setattr(keyring, "set_password", lambda s, u, p: store.__setitem__((s, u), p))

    def _delete(s, u):
        store.pop((s, u), None)
    monkeypatch.setattr(keyring, "delete_password", _delete)
    return store


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
