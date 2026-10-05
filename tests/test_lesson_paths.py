"""
tests/test_lesson_paths.py — Test per estrazione date e risoluzione percorsi lezioni.
"""

import os
from datetime import date, datetime
from pathlib import Path
import pytest

from lesson_paths import (
    slug,
    lesson_date,
    month_folder_name,
    format_date_it,
    lesson_key,
    find_lesson_dir,
    resolve_lesson_dir,
)


def test_slug():
    assert slug("Mario") == "Mario"
    assert slug("Lezione inglese 12.09") == "Lezione_inglese_12_09"
    assert slug("Test & Demo #1") == "Test___Demo__1"


def test_lesson_date_formats(tmp_path):
    # Data con giorno.mese
    d1 = lesson_date(Path("Lezione inglese 12.09.m4a"))
    assert d1.day == 12
    assert d1.month == 9

    # Data con giorno.mese_suffisso
    d2 = lesson_date(Path("Lezione di inglese 26.09_1.m4a"))
    assert d2.day == 26
    assert d2.month == 9

    # Data completa giorno-mese-anno a 4 cifre
    d3 = lesson_date(Path("lezione 05-09-2026.wav"))
    assert d3 == date(2026, 9, 5)

    # Anno a 2 cifre
    d4 = lesson_date(Path("lezione 15.08.26.mp3"))
    assert d4 == date(2026, 8, 15)

    # Spazio e underscore non separano: "Lezione 2 12.09" non deve essere 2 dicembre
    d5 = lesson_date(Path("Lezione 2 12.09.mp3"))
    assert d5.day == 12
    assert d5.month == 9


def test_lesson_date_fallback_mtime(tmp_path):
    # File senza data nel nome: fallback alla data di modifica
    test_file = tmp_path / "Riunione di lavoro.mp3"
    test_file.write_text("dummy")
    # Imposta mtime a una data nota: 2025-04-10
    dt = datetime(2025, 4, 10, 12, 0, 0)
    os.utime(test_file, (dt.timestamp(), dt.timestamp()))

    res = lesson_date(test_file)
    assert res == date(2025, 4, 10)


def test_month_folder_name():
    assert month_folder_name(date(2026, 8, 31)) == "Agosto 26"
    assert month_folder_name(date(2026, 9, 12)) == "Settembre 26"
    assert month_folder_name(date(2026, 10, 5)) == "Ottobre 26"
    assert month_folder_name(date(2027, 1, 15)) == "Gennaio 27"


def test_format_date_it():
    assert format_date_it(date(2026, 9, 12)) == "12 Settembre 2026"
    assert format_date_it(date(2026, 9, 5)) == "05 Settembre 2026"


def test_find_lesson_dir_exact_match(tmp_path):
    out_dir = tmp_path / "Report"
    out_dir.mkdir()

    # Creazione cartelle di test
    dir_26_09 = out_dir / "Settembre 26" / "2026-09-26_Mario_Lezione_di_inglese_26_09"
    dir_26_09.mkdir(parents=True)

    dir_26_09_2 = out_dir / "Settembre 26" / "2026-09-26_Mario_Lezione_di_inglese_26_09_2"
    dir_26_09_2.mkdir(parents=True)

    # Cerca la chiave 26_09: non deve matchare 26_09_2
    key_1 = "Mario_Lezione_di_inglese_26_09"
    found_1 = find_lesson_dir(out_dir, key_1)
    assert found_1 is not None
    assert found_1 == dir_26_09

    key_2 = "Mario_Lezione_di_inglese_26_09_2"
    found_2 = find_lesson_dir(out_dir, key_2)
    assert found_2 is not None
    assert found_2 == dir_26_09_2

    # Inesistente
    assert find_lesson_dir(out_dir, "Mario_Lezione_Inesistente") is None


def test_find_lesson_dir_old_root_format(tmp_path):
    out_dir = tmp_path / "Report"
    out_dir.mkdir()

    # Vecchia cartella salvata direttamente nella radice di Report con data diversa
    old_dir = out_dir / "2026-09-06_Mario_Lezione_inglese_31_08"
    old_dir.mkdir()

    found = find_lesson_dir(out_dir, "Mario_Lezione_inglese_31_08")
    assert found == old_dir


def test_resolve_lesson_dir(tmp_path):
    out_dir = tmp_path / "Report"
    audio_path = tmp_path / "Lezione inglese 12.09.m4a"
    audio_path.write_text("audio data")

    # Nuova cartella creata nel mese corretto
    resolved = resolve_lesson_dir(out_dir, "Mario", audio_path)
    assert resolved.exists()
    assert resolved.parent.name == "Settembre 26"
    assert "2026-09-12_Mario_Lezione_inglese_12_09" in resolved.name

    # Seconda chiamata per la stessa lezione restituisce la cartella gia creata
    resolved_again = resolve_lesson_dir(out_dir, "Mario", audio_path)
    assert resolved_again == resolved
