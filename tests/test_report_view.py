"""Voci mostrate nel PDF e nell'Audio Review: le più importanti, distribuite su tutta la lezione."""
import generate_report
from audio_tutor import build_drill_script
from schema import GrammarEntry


def _many(sample_report, n=30):
    r = sample_report.model_copy(deep=True)
    r.audio_sample_duration = "45m 00s"
    r.analysis_mode, r.n_chunks = "avanzata", 5
    r.grammar_table = [GrammarEntry(entry_id=f"gram_{i}", audio_quote=f"frase sbagliata {i}",
                                    correction=f"frase corretta {i}", error_type="T", l1_interference="-",
                                    rule_and_example="-", llm_confidence=0.5 + i / 100,
                                    timestamp_derived=f"{i * 90 // 60:02d}:{i * 90 % 60:02d}")
                       for i in range(1, n + 1)]
    return r


def _render(report, tmp_path, monkeypatch):
    monkeypatch.setattr(generate_report, "_render_pdf", lambda *a, **k: False)
    generate_report.render_report(report, tmp_path / "Report_x", None, log=lambda m: None)
    return (tmp_path / "Report_x.html").read_text(encoding="utf-8")


def test_pdf_shows_top_20_of_30_distributed(sample_report, tmp_path, monkeypatch):
    html = _render(_many(sample_report), tmp_path, monkeypatch)
    assert "Mostrate 20 di 30 voci" in html and "errori.csv" in html
    import re
    shown = sorted({int(n) for n in re.findall(r"<ins>corretta</ins> (\d+)<", html)})
    assert len(shown) == 20
    assert min(shown) <= 7 and max(shown) >= 24          # presenti inizio e fine lezione
    assert "Avanzata (5 spezzoni)" in html


def test_old_report_renders_without_caption(sample_report, tmp_path, monkeypatch):
    html = _render(sample_report, tmp_path, monkeypatch)
    assert "Mostrate" not in html and "Base" in html


def test_audio_review_max_15_corrections(sample_report):
    script = build_drill_script(_many(sample_report))
    assert sum(1 for s in script if s["type"] == "speech" and s["text"].startswith("Mistake number")) == 15
