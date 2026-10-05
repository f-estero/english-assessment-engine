import os

import keyring
import pytest

import app_config
from app_config import Settings


def test_settings_roundtrip(tmp_appdata):
    app_config.save_settings(Settings(output_dir="X", student_name="A"))
    s = app_config.load_settings()
    assert (s.output_dir, s.student_name, s.model) == ("X", "A", app_config.DEFAULT_MODEL)
    assert (tmp_appdata / "EnglishAssessmentEngine" / "settings.json").exists()


def test_settings_corrupt_returns_defaults(tmp_appdata):
    d = tmp_appdata / "EnglishAssessmentEngine"
    d.mkdir()
    (d / "settings.json").write_text("{non json", encoding="utf-8")
    assert app_config.load_settings() == Settings()


def test_api_key_precedence(tmp_appdata, fake_keyring, monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "app_root", lambda: tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
    fake_keyring[(app_config.APP_NAME, app_config.API_KEY_ENV)] = "from-keyring"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert app_config.get_api_key() == ("from-env", "env")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert app_config.get_api_key() == ("from-dotenv", "dotenv")
    (tmp_path / ".env").unlink()
    assert app_config.get_api_key() == ("from-keyring", "keyring")
    fake_keyring.clear()
    assert app_config.get_api_key() == (None, "")


def test_dotenv_does_not_pollute_environ(monkeypatch, tmp_path, fake_keyring):
    monkeypatch.setattr(app_config, "app_root", lambda: tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
    assert app_config.get_api_key()[1] == "dotenv"
    assert "GEMINI_API_KEY" not in os.environ


def test_keyring_errors_mean_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "app_root", lambda: tmp_path)

    def boom(*a):
        raise RuntimeError("no backend")
    monkeypatch.setattr(keyring, "get_password", boom)
    assert app_config.get_api_key() == (None, "")


def test_key_never_in_settings(tmp_appdata, fake_keyring):
    app_config.save_settings(Settings(output_dir="X"))
    app_config.save_api_key(" abc123 ")
    assert fake_keyring[(app_config.APP_NAME, app_config.API_KEY_ENV)] == "abc123"
    text = (tmp_appdata / "EnglishAssessmentEngine" / "settings.json").read_text(encoding="utf-8")
    assert "abc123" not in text


def test_system_certificates_enabled_by_entry_point():
    """Antivirus/proxy che ispezionano HTTPS (es. Norton) firmano con una CA presente solo nello store di Windows."""
    import ssl
    import truststore
    import generate_report  # noqa: F401  — l'import del punto di ingresso attiva lo store di sistema
    assert issubclass(ssl.SSLContext, truststore.SSLContext)


def test_models_and_analysis_mode(tmp_appdata):
    assert app_config.DEFAULT_MODEL == "gemini-3.8-flash"
    assert app_config.GUI_MODELS == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-pro-latest"]
    assert app_config.MODELS == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                                 "gemini-flash-latest", "gemini-pro-latest", "gemini-2.5-flash"]
    assert Settings().analysis_mode == "base"
    app_config.save_settings(Settings(output_dir="X", model="gemini-3.6-flash", analysis_mode="avanzata"))
    s = app_config.load_settings()
    assert (s.model, s.analysis_mode) == ("gemini-3.6-flash", "avanzata")
    app_config.save_settings(Settings(output_dir="X", analysis_mode="xyz"))
    assert app_config.load_settings().analysis_mode == "base"
