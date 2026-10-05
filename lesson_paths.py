"""
lesson_paths.py — Gestione date delle lezioni, cartelle per mese e risoluzione percorsi.

Consente di:
1. Estrarre la data effettiva della lezione dal nome del file audio (con fallback alla data di modifica)
2. Assegnare la lezione alla relativa sottocartella del mese (es. "Settembre 26")
3. Trovare o creare la cartella della lezione in modo univoco ed esatto, garantendo
   coerenza tra report scritto e traccia audio review.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

MESI = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]

# Regex data: giorno (1-2 cifre), separatore '.' o '-', mese (1-2 cifre), anno opzionale (2 o 4 cifre)
# Delimitatori negativi (?<!\d) e (?!\d) per evitare catture parziali
_DATE_REGEX = re.compile(r"(?<!\d)(\d{1,2})[.-](\d{1,2})(?:[.-](\d{4}|\d{2}))?(?!\d)")
_ISO_DATE_REGEX = re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")
_DIR_PREFIX_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}_(.*)$", re.IGNORECASE)


def slug(text: str) -> str:
    """Normalizza una stringa sostituendo caratteri speciali e spazi con underscore."""
    return re.sub(r"[^\w\-]", "_", text.strip())


def lesson_date(audio_path: Path) -> date:
    """Estrae la data della lezione dal nome del file audio.
    Cerca la prima corrispondenza valida nel formato GG.MM o GG.MM.AAAA o GG-MM-AAAA.
    - Se l'anno manca, usa l'anno di modifica del file (o l'anno corrente).
    - Se l'anno e a 2 cifre, assume 2000+.
    - Se nessuna data valida e presente, usa la data di modifica del file.
    """
    stem = audio_path.stem

    # Date ISO (AAAA-MM-GG o AAAAMMGG), tipiche delle registrazioni del telefono
    for m in _ISO_DATE_REGEX.finditer(stem):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue

    for m in _DATE_REGEX.finditer(stem):
        day_str, month_str, year_str = m.group(1), m.group(2), m.group(3)
        try:
            day = int(day_str)
            month = int(month_str)

            if year_str:
                year = int(year_str)
                if year < 100:
                    year += 2000
            else:
                # Anno mancante: prova dalla data di modifica del file se esiste
                if audio_path.is_file():
                    year = datetime.fromtimestamp(audio_path.stat().st_mtime).date().year
                else:
                    year = date.today().year

            return date(year, month, day)
        except ValueError:
            # Giorno/mese non validi (es. mese > 12), prosegui alla prossima corrispondenza
            continue

    # Fallback: data di modifica del file (o oggi)
    if audio_path.is_file():
        return datetime.fromtimestamp(audio_path.stat().st_mtime).date()
    return date.today()


def month_folder_name(d: date) -> str:
    """Restituisce il nome della cartella del mese per la data specificata (es. 'Settembre 26')."""
    return f"{MESI[d.month - 1]} {d.year % 100:02d}"


def format_date_it(d: date) -> str:
    """Formatta la data in italiano esteso (es. '12 Settembre 2026' o '05 Settembre 2026')."""
    return f"{d.day:02d} {MESI[d.month - 1]} {d.year}"


def lesson_key(student: str, audio_path: Path) -> str:
    """Costruisce la chiave identificativa univoca della lezione:
    f'{slug(student)}_{slug(audio_path.stem)}'."""
    return f"{slug(student)}_{slug(audio_path.stem)}"


def find_lesson_dir(output_dir: Path, key: str) -> Optional[Path]:
    """Cerca una cartella di lezione corrispondente esattamente alla chiave specificata.
    Scansiona:
    1. La radice di output_dir
    2. Le sottocartelle dirette (profondita 2, es. 'Settembre 26')

    Una cartella e considerata corrispondente se il suo nome inizia per 'YYYY-MM-DD_'
    e il resto del nome corrisponde esattamente a key (senza distinzione maiuscole/minuscole).
    Evita corrispondenze spurie come '26_09' con '26_09_2'.
    """
    if not output_dir.is_dir():
        return None

    target_key = key.lower()

    # 1. Cerca nella radice di output_dir
    try:
        for entry in output_dir.iterdir():
            if entry.is_dir():
                m = _DIR_PREFIX_REGEX.match(entry.name)
                if m and m.group(1).lower() == target_key:
                    return entry

        # 2. Cerca nelle sottocartelle dirette (profondita 2)
        for sub in output_dir.iterdir():
            if sub.is_dir():
                for entry in sub.iterdir():
                    if entry.is_dir():
                        m = _DIR_PREFIX_REGEX.match(entry.name)
                        if m and m.group(1).lower() == target_key:
                            return entry
    except OSError:
        pass

    return None


def resolve_lesson_dir(output_dir: Path, student: str, audio_path: Path) -> Path:
    """Risolve o crea la cartella unificata per la lezione.
    Se una cartella esistente corrisponde alla chiave (anche con data ISO di elaborazione precedente),
    la riutilizza.
    Altrimenti crea una nuova cartella:
    output_dir / month_folder_name(d) / f'{d.isoformat()}_{key}'
    dove d e la data della lezione.
    """
    key = lesson_key(student, audio_path)
    existing = find_lesson_dir(output_dir, key)
    if existing:
        return existing

    d = lesson_date(audio_path)
    month_name = month_folder_name(d)
    dir_name = f"{d.isoformat()}_{key}"
    target = output_dir / month_name / dir_name
    target.mkdir(parents=True, exist_ok=True)
    return target
