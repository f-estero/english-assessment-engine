"""
tests/test_template.py — Test per rendering template HTML, autoescape e pulizia termini.
"""

from jinja2 import Environment, FileSystemLoader, select_autoescape
from app_config import resource_path
from schema import AssessmentReport, GrammarEntry


def test_template_terms_and_fonts():
    template_file = resource_path("templates", "report_template.html")
    content = template_file.read_text(encoding="utf-8")
    content_lower = content.lower()

    # Verifica rimozione Google Fonts
    assert "fonts.googleapis" not in content_lower
    assert "fonts.gstatic" not in content_lower

    # Verifica rimozione claim certificati e denominazioni ufficiali
    assert "official" not in content_lower
    assert "cambridge esol" not in content_lower
    assert "clinica" not in content_lower
    assert "clinico" not in content_lower


def test_template_autoescape():
    templates_dir = resource_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report_template.html")

    # Inietta testo con tag HTML potenzialmente pericolosi o non sanitizzati
    malicious_text = "<script>alert('xss')</script><b>injection</b>"
    report = AssessmentReport(
        session_date="12 Settembre 2026",
        student_name=malicious_text,
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
                audio_quote=malicious_text,
                correction="Safe",
                error_type="Grammar",
                l1_interference="L1",
                rule_and_example="Rule",
            )
        ],
        phonetics_table=[],
        lexical_table=[],
        critical_matrix=[],
        protocol_notes=[],
    )

    rendered = template.render(data=report, session_summary=None)

    # I tag devono essere escapati in entita HTML
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&lt;b&gt;injection&lt;/b&gt;" in rendered
