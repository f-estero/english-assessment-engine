"""Difetti emersi dalla revisione finale (ognuno riprodotto prima della correzione)."""
import csv
import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

import merge
import session_store
from export_study import export_csv
from lesson_paths import lesson_date

APP_DIR = Path(__file__).resolve().parent.parent


def test_pre_commit_blocks_key_at_start_of_line(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    key = "AIza" + "B" * 35
    (tmp_path / "chiave.txt").write_text(key + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "chiave.txt"], check=True)
    hook = (APP_DIR / ".githooks" / "pre-commit").as_posix()
    import shutil
    shell = shutil.which("sh") or shutil.which("bash")
    res = subprocess.run([shell, hook], cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 1


def test_iso_dates_in_file_names(tmp_path):
    for name in ("2026-09-12 lezione.m4a", "Recording 2026-09-12 10.30.15.m4a", "lezione_20260912.m4a"):
        p = tmp_path / name
        p.write_bytes(b"x")
        assert lesson_date(p) == date(2026, 9, 12), name


def test_hh_mm_ss_timestamps():
    assert merge.parse_mmss("00:05:30") == 330
    assert merge.parse_mmss("1:02:03") == 3723
    assert merge.parse_mmss("[12:04]") == 724


def test_history_is_per_student(tmp_path, sample_report):
    f = tmp_path / "sessions.jsonl"
    mario, anna = sample_report.model_copy(deep=True), sample_report.model_copy(deep=True)
    mario.student_name, anna.student_name = "Mario", "Anna"
    session_store.upsert_session(mario, f, "Lezione 12.09.m4a", "2026-09-12")
    session_store.upsert_session(anna, f, "Lezione 12.09.m4a", "2026-09-12")
    session_store.upsert_session(anna, f, "Lezione 15.09.m4a", "2026-09-15")
    assert len(f.read_text(encoding="utf-8").splitlines()) == 3
    s = session_store.get_session_summary(f, "Lezione 15.09.m4a", student_name="Anna")
    assert s["total_sessions"] == 2 and len(s["scores_history"]) == 2


def test_csv_has_minutes_for_every_table(tmp_path, sample_report):
    r = sample_report.model_copy(deep=True)
    r.phonetics_table[0].timestamp_derived = "03:10"
    r.lexical_table[0].timestamp_derived = "07:45"
    out = tmp_path / "errori.csv"
    export_csv(r, str(out))
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig"), delimiter=";"))
    by_type = {row["type"]: row["timestamp"] for row in rows}
    assert by_type["phonetics"] == "03:10" and by_type["lexical"] == "07:45"


def test_gitignore_covers_more_audio_formats():
    text = (APP_DIR / ".gitignore").read_text(encoding="utf-8")
    for ext in ("*.opus", "*.webm", "*.wma", "*.amr", "*.3gp", "*.mov", "*.mkv"):
        assert ext in text
