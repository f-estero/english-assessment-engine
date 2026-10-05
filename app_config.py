"""
app_config.py — Impostazioni utente, gestione chiave API e percorsi applicativi.

Unica fonte di verita per impostazioni, credenziali e percorsi.
Nessun altro modulo legge direttamente il file .env o il keyring.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from dotenv import dotenv_values

APP_NAME = "EnglishAssessmentEngine"
API_KEY_ENV = "GEMINI_API_KEY"
# Modelli mostrati nella GUI (verificati sull'analisi audio, vedi docs/superpowers/specs)
GUI_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-pro-latest"]
# Ordine di ripiego automatico se il modello scelto non risponde
MODELS = [
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
    "gemini-flash-latest", "gemini-pro-latest", "gemini-2.5-flash",
]
ANALYSIS_MODES = ("base", "avanzata")
DEFAULT_MODEL = MODELS[0]


def app_root() -> Path:
    """Restituisce la cartella dell'eseguibile se congelato (PyInstaller),
    altrimenti la cartella radice del codice sorgente."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(*parts: str | Path) -> Path:
    """Restituisce il percorso di una risorsa interna (es. templates, assets).
    Se l'app e congelata con PyInstaller, cerca all'interno di sys._MEIPASS."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).joinpath(*parts)
    return app_root().joinpath(*parts)


def user_config_dir() -> Path:
    """Restituisce la cartella per i dati di configurazione dell'utente:
    %APPDATA%\\EnglishAssessmentEngine su Windows, ~/.config/EnglishAssessmentEngine altrove."""
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else (Path.home() / "AppData" / "Roaming")
    else:
        base = Path.home() / ".config"
    return base / APP_NAME


@dataclass
class Settings:
    output_dir: str = ""
    student_name: str = ""
    model: str = DEFAULT_MODEL
    analysis_mode: str = "base"


def load_settings() -> Settings:
    """Carica le impostazioni da settings.json.
    Se il file e assente o corrotto restituisce i default, senza sollevare eccezioni."""
    config_file = user_config_dir() / "settings.json"
    if not config_file.is_file():
        return Settings()

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return Settings()

        output_dir = str(data.get("output_dir", "") or "").strip()
        student_name = str(data.get("student_name", "") or "").strip()
        model = str(data.get("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
        if model not in MODELS:
            model = DEFAULT_MODEL

        mode = str(data.get("analysis_mode", "base") or "base").strip()
        if mode not in ANALYSIS_MODES:
            mode = "base"

        return Settings(
            output_dir=output_dir,
            student_name=student_name,
            model=model,
            analysis_mode=mode,
        )
    except Exception:
        return Settings()


def save_settings(s: Settings) -> None:
    """Salva le impostazioni in modo atomico (file temporaneo + rename atomico)."""
    cfg_dir = user_config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    target_file = cfg_dir / "settings.json"
    temp_file = cfg_dir / f"settings.json.tmp.{os.getpid()}"

    data = {
        "output_dir": s.output_dir.strip(),
        "student_name": s.student_name.strip(),
        "model": s.model if s.model in MODELS else DEFAULT_MODEL,
        "analysis_mode": s.analysis_mode if s.analysis_mode in ANALYSIS_MODES else "base",
    }

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, target_file)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def get_api_key() -> tuple[str | None, str]:
    """Recupera la chiave API Gemini e la sua sorgente secondo la precedenza:
    1. Variabile d'ambiente GEMINI_API_KEY -> 'env'
    2. File .env nella cartella dell'app -> 'dotenv'
    3. Gestione credenziali di Windows via keyring -> 'keyring'
    Altrimenti (None, '').

    Eventuali errori del keyring vengono trattati come chiave assente senza propagare eccezioni.
    """
    # 1. Variabile d'ambiente
    env_key = os.environ.get(API_KEY_ENV)
    if env_key and env_key.strip():
        return env_key.strip(), "env"

    # 2. File .env nella cartella dell'applicazione (dotenv_values non tocca os.environ)
    env_file = app_root() / ".env"
    if env_file.is_file():
        try:
            values = dotenv_values(env_file)
            dotenv_key = values.get(API_KEY_ENV)
            if dotenv_key and str(dotenv_key).strip():
                return str(dotenv_key).strip(), "dotenv"
        except Exception:
            pass

    # 3. Credenziali di Windows / Keyring
    try:
        import keyring

        key = keyring.get_password(APP_NAME, API_KEY_ENV)
        if key and key.strip():
            return key.strip(), "keyring"
    except Exception:
        pass

    return None, ""


def save_api_key(key: str) -> None:
    """Salva la chiave API ripulita da spazi nella Gestione credenziali di Windows via keyring."""
    clean_key = key.strip()
    import keyring

    keyring.set_password(APP_NAME, API_KEY_ENV, clean_key)


def delete_api_key() -> None:
    """Rimuove la chiave API dalla Gestione credenziali di Windows."""
    try:
        import keyring

        keyring.delete_password(APP_NAME, API_KEY_ENV)
    except Exception:
        pass


def enable_system_certificates() -> None:
    """Usa i certificati di Windows/macOS invece del bundle interno di Python.
    Necessario dietro antivirus o proxy che ispezionano HTTPS (es. Norton),
    altrimenti ogni chiamata fallisce con CERTIFICATE_VERIFY_FAILED."""
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass
