"""
app_gui.py — Interfaccia Grafica Desktop per English Assessment Engine.

Fornisce:
1. Configurazione persistente (Nome studente, Modello, Cartella output, Chiave API)
2. Gestione sicura delle credenziali con Windows Credential Manager (keyring)
3. Coda di file audio per elaborazione batch e generazione Audio Review MP3
4. Monitoraggio avanzato del progresso e log in tempo reale
5. Integrazione con taskbar e icone native di Windows
"""

from __future__ import annotations

import os
import sys
import threading
import queue
import webbrowser
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from app_config import (
    APP_NAME,
    MODELS,
    GUI_MODELS,
    DEFAULT_MODEL,
    Settings,
    load_settings,
    save_settings,
    get_api_key,
    save_api_key,
    delete_api_key,
    resource_path,
)


ANALYSIS_HELP_TEXT = (
    "BASE — 1 chiamata per lezione\n"
    "Adatta al piano gratuito di Gemini. L'intera registrazione viene analizzata in una sola richiesta: "
    "veloce ed economica, ma sulle lezioni lunghe il modello si concentra sui primi 15-20 minuti "
    "(nelle nostre misure l'83% degli errori trovati cade nella prima metà della lezione).\n\n"
    "AVANZATA — circa 1 chiamata ogni 10 minuti + 1 di sintesi\n"
    "(una lezione di 45 minuti ≈ 6 chiamate). L'audio viene diviso in spezzoni da 10 minuti analizzati "
    "separatamente: copre tutta la lezione e trova circa 4 volte più errori. Consigliata con un piano "
    "a pagamento o con limiti giornalieri ampi. Richiede 1-2 minuti per lezione.\n\n"
    "RIELABORA — se spuntato, rianalizza anche le lezioni che hanno già un report (nuove chiamate).\n\n"
    "I limiti della tua chiave sono in Google AI Studio → Usage / Rate limits."
)


class AssessmentEngineGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("English Assessment Engine — Batch Diagnostic Processor")
        self.root.geometry("900x800")
        self.root.minsize(820, 700)

        # Icona applicativa e ID Windows per taskbar
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
            except Exception:
                pass

        icon_path = resource_path("assets", "app.ico")
        if icon_path.is_file():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

        # Caricamento impostazioni utente
        self.settings: Settings = load_settings()

        # Coda di elaborazione e stato
        self.audio_files: List[str] = []
        self.processing_thread: Optional[threading.Thread] = None
        self.stop_requested = False
        self.log_queue: queue.Queue = queue.Queue()

        self._apply_styles()
        self._build_ui()
        self._refresh_api_key_status()

        # Polling della coda dei log per aggiornare l'interfaccia in modo thread-safe
        self.root.after(100, self._process_log_queue)

    def _apply_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.c_bg = "#EEF1F4"
        self.c_card = "#ffffff"
        self.c_primary = "#1F2A44"
        self.c_primary_hover = "#33406A"
        self.c_dark = "#1F2A44"
        self.c_text = "#1F2A44"
        self.c_purple = "#FFFFFF"
        self.c_purple_hover = "#E3E8EE"

        self.root.configure(bg=self.c_bg)

        style.configure("TFrame", background=self.c_bg)
        style.configure("Card.TFrame", background=self.c_card, relief="solid", borderwidth=1)
        style.configure("TLabel", background=self.c_bg, foreground=self.c_text, font=("Segoe UI", 9))
        style.configure("Bold.TLabel", font=("Segoe UI", 9, "bold"), background=self.c_bg, foreground=self.c_dark)
        style.configure("Header.TLabel", background=self.c_dark, foreground="#ffffff", font=("Segoe UI", 12, "bold"))
        style.configure("SubHeader.TLabel", background=self.c_dark, foreground="#94a3b8", font=("Segoe UI", 8))
        style.configure("Title.TLabel", background=self.c_bg, foreground=self.c_dark, font=("Segoe UI", 11, "bold"))

        style.configure("Primary.TButton", font=("Bahnschrift", 10), background=self.c_primary, foreground="#ffffff", bordercolor=self.c_primary, padding=(14, 6))
        style.map("Primary.TButton", background=[("active", self.c_primary_hover)])

        style.configure("Secondary.TButton", font=("Bahnschrift", 10), background=self.c_purple, foreground=self.c_primary, bordercolor=self.c_primary, padding=(14, 6))
        style.map("Secondary.TButton", background=[("active", self.c_purple_hover)])

        style.configure("TProgressbar", thickness=10, troughcolor="#D5DCE4", background=self.c_primary, bordercolor="#D5DCE4")
        style.configure("TLabelframe", background=self.c_bg, bordercolor="#D5DCE4")
        style.configure("TLabelframe.Label", background=self.c_bg, foreground=self.c_dark, font=("Bahnschrift", 10))
        style.configure("TButton", font=("Segoe UI", 9))
        style.configure("TRadiobutton", background=self.c_bg, foreground=self.c_text, font=("Segoe UI", 9))
        style.configure("TCheckbutton", background=self.c_bg, foreground=self.c_text, font=("Segoe UI", 9))

        style.configure("Treeview", font=("Segoe UI", 9), rowheight=24, background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Bahnschrift", 9), background="#E3E8EE", foreground=self.c_dark)

    def _build_ui(self):
        # 1. HEADER BAR
        header_frame = tk.Frame(self.root, bg=self.c_dark, height=54)
        header_frame.pack(fill="x", side="top")

        lbl_title = tk.Label(
            header_frame,
            text="English Assessment Engine",
            font=("Bahnschrift", 16),
            bg=self.c_dark,
            fg="#ffffff",
        )
        lbl_title.pack(anchor="w", padx=16, pady=(8, 0))
        lbl_sub = tk.Label(
            header_frame,
            text="Analisi delle lezioni di conversazione in inglese",
            font=("Segoe UI", 9),
            bg=self.c_dark,
            fg="#B7C0D4",
        )
        lbl_sub.pack(anchor="w", padx=16, pady=(0, 8))

        # MAIN CONTAINER
        main_container = ttk.Frame(self.root, padding=12)
        main_container.pack(fill="both", expand=True)

        # 2. SEZIONE CONFIGURAZIONE (3 Righe)
        config_frame = ttk.LabelFrame(main_container, text=" Impostazioni ", padding=10)
        config_frame.pack(fill="x", pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        # Riga 1: Nome Studente + Modello Gemini
        row1 = ttk.Frame(config_frame)
        row1.pack(fill="x", pady=(0, 6))

        ttk.Label(row1, text="Studente:").pack(side="left", padx=(0, 6))
        self.ent_student = ttk.Entry(row1, width=22)
        self.ent_student.insert(0, self.settings.student_name)
        self.ent_student.pack(side="left", padx=(0, 24))

        ttk.Label(row1, text="Modello:").pack(side="left", padx=(0, 6))
        selected_model = self.settings.model if self.settings.model in MODELS else DEFAULT_MODEL
        model_values = GUI_MODELS + ([selected_model] if selected_model not in GUI_MODELS else [])
        self.cmb_model = ttk.Combobox(row1, values=model_values, width=20, state="readonly")
        self.cmb_model.set(selected_model)
        self.cmb_model.pack(side="left")

        # Riga 1b: Tipo di analisi + Rielabora
        row_mode = ttk.Frame(config_frame)
        row_mode.pack(fill="x", pady=(0, 6))
        ttk.Label(row_mode, text="Tipo di analisi:").pack(side="left", padx=(0, 6))
        self.var_mode = tk.StringVar(value=self.settings.analysis_mode)
        ttk.Radiobutton(row_mode, text="Base (1 chiamata)", value="base", variable=self.var_mode).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(row_mode, text="Avanzata (a spezzoni)", value="avanzata", variable=self.var_mode).pack(side="left", padx=(0, 4))
        ttk.Button(row_mode, text="?", width=3, command=self._show_analysis_help).pack(side="left", padx=(0, 20))
        self.var_force = tk.BooleanVar(value=False)
        ttk.Checkbutton(row_mode, text="Rielabora anche se già analizzata", variable=self.var_force).pack(side="left")

        # Riga 2: Cartella Report + Pulsante Cambia
        row2 = ttk.Frame(config_frame)
        row2.pack(fill="x", pady=(0, 6))

        ttk.Label(row2, text="Cartella dei report:").pack(side="left", padx=(0, 6))
        self.var_output_dir = tk.StringVar(value=self.settings.output_dir or "Nessuna cartella selezionata")
        self.ent_output_dir = ttk.Entry(row2, textvariable=self.var_output_dir, state="readonly")
        self.ent_output_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_change_dir = ttk.Button(row2, text="Cambia…", command=self._change_output_dir)
        btn_change_dir.pack(side="right")

        # Riga 3: Chiave API Gemini + Pulsante Gestione
        row3 = ttk.Frame(config_frame)
        row3.pack(fill="x")

        ttk.Label(row3, text="Chiave Gemini:").pack(side="left", padx=(0, 6))
        self.lbl_api_status = ttk.Label(row3, text="verifica in corso…", font=("Segoe UI", 9, "italic"))
        self.lbl_api_status.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_api_dialog = ttk.Button(row3, text="Chiave API…", command=self._open_api_key_dialog)
        btn_api_dialog.pack(side="right")

        # 3. FILE QUEUE SECTION
        queue_frame = ttk.LabelFrame(main_container, text=" Lezioni da analizzare ", padding=10)
        queue_frame.pack(fill="both", expand=True, pady=(0, 10))

        # Bottoni Gestione File
        btn_box = ttk.Frame(queue_frame)
        btn_box.pack(fill="x", pady=(0, 8))

        btn_add = ttk.Button(btn_box, text="Aggiungi registrazioni…", command=self._add_audio_files)
        btn_add.pack(side="left", padx=(0, 6))

        btn_remove = ttk.Button(btn_box, text="Rimuovi selezionata", command=self._remove_selected_file)
        btn_remove.pack(side="left", padx=(0, 6))

        btn_clear = ttk.Button(btn_box, text="Svuota elenco", command=self._clear_queue)
        btn_clear.pack(side="left")

        # Treeview per lista file
        tree_scroll = ttk.Scrollbar(queue_frame)
        tree_scroll.pack(side="right", fill="y")

        self.tree = ttk.Treeview(
            queue_frame,
            columns=("num", "filename", "size", "status"),
            show="headings",
            yscrollcommand=tree_scroll.set,
            height=4,
        )
        tree_scroll.config(command=self.tree.yview)

        self.tree.heading("num", text="#")
        self.tree.heading("filename", text="Registrazione")
        self.tree.heading("size", text="Dimensione")
        self.tree.heading("status", text="Stato")

        self.tree.column("num", width=40, anchor="center")
        self.tree.column("filename", width=400, anchor="w")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("status", width=180, anchor="center")

        self.tree.pack(fill="both", expand=True)

        # 4. PROGRESS & STATUS SECTION
        progress_frame = ttk.LabelFrame(main_container, text=" Avanzamento ", padding=10)
        progress_frame.pack(fill="x", pady=(0, 10))

        self.lbl_percentage = ttk.Label(progress_frame, text="Nessuna lezione in corso", font=("Segoe UI", 9, "bold"))
        self.lbl_percentage.pack(anchor="w", pady=(0, 4))

        self.progressbar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
        self.progressbar.pack(fill="x", pady=(0, 6))

        self.lbl_status = ttk.Label(progress_frame, text="Aggiungi le registrazioni e premi Analizza le lezioni.", foreground="#64748b")
        self.lbl_status.pack(anchor="w")

        # 5. LOG CONSOLE SECTION
        log_frame = ttk.LabelFrame(main_container, text=" Dettagli ", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=6,
            font=("Consolas", 9),
            bg="#1F2A44",
            fg="#E9EDF3",
            insertbackground="white",
        )
        self.log_text.pack(fill="both", expand=True)

        # 6. ACTION CONTROLS SECTION (ctl_frame posizionato correttamente prima dei bottoni)
        ctl_frame = ttk.Frame(main_container)
        # ancorato in basso: resta visibile anche se la finestra è bassa
        ctl_frame.pack(fill="x", pady=(8, 0), side="bottom", before=config_frame)

        self.btn_start = ttk.Button(
            ctl_frame,
            text="Analizza le lezioni",
            style="Primary.TButton",
            command=self._start_batch_processing,
        )
        self.btn_start.pack(side="left", padx=(0, 8), ipadx=10, ipady=4)

        self.btn_audio = ttk.Button(
            ctl_frame,
            text="Crea l'Audio Review",
            style="Secondary.TButton",
            command=self._start_audio_review_processing,
        )
        self.btn_audio.pack(side="left", padx=(0, 8), ipadx=10, ipady=4)

        self.btn_stop = ttk.Button(
            ctl_frame,
            text="Interrompi",
            state="disabled",
            command=self._stop_batch_processing,
        )
        self.btn_stop.pack(side="left", padx=(0, 8), ipady=4)

        btn_open_report = ttk.Button(ctl_frame, text="Apri la cartella dei report", command=self._open_reports_dir)
        btn_open_report.pack(side="right", ipady=4)

    # -------------------------------------------------------------
    # GESTIONE IMPOSTAZIONI & CHIAVE API
    # -------------------------------------------------------------
    def _refresh_api_key_status(self):
        """Aggiorna l'etichetta dello stato della chiave API."""
        key, source = get_api_key()
        if not key:
            self.lbl_api_status.config(text="non configurata", foreground="#dc2626")
        elif source == "keyring":
            self.lbl_api_status.config(text="configurata — Gestione credenziali Windows", foreground="#16a34a")
        elif source == "dotenv":
            self.lbl_api_status.config(text="configurata — file .env", foreground="#2563eb")
        elif source == "env":
            self.lbl_api_status.config(text="configurata — variabile d'ambiente", foreground="#2563eb")
        else:
            self.lbl_api_status.config(text="configurata", foreground="#16a34a")

    def _show_analysis_help(self):
        messagebox.showinfo("Tipo di analisi", ANALYSIS_HELP_TEXT, parent=self.root)

    def _change_output_dir(self):
        initial = self.settings.output_dir if os.path.isdir(self.settings.output_dir) else None
        chosen = filedialog.askdirectory(title="Seleziona la Cartella Report delle Lezioni", initialdir=initial)
        if chosen:
            self.settings.output_dir = os.path.normpath(chosen)
            self.var_output_dir.set(self.settings.output_dir)
            save_settings(self.settings)

    def _open_api_key_dialog(self):
        """Apre il dialogo modale per la gestione della chiave API Gemini."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Configurazione Chiave API Gemini")
        dlg.geometry("520x240")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        pad_f = ttk.Frame(dlg, padding=16)
        pad_f.pack(fill="both", expand=True)

        ttk.Label(
            pad_f,
            text="Inserisci la tua chiave API Google Gemini:",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        # Campo chiave con mascheramento
        ent_key = ttk.Entry(pad_f, width=54, show="*")
        ent_key.pack(fill="x", pady=(0, 4))

        # Checkbox mostra/nascondi
        show_var = tk.BooleanVar(value=False)

        def toggle_show():
            ent_key.config(show="" if show_var.get() else "*")

        chk_show = ttk.Checkbutton(pad_f, text="Mostra caratteri", variable=show_var, command=toggle_show)
        chk_show.pack(anchor="w", pady=(0, 8))

        # Link AI Studio
        link_lbl = tk.Label(
            pad_f,
            text="Non hai una chiave? Creala gratuitamente su Google AI Studio ↗",
            fg="#2563eb",
            cursor="hand2",
            font=("Segoe UI", 8, "underline"),
        )
        link_lbl.pack(anchor="w", pady=(0, 6))
        link_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://aistudio.google.com/apikey"))

        # Nota di precedenza
        note_lbl = ttk.Label(
            pad_f,
            text="Nota: una chiave presente in variabile d'ambiente o nel file .env ha la precedenza.",
            font=("Segoe UI", 8),
            foreground="#64748b",
        )
        note_lbl.pack(anchor="w", pady=(0, 12))

        # Pulsanti Salva / Rimuovi / Annulla
        btn_row = ttk.Frame(pad_f)
        btn_row.pack(fill="x", side="bottom")

        def on_save():
            new_key = ent_key.get().strip()
            if not new_key:
                messagebox.showerror("Errore", "La chiave non puo essere vuota.", parent=dlg)
                return
            if " " in new_key:
                messagebox.showerror("Errore", "La chiave non puo contenere spazi.", parent=dlg)
                return
            if len(new_key) < 20:
                messagebox.showerror("Errore", "La chiave inserita sembra troppo corta.", parent=dlg)
                return

            try:
                save_api_key(new_key)
                self._refresh_api_key_status()
                dlg.destroy()
                messagebox.showinfo(
                    "Chiave Salvata",
                    "Chiave API salvata con successo nella Gestione credenziali di Windows.",
                    parent=self.root,
                )
            except Exception as e:
                messagebox.showerror("Errore Salvataggio", f"Impossibile salvare la chiave: {e}", parent=dlg)

        def on_remove():
            if messagebox.askyesno("Conferma Rimozione", "Vuoi rimuovere la chiave salvata dalla Gestione credenziali?", parent=dlg):
                delete_api_key()
                self._refresh_api_key_status()
                dlg.destroy()

        btn_save = ttk.Button(btn_row, text="Salva", style="Primary.TButton", command=on_save)
        btn_save.pack(side="left", padx=(0, 6))

        btn_delete = ttk.Button(btn_row, text="Rimuovi", command=on_remove)
        btn_delete.pack(side="left", padx=(0, 6))

        btn_cancel = ttk.Button(btn_row, text="Annulla", command=dlg.destroy)
        btn_cancel.pack(side="right")

        dlg.focus_set()
        ent_key.focus_set()
        self.root.wait_window(dlg)

    def run_first_launch_checks(self):
        """Esegue i controlli al primo avvio in modo non bloccante dopo che la finestra e visibile."""
        # 1. Controllo cartella output
        if not self.settings.output_dir or not os.path.isdir(self.settings.output_dir):
            messagebox.showinfo(
                "Configurazione Cartella Report",
                "Benvenuto in English Assessment Engine!\n\n"
                "Seleziona la cartella del tuo computer in cui desideri salvare tutti i report delle lezioni.",
                parent=self.root,
            )
            chosen = filedialog.askdirectory(title="Seleziona la Cartella Report Principale")
            if chosen:
                self.settings.output_dir = os.path.normpath(chosen)
                self.var_output_dir.set(self.settings.output_dir)
                save_settings(self.settings)

        # 2. Controllo chiave API
        key, _ = get_api_key()
        if not key:
            self._open_api_key_dialog()

    # -------------------------------------------------------------
    # EVENT HANDLERS & GESTIONE CODA FILE
    # -------------------------------------------------------------
    def _add_audio_files(self):
        files = filedialog.askopenfilenames(
            title="Seleziona File Audio Lezioni",
            filetypes=[
                ("File Audio/Video", "*.m4a *.mp3 *.mp4 *.wav *.aac *.ogg *.flac"),
                ("Tutti i file", "*.*"),
            ],
        )
        if files:
            for f in files:
                norm_f = os.path.normpath(f)
                if norm_f not in self.audio_files:
                    self.audio_files.append(norm_f)
            self._update_treeview()

    def _remove_selected_file(self):
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(self.tree.item(selected[0])["values"][0]) - 1
        if 0 <= idx < len(self.audio_files):
            del self.audio_files[idx]
            self._update_treeview()

    def _clear_queue(self):
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Attenzione", "Impossibile svuotare la coda durante l'elaborazione.")
            return
        self.audio_files.clear()
        self._update_treeview()

    def _update_treeview(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, filepath in enumerate(self.audio_files, start=1):
            filename = os.path.basename(filepath)
            size_mb = f"{os.path.getsize(filepath) / (1024 * 1024):.1f} MB" if os.path.exists(filepath) else "N/D"
            self.tree.insert("", "end", iid=str(i), values=(i, filename, size_mb, "In attesa"))

        total = len(self.audio_files)
        self.lbl_percentage.config(text=f"0 di {total} lezioni completate")
        self.progressbar["value"] = 0

    def _log(self, message: str):
        self.log_queue.put(message)

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
        self.root.after(100, self._process_log_queue)

    def _open_reports_dir(self):
        target = self.settings.output_dir
        if not target or not os.path.isdir(target):
            messagebox.showwarning("Cartella Non Trovata", "Nessuna cartella report valida configurata.")
            return

        abs_path = os.path.abspath(target)
        if sys.platform == "win32":
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(["open", abs_path])
        else:
            import subprocess

            subprocess.run(["xdg-open", abs_path])

    def _validate_before_start(self) -> Optional[tuple[str, str, str, str]]:
        """Verifica nome studente, cartella output e chiave API prima di iniziare."""
        if not self.audio_files:
            messagebox.showwarning("Coda Vuota", "Aggiungi almeno un file audio prima di avviare.")
            return None

        student_name = self.ent_student.get().strip()
        if not student_name:
            messagebox.showerror("Campo Mancante", "Inserisci il nome dello studente.")
            return None

        # Verifica e convalida cartella output
        output_dir = self.settings.output_dir
        if not output_dir:
            self._change_output_dir()
            output_dir = self.settings.output_dir

        if not output_dir:
            messagebox.showerror("Cartella Mancante", "E necessario selezionare una cartella report di destinazione.")
            return None

        try:
            os.makedirs(output_dir, exist_ok=True)
            # Test di scrittura
            test_path = Path(output_dir) / f".test_write_{os.getpid()}"
            test_path.write_text("test", encoding="utf-8")
            test_path.unlink()
        except Exception as e:
            messagebox.showerror("Cartella Non Scrivibile", f"Impossibile scrivere nella cartella selezionata:\n{e}\n\nSeleziona una cartella differente.")
            self._change_output_dir()
            return None

        # Controllo chiave API
        api_key, _ = get_api_key()
        if not api_key:
            messagebox.showwarning(
                "Chiave API Mancante",
                "E necessaria una chiave API Gemini per elaborare nuove lezioni.\nInserisci la tua chiave nel prossimo dialogo.",
            )
            self._open_api_key_dialog()
            api_key, _ = get_api_key()
            if not api_key:
                return None

        # Aggiorna e salva impostazioni
        model = self.cmb_model.get().strip() or DEFAULT_MODEL
        self.settings.student_name = student_name
        self.settings.model = model
        self.settings.analysis_mode = self.var_mode.get()
        save_settings(self.settings)
        self._run_mode, self._run_force = self.var_mode.get(), bool(self.var_force.get())

        return student_name, output_dir, model, api_key

    # -------------------------------------------------------------
    # WORKER BATCH & THREAD
    # -------------------------------------------------------------
    def _start_batch_processing(self):
        validated = self._validate_before_start()
        if not validated:
            return
        student_name, output_dir, model, api_key = validated

        self.stop_requested = False
        self.btn_start.config(state="disabled")
        self.btn_audio.config(state="disabled")
        self.btn_stop.config(state="normal")

        self.processing_thread = threading.Thread(
            target=self._run_batch_worker,
            args=(list(self.audio_files), student_name, model, output_dir, api_key),
            daemon=True,
        )
        self.processing_thread.start()

    def _start_audio_review_processing(self):
        validated = self._validate_before_start()
        if not validated:
            return
        student_name, output_dir, model, api_key = validated

        self.stop_requested = False
        self.btn_start.config(state="disabled")
        self.btn_audio.config(state="disabled")
        self.btn_stop.config(state="normal")

        self.processing_thread = threading.Thread(
            target=self._run_audio_worker,
            args=(list(self.audio_files), student_name, model, output_dir, api_key),
            daemon=True,
        )
        self.processing_thread.start()

    def _stop_batch_processing(self):
        if messagebox.askyesno(
            "Conferma Interruzione",
            "Vuoi davvero interrompere la coda?\nLe lezioni gia completate rimarranno salvate.",
        ):
            self.stop_requested = True
            self._log("\n[AVVISO] Richiesta di interruzione inoltrata. L'elaborazione si fermera al termine della lezione corrente.")

    def _update_tree_status(self, idx_1based: int, status_str: str):
        def update():
            try:
                self.tree.set(str(idx_1based), "status", status_str)
            except Exception:
                pass

        self.root.after(0, update)

    def _update_progress(self, current: int, total: int, status_msg: str):
        def update():
            pct = int((current / total) * 100) if total > 0 else 0
            self.progressbar["value"] = pct
            self.lbl_percentage.config(text=f"{current} di {total} lezioni completate ({pct}%)")
            self.lbl_status.config(text=status_msg)

        self.root.after(0, update)

    def _run_batch_worker(
        self,
        audio_list: List[str],
        student_name: str,
        model_name: str,
        output_dir: str,
        api_key: str,
    ):
        from generate_report import process_single_audio

        total = len(audio_list)
        self._log(f"\n============================================================")
        self._log(f"  AVVIO ELABORAZIONE BATCH DA {total} LEZIONI")
        self._log(f"  Studente: {student_name} | Modello: {model_name} | Analisi: {self._run_mode}"
                  f"{' | rielaborazione forzata' if self._run_force else ''}")
        self._log(f"  Cartella Output: {output_dir}")
        self._log(f"============================================================\n")

        success_count = 0

        for i, original_audio_path in enumerate(audio_list, start=1):
            if self.stop_requested:
                self._log("\n[INTERRUZIONE] Coda bloccata dall'utente.")
                break

            filename = os.path.basename(original_audio_path)
            self._update_tree_status(i, "In corso")
            self._update_progress(i - 1, total, f"Elaborazione lezione {i} di {total}: '{filename}'...")
            self._log(f"\n---> [{i}/{total}] Inizio lezione: {filename}")

            try:
                lesson_dir = process_single_audio(
                    audio_path=original_audio_path,
                    student_name=student_name,
                    model_name=model_name,
                    output_dir=output_dir,
                    api_key=api_key,
                    log=self._log,
                    mode=self._run_mode,
                    force=self._run_force,
                    progress=lambda step, row=i: self._update_tree_status(row, step),
                )
                self._update_tree_status(i, "Completata")
                self._log(f"  [CHECKPOINT SUCCESS] Lezione salvata in: {lesson_dir}")
                success_count += 1
            except Exception as e:
                self._update_tree_status(i, "Errore: vedi Dettagli")
                self._log(f"  [ERRORE LEZIONE {i}] {e}")

            self._update_progress(i, total, f"Completata lezione {i} di {total}.")

        self._log(f"\n============================================================")
        self._log(f"  ELABORAZIONE BATCH TERMINATA: {success_count}/{total} lezioni completate.")
        self._log(f"============================================================\n")

        def finish_ui():
            self.btn_start.config(state="normal")
            self.btn_audio.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.lbl_status.config(text=f"Batch completato. {success_count}/{total} lezioni elaborate.")
            messagebox.showinfo(
                "Elaborazione Completata",
                f"Elaborazione batch terminata!\n{success_count} su {total} lezioni elaborate con successo.",
                parent=self.root,
            )

        self.root.after(0, finish_ui)

    def _run_audio_worker(
        self,
        audio_list: List[str],
        student_name: str,
        model_name: str,
        output_dir: str,
        api_key: str,
    ):
        from generate_report import process_single_audio_review

        total = len(audio_list)
        self._log(f"\n============================================================")
        self._log(f"  AVVIO GENERAZIONE AUDIO REVIEW DIDATTICO DA {total} LEZIONI")
        self._log(f"  Studente: {student_name} | Voci: Cambridge RP (Sonia & Ryan)")
        self._log(f"============================================================\n")

        success_count = 0

        for i, original_audio_path in enumerate(audio_list, start=1):
            if self.stop_requested:
                self._log("\n[INTERRUZIONE] Coda bloccata dall'utente.")
                break

            filename = os.path.basename(original_audio_path)
            self._update_tree_status(i, "Audio Review in corso")
            self._update_progress(i - 1, total, f"Sintesi audio review {i} di {total}: '{filename}'...")
            self._log(f"\n---> [{i}/{total}] Inizio Audio Review: {filename}")

            try:
                mp3_path = process_single_audio_review(
                    audio_path=original_audio_path,
                    student_name=student_name,
                    model_name=model_name,
                    output_dir=output_dir,
                    api_key=api_key,
                    log=self._log,
                    stop_check=lambda: self.stop_requested,
                    mode=self._run_mode,
                    progress=lambda step, row=i: self._update_tree_status(row, step),
                )
                if mp3_path:
                    self._update_tree_status(i, "Audio Review pronta")
                    self._log(f"  [AUDIO REVIEW SUCCESS] Traccia salvata: {mp3_path}")
                    success_count += 1
                else:
                    self._update_tree_status(i, "Nessun errore da ripassare")
            except Exception as e:
                self._update_tree_status(i, "Errore: vedi Dettagli")
                self._log(f"  [ERRORE AUDIO REVIEW {i}] {e}")

            self._update_progress(i, total, f"Completata lezione {i} di {total}.")

        self._log(f"\n============================================================")
        self._log(f"  SESSIONE AUDIO REVIEW TERMINATA: {success_count}/{total} tracce generate.")
        self._log(f"============================================================\n")

        def finish_audio_ui():
            self.btn_start.config(state="normal")
            self.btn_audio.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.lbl_status.config(text=f"Audio Review completato. {success_count}/{total} tracce generate.")
            messagebox.showinfo(
                "Audio Review Completato",
                f"Generazione Audio Review terminata!\n{success_count} su {total} tracce create.",
                parent=self.root,
            )

        self.root.after(0, finish_audio_ui)


def launch_gui():
    root = tk.Tk()
    app = AssessmentEngineGUI(root)
    root.after(100, app.run_first_launch_checks)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
