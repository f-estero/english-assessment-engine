"""
report_format.py — Funzioni di presentazione per il template del report.

- correction_diff: la frase dello studente con le parole sbagliate barrate e quelle corrette inserite,
  come la correzione a penna di un insegnante.
- timeline: posizione nel tempo di ogni errore, per mostrare quanta parte della lezione è coperta.
- num / signed: numeri in formato italiano.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from markupsafe import Markup, escape

from merge import duration_seconds, parse_mmss
from schema import AssessmentReport


def correction_diff(quote: str, correction: str) -> Markup:
    """Confronta parola per parola (senza distinguere maiuscole) e marca solo ciò che cambia."""
    a, b = (quote or "").split(), (correction or "").split()
    ops = SequenceMatcher(a=[w.lower() for w in a], b=[w.lower() for w in b], autojunk=False).get_opcodes()
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in ops:
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if tag == "equal":
            parts.append(str(escape(old)))
        if tag in ("replace", "delete"):
            parts.append(f"<del>{escape(old)}</del>")
        if tag in ("replace", "insert"):
            parts.append(f"<ins>{escape(new)}</ins>")
    return Markup(" ".join(parts))


def timeline(report: AssessmentReport) -> dict:
    """Punti della linea del tempo (percentuale della durata) e conteggi per tipo di voce."""
    duration = duration_seconds(report.audio_sample_duration)
    tables = {"grammar": report.grammar_table, "phonetics": report.phonetics_table,
              "lexical": report.lexical_table}
    points = []
    for kind, entries in tables.items():
        for e in entries:
            t = parse_mmss(getattr(e, "timestamp_derived", None))
            if t is not None and duration > 0:
                points.append({"kind": kind, "pct": round(min(t / duration, 1.0) * 100, 1),
                               "label": getattr(e, "timestamp_derived")})
    return {"minutes": round(duration / 60), "points": points,
            "counts": {k: len(v) for k, v in tables.items()}}


def num(x: float, decimals: int = 1) -> str:
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return f"{q}".replace(".", ",")


def signed(x: float) -> str:
    return ("+" if x >= 0 else "−") + num(abs(x))
