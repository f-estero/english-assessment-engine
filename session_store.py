"""
session_store.py — Memoria Longitudinale e tracciamento trend.

Salva e legge i record delle sessioni in sessions.jsonl.
Supporta:
- Aggiornamento idempotente (upsert basato sul nome file audio)
- Ordinamento rigoroso per data della lezione (lesson_date ISO) e timestamp
- Calcolo degli errori ricorrenti solo contro le lezioni cronologicamente precedenti
- Generazione del sommario per il report HTML centrato sulla lezione corrente
- Scrittura atomica
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from schema import AssessmentReport


class SessionRecord(BaseModel):
    """Record per una sessione, ottimizzato per tracciamento trend."""
    session_id: str = Field(description="ID univoco basato su timestamp")
    lesson_date: str = Field(default="", description="Data ISO della lezione (YYYY-MM-DD)")
    date: str = Field(description="Data leggibile della sessione")
    timestamp_iso: str = Field(description="Timestamp ISO 8601 del salvataggio")
    audio_file: str = Field(description="Nome del file audio analizzato")
    student_name: str = Field(default="Studente")
    cefr_level: str = Field(description="Livello CEFR stimato")

    # Punteggi (5 dimensioni)
    score_phonetics: float = 0.0
    score_grammar: float = 0.0
    score_lexicon: float = 0.0
    score_fluency: float = 0.0
    score_autonomy: float = 0.0
    score_weighted: float = Field(default=0.0, description="Media ponderata (20/25/20/20/15)")

    # Conteggi errori per tipo (per tracciare trend)
    error_counts: Dict[str, int] = Field(default_factory=dict, description="Conteggio errori per tipo")

    # Errori ricorrenti rispetto alle lezioni precedenti
    recurring_error_types: List[str] = Field(default_factory=list, description="Tipi di errore ricorrenti")

    # Statistiche validazione
    validation_proposed: int = 0
    validation_validated: int = 0
    validation_discarded: int = 0
    transcript_source: str = "llm"


def _compute_weighted_score(report: AssessmentReport) -> float:
    """Calcola la media ponderata dei punteggi (pesi: 20/25/20/20/15)."""
    return round(
        report.score_phonetics * 0.20 +
        report.score_grammar * 0.25 +
        report.score_lexicon * 0.20 +
        report.score_fluency * 0.20 +
        report.score_autonomy * 0.15,
        2
    )


def _count_errors_by_type(report: AssessmentReport) -> Dict[str, int]:
    """Conta gli errori per tipo dalla grammar_table, phonetics_table e lexical_table."""
    counts: Dict[str, int] = {}
    for entry in report.grammar_table:
        etype = entry.error_type.strip()
        counts[etype] = counts.get(etype, 0) + 1
    for entry in report.phonetics_table:
        cat = f"Fonetica: {entry.category.strip()}"
        counts[cat] = counts.get(cat, 0) + 1
    if report.lexical_table:
        counts["Calco Lessicale"] = len(report.lexical_table)
    return counts


def _find_recurring_errors(
    current_counts: Dict[str, int],
    previous_sessions: List[SessionRecord]
) -> List[str]:
    """Trova i tipi di errore presenti sia nella sessione corrente che nelle sessioni precedenti."""
    if not previous_sessions:
        return []

    all_previous_types: set = set()
    for session in previous_sessions:
        all_previous_types.update(session.error_counts.keys())

    recurring = [
        etype for etype in current_counts.keys()
        if etype in all_previous_types
    ]
    return sorted(recurring)


def _generate_session_id() -> str:
    """Genera un session ID univoco basato sul timestamp corrente."""
    now = datetime.now()
    return f"session_{now.strftime('%Y%m%d_%H%M%S')}"


def load_sessions(sessions_file: Path | str) -> List[SessionRecord]:
    """Carica tutte le sessioni dal file JSONL, ignorando righe vuote o corrotte."""
    sessions_path = Path(sessions_file)
    sessions: List[SessionRecord] = []
    if not sessions_path.is_file():
        return sessions

    try:
        with open(sessions_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    sessions.append(SessionRecord.model_validate(data))
                except Exception:
                    continue
    except OSError:
        pass
    return sessions


def _sort_sessions(sessions: List[SessionRecord]) -> List[SessionRecord]:
    """Ordina le sessioni per (lesson_date, timestamp_iso)."""
    return sorted(sessions, key=lambda s: (s.lesson_date or "", s.timestamp_iso or ""))


def upsert_session(
    report: AssessmentReport,
    sessions_file: Path | str,
    audio_file: str,
    lesson_date_iso: str
) -> SessionRecord:
    """
    Inserisce o aggiorna un record di sessione nel file JSONL:
    1. Carica tutte le sessioni esistenti
    2. Calcola i conteggi degli errori e gli errori ricorrenti rispetto alle sole
       sessioni con lesson_date antecedente a lesson_date_iso (esclusa la stessa lezione)
    3. Sostituisce il record con lo stesso audio_file (basename case-insensitive) o lo aggiunge
    4. Ordina cronologicamente per (lesson_date, timestamp_iso)
    5. Salva in modo atomico
    """
    sessions_path = Path(sessions_file)
    existing_sessions = load_sessions(sessions_path)
    target_basename = Path(audio_file).name.lower()
    student_key = (report.student_name or "Studente").strip().lower()

    def same_student(s: SessionRecord) -> bool:
        return (s.student_name or "Studente").strip().lower() == student_key

    # Filtra le sole sessioni cronologicamente precedenti
    prior_sessions = [
        s for s in existing_sessions
        if same_student(s)
        and (s.lesson_date and s.lesson_date < lesson_date_iso)
        and Path(s.audio_file).name.lower() != target_basename
    ]

    error_counts = _count_errors_by_type(report)
    recurring = _find_recurring_errors(error_counts, prior_sessions)
    weighted = _compute_weighted_score(report)

    record = SessionRecord(
        session_id=_generate_session_id(),
        lesson_date=lesson_date_iso,
        date=report.session_date,
        timestamp_iso=datetime.now().isoformat(),
        audio_file=Path(audio_file).name,
        student_name=report.student_name or "Studente",
        cefr_level=report.cefr_level,
        score_phonetics=report.score_phonetics,
        score_grammar=report.score_grammar,
        score_lexicon=report.score_lexicon,
        score_fluency=report.score_fluency,
        score_autonomy=report.score_autonomy,
        score_weighted=weighted,
        error_counts=error_counts,
        recurring_error_types=recurring,
        validation_proposed=report.validation_stats.total_proposed if report.validation_stats else 0,
        validation_validated=report.validation_stats.total_validated if report.validation_stats else 0,
        validation_discarded=report.validation_stats.total_discarded if report.validation_stats else 0,
        transcript_source=report.validation_stats.transcript_source if report.validation_stats else "llm",
    )

    # Upsert: sostituisci se esiste per lo stesso file audio, altrimenti aggiungi
    replaced = False
    updated_list: List[SessionRecord] = []
    for s in existing_sessions:
        if same_student(s) and Path(s.audio_file).name.lower() == target_basename:
            updated_list.append(record)
            replaced = True
        else:
            updated_list.append(s)

    if not replaced:
        updated_list.append(record)

    # Ordina cronologicamente
    sorted_list = _sort_sessions(updated_list)

    # Scrittura atomica
    sessions_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = sessions_path.parent / f"{sessions_path.name}.tmp.{os.getpid()}"

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            for s in sorted_list:
                f.write(s.model_dump_json() + "\n")
        os.replace(temp_file, sessions_path)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass

    return record


def get_session_summary(
    sessions_file: Path | str,
    current_audio_file: Optional[str] = None,
    student_name: Optional[str] = None,
) -> Optional[Dict]:
    """
    Restituisce un sommario per il template HTML:
    - Ordina per data (lesson_date, timestamp_iso)
    - La sessione corrente e quella corrispondente al file audio passato;
      se assente o non trovato, usa l'ultima sessione
    - Storico: fino a 10 sessioni fino alla corrente inclusa
    - Delta: calcolato rispetto alla sessione immediatamente precedente nello storico
    """
    sessions = _sort_sessions(load_sessions(sessions_file))
    if student_name:
        key = student_name.strip().lower()
        sessions = [s for s in sessions if (s.student_name or "Studente").strip().lower() == key]
    if not sessions:
        return None

    # Individua la sessione corrente
    current_idx = -1
    if current_audio_file:
        target_name = Path(current_audio_file).name.lower()
        for i, s in enumerate(sessions):
            if Path(s.audio_file).name.lower() == target_name:
                current_idx = i
                break

    if current_idx == -1:
        current_idx = len(sessions) - 1

    current = sessions[current_idx]
    previous = sessions[current_idx - 1] if current_idx > 0 else None

    # Fino a 10 sessioni fino a current inclusa
    start_idx = max(0, current_idx - 9)
    history_window = sessions[start_idx : current_idx + 1]

    summary: Dict = {
        "total_sessions": len(sessions),
        "scores_history": [
            {
                "date": s.date,
                "weighted": s.score_weighted,
                "phonetics": s.score_phonetics,
                "grammar": s.score_grammar,
                "lexicon": s.score_lexicon,
                "fluency": s.score_fluency,
                "autonomy": s.score_autonomy,
            }
            for s in history_window
        ],
        "recurring_errors": current.recurring_error_types,
        "delta": None,
    }

    if previous:
        summary["delta"] = {
            "weighted": round(current.score_weighted - previous.score_weighted, 2),
            "phonetics": round(current.score_phonetics - previous.score_phonetics, 1),
            "grammar": round(current.score_grammar - previous.score_grammar, 1),
            "lexicon": round(current.score_lexicon - previous.score_lexicon, 1),
            "fluency": round(current.score_fluency - previous.score_fluency, 1),
            "autonomy": round(current.score_autonomy - previous.score_autonomy, 1),
        }

    return summary
