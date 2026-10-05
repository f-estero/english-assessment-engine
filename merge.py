"""
merge.py — Unione dei risultati degli spezzoni (modalità Avanzata) e selezione delle voci da mostrare.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, List, Optional, Sequence

from rapidfuzz import fuzz

from chunking import AudioChunk
from schema import AssessmentReport, ChunkAnalysis, SynthesisOutput

DEDUP_WINDOW_SECONDS = 60
DEDUP_MIN_RATIO = 85
_MMSS = re.compile(r"(?:(\d{1,2}):)?(\d{1,3}):(\d{2})")

# tabella → (attributo con il testo da confrontare, prefisso id)
_TABLES = {"grammar_table": ("audio_quote", "gram"),
           "phonetics_table": ("term", "phon"),
           "lexical_table": ("used_term", "lex")}


def parse_mmss(text: Optional[str]) -> Optional[int]:
    m = _MMSS.search(text or "")
    if not m:
        return None
    hours, minutes, seconds = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    if seconds >= 60 or (m.group(1) and minutes >= 60):
        return None
    return hours * 3600 + minutes * 60 + seconds


def fmt_mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def _dedup(entries: list, text_attr: str) -> list:
    """Voci di spezzoni diversi con stesso testo entro DEDUP_WINDOW_SECONDS: resta la più sicura."""
    kept: list = []
    for e, chunk_i in sorted(entries, key=lambda x: parse_mmss(x[0].timestamp_derived)):
        t = parse_mmss(e.timestamp_derived)
        dup = next((k for k in kept if k[1] != chunk_i
                    and abs(parse_mmss(k[0].timestamp_derived) - t) <= DEDUP_WINDOW_SECONDS
                    and fuzz.ratio(getattr(k[0], text_attr).lower(), getattr(e, text_attr).lower()) >= DEDUP_MIN_RATIO),
                   None)
        if dup is None:
            kept.append((e, chunk_i))
        elif e.llm_confidence > dup[0].llm_confidence:
            # tiene il minuto della prima occorrenza (quella del contesto più ampio)
            e.timestamp_derived = dup[0].timestamp_derived
            kept[kept.index(dup)] = (e, chunk_i)
    return [e for e, _ in kept]


def merge_chunks(results: Iterable[tuple[AudioChunk, ChunkAnalysis]]):
    """Restituisce (grammatica, fonetica, lessico, note per spezzone) con minuti assoluti, senza doppioni
    nelle sovrapposizioni e con id riassegnati in ordine di tempo."""
    collected = {name: [] for name in _TABLES}
    notes = []
    for chunk, analysis in sorted(results, key=lambda r: r[0].index):
        length = chunk.end - chunk.start
        notes.append({"chunk": chunk.index, "minutes": f"{fmt_mmss(chunk.start)}-{fmt_mmss(chunk.end)}",
                      "topic": analysis.topic, "prosody": analysis.prosody_notes, "fluency": analysis.fluency_notes})
        for name in _TABLES:
            for e in getattr(analysis, name):
                rel = parse_mmss(e.timestamp_derived)
                if rel is None or rel > length + 5:
                    rel = 0
                e.timestamp_derived = fmt_mmss(chunk.start + rel)
                collected[name].append((e, chunk.index))
    out = []
    for name, (text_attr, prefix) in _TABLES.items():
        merged = _dedup(collected[name], text_attr)
        for i, e in enumerate(merged, start=1):
            e.entry_id = f"{prefix}_{i}"
        out.append(merged)
    return out[0], out[1], out[2], notes


def select_distributed(entries: Sequence, n: int, duration: float, n_buckets: int = 4) -> list:
    """Al massimo n voci, prese a turno da ciascuna parte della lezione (le più sicure prima),
    restituite in ordine di minuto. Se le voci sono ≤ n tornano tutte, nell'ordine originale."""
    if len(entries) <= n:
        return list(entries)
    n_buckets = max(1, n_buckets)
    buckets: List[list] = [[] for _ in range(n_buckets + 1)]   # ultimo = senza minuto
    for e in entries:
        t = parse_mmss(getattr(e, "timestamp_derived", None))
        idx = n_buckets if t is None or duration <= 0 else min(int(t / duration * n_buckets), n_buckets - 1)
        buckets[idx].append(e)
    for b in buckets:
        b.sort(key=lambda e: e.llm_confidence, reverse=True)
    chosen: list = []
    while len(chosen) < n and any(buckets):
        for b in buckets:
            if b and len(chosen) < n:
                chosen.append(b.pop(0))
    big = 10 ** 6
    return sorted(chosen, key=lambda e: parse_mmss(getattr(e, "timestamp_derived", None)) or big)


