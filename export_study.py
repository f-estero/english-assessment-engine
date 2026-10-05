"""
export_study.py — Esportazione errori per studio attivo.

Esporta gli errori estratti dal report (grammatica, fonetica, lessico)
in formato CSV UTF-8 con delimitatore punto e virgola.
"""

from __future__ import annotations

import csv
import os
from typing import List
from schema import AssessmentReport


def export_csv(report: AssessmentReport, output_path: str) -> str:
    """
    Esporta tutti gli errori (grammatica, fonetica, lessico) in un unico file CSV.
    Colonne: type, entry_id, quote_or_term, correction_or_target, error_category,
             detail, rule, source, llm_confidence, verified_confidence, timestamp
    """
    rows = []

    # Grammatica
    for entry in report.grammar_table:
        rows.append({
            "type": "grammar",
            "entry_id": entry.entry_id,
            "quote_or_term": entry.audio_quote,
            "correction_or_target": entry.correction,
            "error_category": entry.error_type,
            "detail": entry.l1_interference,
            "rule": entry.rule_and_example,
            "source": entry.source,
            "llm_confidence": entry.llm_confidence,
            "verified_confidence": entry.verified_confidence if entry.verified_confidence is not None else "",
            "timestamp": entry.timestamp_derived or "",
        })

    # Fonetica
    for entry in report.phonetics_table:
        rows.append({
            "type": "phonetics",
            "entry_id": entry.entry_id,
            "quote_or_term": entry.term,
            "correction_or_target": entry.target_ipa or "N/D",
            "error_category": entry.category,
            "detail": f"Percepito: {entry.perceived_ipa} | Accento: {entry.stress_displacement}",
            "rule": entry.practical_drill,
            "source": entry.source,
            "llm_confidence": entry.llm_confidence,
            "verified_confidence": entry.verified_confidence if entry.verified_confidence is not None else "",
            "timestamp": entry.timestamp_derived or "",
        })

    # Lessico
    for entry in report.lexical_table:
        rows.append({
            "type": "lexical",
            "entry_id": entry.entry_id,
            "quote_or_term": entry.used_term,
            "correction_or_target": entry.target_term,
            "error_category": "Calco Lessicale",
            "detail": entry.calque_or_error,
            "rule": entry.context_note,
            "source": entry.source,
            "llm_confidence": entry.llm_confidence,
            "verified_confidence": entry.verified_confidence if entry.verified_confidence is not None else "",
            "timestamp": entry.timestamp_derived or "",
        })

    if not rows:
        return output_path

    fieldnames = [
        "type", "entry_id", "quote_or_term", "correction_or_target",
        "error_category", "detail", "rule", "source",
        "llm_confidence", "verified_confidence", "timestamp"
    ]

    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    return output_path
