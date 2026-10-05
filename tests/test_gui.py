"""
tests/test_gui.py — Test per inizializzazione GUI (senza mostrare la finestra).
"""

import tkinter as tk
import pytest
from app_gui import AssessmentEngineGUI


@pytest.fixture(scope="module")
def tk_root():
    """Un solo interprete Tk per modulo: crearne e distruggerne più d'uno nello stesso processo
    su Windows è fragile (init.tcl non trovato)."""
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        pytest.skip(f"Ambiente senza display o supporto Tk: {e}")
    yield root
    root.destroy()


@pytest.fixture
def root(tk_root):
    yield tk_root
    for w in tk_root.winfo_children():
        w.destroy()


def test_gui_instantiation(root):
    app = AssessmentEngineGUI(root)
    assert app is not None
    assert app.root.title().startswith("English Assessment Engine")
    assert app.btn_start is not None
    assert app.btn_audio is not None
    assert app.btn_stop is not None
    assert app.ent_student is not None
    assert app.cmb_model is not None


def test_gui_mode_models_force_and_help(root, tmp_appdata, fake_keyring, tmp_path):
    import app_config
    import app_gui
    app_config.save_settings(app_config.Settings(output_dir=str(tmp_path), analysis_mode="avanzata",
                                                 model="gemini-3.6-flash"))
    app = AssessmentEngineGUI(root)
    assert app.var_mode.get() == "avanzata"
    assert list(app.cmb_model["values"]) == app_config.GUI_MODELS + ["gemini-3.6-flash"]  # salvato ma fuori lista
    assert app.cmb_model.get() == "gemini-3.6-flash"
    assert app.var_force.get() is False
    for words in ("1 chiamata", "spezzoni", "piano gratuito", "AI Studio"):
        assert words in app_gui.ANALYSIS_HELP_TEXT


def test_cli_help_lists_mode_and_force():
    import subprocess, sys
    from pathlib import Path
    out = subprocess.run([sys.executable, "generate_report.py", "--help"], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent).stdout
    assert "--mode" in out and "--force" in out and "avanzata" in out