def build_synthesis_input(grammar, phonetics, lexical, notes, duration: float) -> str:
    """Evidenza compatta per la chiamata di sintesi (solo testo, niente audio)."""
    return json.dumps({
        "duration_minutes": round(duration / 60, 1),
        "grammar": [{"id": e.entry_id, "t": e.timestamp_derived, "quote": e.audio_quote,
                     "correction": e.correction, "type": e.error_type} for e in grammar],
        "phonetics": [{"id": e.entry_id, "t": e.timestamp_derived, "term": e.term,
                       "perceived": e.perceived_ipa, "category": e.category} for e in phonetics],
        "lexical": [{"id": e.entry_id, "t": e.timestamp_derived, "used": e.used_term,
                     "target": e.target_term} for e in lexical],
        "chunk_notes": notes,
    }, ensure_ascii=False)


def assemble_report(grammar, phonetics, lexical, synth: SynthesisOutput, duration: float,
                    n_chunks: int) -> AssessmentReport:
    """Report finale: voci dagli spezzoni + valutazione della sintesi; dati di contesto dal codice."""
    ids = {e.entry_id for e in [*grammar, *phonetics, *lexical]}
    for rule in synth.critical_matrix:
        rule.refs = [r for r in rule.refs if r in ids]
    secs = int(round(duration))
    return AssessmentReport(
        session_date="", teacher_name="—", student_name=None,
        audio_sample_duration=f"{secs // 60}m {secs % 60:02d}s",
        grammar_table=grammar, phonetics_table=phonetics, lexical_table=lexical,
        analysis_mode="avanzata", n_chunks=n_chunks,
        **synth.model_dump(),
    )


PDF_LIMITS = {"grammar": 20, "phonetics": 12, "lexical": 10}
AUDIO_REVIEW_MAX_GRAMMAR = 15


def duration_seconds(text: Optional[str]) -> float:
    """'44m 25s' → 2665; restituisce 0 se il formato non è riconosciuto."""
    m = re.search(r"(\d+)\s*m\D*(\d+)?\s*s?", text or "")
    return int(m.group(1)) * 60 + int(m.group(2) or 0) if m else 0.0


def _buckets(report: AssessmentReport) -> int:
    return max(4, report.n_chunks or 0)


def select_for_display(report: AssessmentReport) -> dict:
    """Voci da mostrare nel PDF: le più sicure, distribuite su tutta la lezione."""
    dur, nb = duration_seconds(report.audio_sample_duration), _buckets(report)
    return {
        "grammar": select_distributed(report.grammar_table, PDF_LIMITS["grammar"], dur, nb),
        "phonetics": select_distributed(report.phonetics_table, PDF_LIMITS["phonetics"], dur, nb),
        "lexical": select_distributed(report.lexical_table, PDF_LIMITS["lexical"], dur, nb),
    }


def select_for_audio_review(report: AssessmentReport) -> list:
    return select_distributed(report.grammar_table, AUDIO_REVIEW_MAX_GRAMMAR,
                              duration_seconds(report.audio_sample_duration), _buckets(report))
