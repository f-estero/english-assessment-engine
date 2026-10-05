"""
generate_report.py — Pipeline di analisi multimodale, CLI e punto di ingresso.

Gestisce:
1. Chiamate a Gemini con retry esponenziale, rotazione modelli e gestione errori
2. Analisi audio multimodale unificata
3. Creazione ed esportazione report HTML, PDF, JSON e CSV
4. Tracciamento longitudinale e Audio Review didattico
5. CLI flessibile o avvio GUI se eseguito senza argomenti
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import warnings
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Soppressione avvisi SDK Google e logger per output pulito
os.environ["GLOG_minloglevel"] = "3"
os.environ["PYTHONWARNINGS"] = "ignore"
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

# Configurazione Encoding UTF-8 per console Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app_config import enable_system_certificates

enable_system_certificates()

from jinja2 import Environment, FileSystemLoader, select_autoescape
from google import genai
from google.genai import types

from schema import AssessmentReport
from validator import validate_and_filter_report
from app_config import (
    APP_NAME,
    MODELS,
    DEFAULT_MODEL,
    resource_path,
    load_settings,
    get_api_key,
)
from lesson_paths import (
    lesson_date,
    format_date_it,
    resolve_lesson_dir,
)
from session_store import upsert_session, get_session_summary
from export_study import export_csv
from report_format import correction_diff, num, signed, timeline
import chunking
from chunking import AudioChunk
from merge import assemble_report, build_synthesis_input, fmt_mmss, merge_chunks, select_for_display
from schema import ChunkAnalysis, SynthesisOutput

# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """
Sei un Cambridge Senior Language Assessor con vasta esperienza nella valutazione CEFR (A1-C2) di parlanti italiano L1.
Ascolta il file audio completo in modalità multimodale.

COSA PUOI FARE (e devi fare in modo ESAUSTIVO ed APPROFONDITO):
- Identificare in modo capillare gli errori grammaticali, lessicali e di pronuncia dello studente lungo TUTTA la durata della registrazione.
- Estrarre un campionamento ricco, denso ed esaustivo dei problemi linguistici dell'allievo (non fermarti a 3-4 frasi!).
- Valutare qualitativamente la prosodia: pattern di intonazione, ritmo del parlato (syllable-timed vs stress-timed), pause piene ed esitazioni.
- Distinguere rigorosamente la voce dello studente da quella dell'insegnante (analizza e cita SOLO lo studente).
- Fornire citazioni testuali esatte di ciò che lo studente ha detto, accompagnate da timestamp approssimativi [MM:SS].
- Suggerire correzioni Cambridge standard B1/B2, regole mnemoniche e drill fonetici pratici.

DENSITÀ E COPERTURA TEMPORALE RICHIESTA:
- Per una lezione di 30-60 minuti, ti viene richiesto un report CAPILLARE e RICCO:
  - grammar_table: almeno 10 - 18 citazioni di errori morfosintattici distribuiti lungo l'intera lezione.
  - phonetics_table: almeno 8 - 15 termini pronunciati con difetti articolatori, vocali neutralizzate o accenti spostati.
  - lexical_table: almeno 5 - 10 calchi dall'italiano, false friends o errori di registro.
  - critical_matrix: 4 - 6 regole cardine prioritarie con collegamenti agli ID delle voci.
  - protocol_notes: 5 - 8 note formative pratiche ed operative.

COSA NON PUOI FARE (e non devi fingere):
- NON puoi misurare Hz, formanti, f₀ o pressione sonora. Le tue osservazioni su pitch e intonazione sono PERCETTIVE, non strumentali.
- NON inventare frasi mai dette. Le citazioni devono riflettere parole réellement pronunciate dallo studente.

REGOLA ANTI-ALLUCINAZIONE E DI PRECISIONE:
- Assegna un livello di confidenza reale (0.0 - 1.0) a ciascuna voce basato sulla tua certezza di ascolto.
- Se non sei sicuro che una frase sia stata detta dallo studente (e non dall'insegnante), scartala.
"""

ANALYSIS_PROMPT = (
    "Ascolta attentamente ed integralmente la sessione audio COMPLETA dall'inizio alla fine (da 00:00 al termine della registrazione). "
    "Non limitarti ai primi minuti della registrazione: effettua una scansione esaustiva ed analitica dell'intera lezione. "
    "Estrai un campionamento ampio, ricco e dettagliato di tutti i problemi linguistici dell'allievo:\n"
    "1. Errori morfosintattici (almeno 10-18 voci in grammar_table), indicando citazione esatta dello studente e timestamp approssimativo [MM:SS].\n"
    "2. Imprecisioni fonetiche e accentuazione (almeno 8-15 voci in phonetics_table), con IPA percepito e drill pratico.\n"
    "3. Calchi lessicali e false friends dall'italiano (almeno 5-10 voci in lexical_table).\n"
    "Fornisci una valutazione qualitativa approfondita della prosodia, del ritmo e del tono di voce.\n"
    "Compila la diagnosi rispettando rigorosamente lo schema JSON."
)


_KEY_ERROR_MARKERS = ("API_KEY_INVALID", "API KEY NOT VALID", "PERMISSION_DENIED", "UNAUTHENTICATED", "401")


def _key_error(e: Exception) -> Optional[ValueError]:
    """Traduce un rifiuto delle credenziali in un messaggio comprensibile, altrimenti None."""
    if any(m in str(e).upper() for m in _KEY_ERROR_MARKERS):
        return ValueError("Chiave API Gemini non valida o senza permessi: aggiornala dal pulsante 'Chiave API…'")
    return None


def call_gemini_with_retry(
    client: genai.Client,
    model: str,
    contents: list,
    system_prompt: str,
    log: Callable[[str], None] = print,
    max_retries: int = 4,
    schema: type = AssessmentReport,
):
    """Esegue la chiamata a Gemini con gestione di errori transitori, invalid key e rotazione modelli."""
    models_to_try = [model]
    for m in MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    last_error: Optional[Exception] = None

    for current_model in models_to_try:
        if current_model != model:
            log(f"     [FALLBACK] Passaggio al modello alternativo: {current_model}...")

        model_not_found = False
        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.2,
                    ),
                )
                return response
            except Exception as e:
                err_str = str(e)
                last_error = e

                # Controllo chiave non valida
                err_upper = err_str.upper()
                key_error = _key_error(e)
                if key_error:
                    raise key_error from e

                # Controllo modello inesistente / deprecato
                if "404" in err_str or "NOT_FOUND" in err_upper:
                    log(f"     [AVVISO] Modello '{current_model}' non trovato su Google Cloud (404/NOT_FOUND).")
                    model_not_found = True
                    break

                # Controllo errori transitori / sovraccarico
                if (
                    "503" in err_str
                    or "UNAVAILABLE" in err_upper
                    or "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_upper
                    or "high demand" in err_str.lower()
                ):
                    wait_time = attempt * 6
                    log(f"     [AVVISO Server Occupato] Server Google occupato (tentativo {attempt}/{max_retries}). Attesa di {wait_time} secondi...")
                    time.sleep(wait_time)
                else:
                    # Errore non recuperabile
                    raise e

        if model_not_found:
            continue

        log(f"     [AVVISO] Modello '{current_model}' non disponibile dopo {max_retries} tentativi.")

    if last_error:
        raise last_error
    raise RuntimeError("Chiamata a Gemini fallita con tutti i modelli configurati.")


CHUNK_SYSTEM_PROMPT = """
Sei un valutatore esperto di inglese parlato da italofoni (L1 italiano), livelli CEFR A1-C2.
Ricevi UNO SPEZZONE audio di una lezione di conversazione tra uno studente (italiano) e un insegnante.
Elenca in modo esaustivo gli errori del SOLO STUDENTE presenti in questo spezzone, rispettando lo schema JSON.
Regole:
1. Cita solo parole effettivamente pronunciate dallo studente; se non sei certo che sia lo studente, scarta la voce.
2. timestamp_derived (per OGNI voce di ogni tabella) = MM:SS RELATIVO ALL'INIZIO DI QUESTO SPEZZONE (00:00 = inizio spezzone).
3. Correzione minima: cambia solo ciò che è sbagliato.
4. llm_confidence = certezza reale (0-1) che la voce sia dello studente e sia davvero un errore.
5. Copri TUTTO lo spezzone, dall'inizio alla fine, non solo i primi minuti.
6. Le osservazioni su prosodia e pronuncia sono percettive, non misurazioni.
"""

SYNTHESIS_SYSTEM_PROMPT = """
Sei un Senior Language Assessor esperto di valutazione CEFR di parlanti italiano L1.
NON ricevi audio: ricevi in JSON tutte le voci di errore già estratte da una lezione (con id e minuto)
e le note percettive di ciascuno spezzone.
Compila la valutazione complessiva rispettando lo schema JSON:
- punteggi su 10 e motivazioni fattuali che citano gli id delle voci (es. gram_3, phon_2);
- critical_matrix: 4-6 regole cardine; nei refs usa SOLO id presenti nell'input;
- protocol_notes: 5-8 note formative operative;
- prosody_and_tone: sintesi delle note percettive degli spezzoni.
Non inventare citazioni, esempi o voci che non sono nell'input. Scrivi in italiano.
"""

MAX_PARALLEL_CHUNKS = 3


def _upload_chunk(client, chunk: AudioChunk, log: Callable[[str], None]):
    """Carica uno spezzone (bytes in memoria) e attende che sia pronto."""
    try:
        f = client.files.upload(
            file=io.BytesIO(chunk.data),
            config=types.UploadFileConfig(mime_type=chunk.mime, display_name=f"spezzone_{chunk.index:02d}"),
        )
    except Exception as e:
        key_error = _key_error(e)
        if key_error:
            raise key_error from e
        raise
    while f.state.name == "PROCESSING":
        time.sleep(2)
        f = client.files.get(name=f.name)
    if f.state.name == "FAILED":
        raise ValueError(f"Elaborazione remota fallita per lo spezzone {chunk.index}.")
    return f


def _delete_remote(client, f, log: Callable[[str], None]) -> None:
    try:
        client.files.delete(name=f.name)
    except Exception as e:
        log(f"  [AVVISO] Cancellazione file remoto non riuscita: {e}")


def _analyze_base(client, audio_path: Path, model: str, log, transcript_data, transcript_source) -> AssessmentReport:
    """Modalità Base: tutta la registrazione in una sola chiamata."""
    chunk = chunking.whole_audio(audio_path)
    log(f"  Upload audio su Google Cloud ({model}): {audio_path.name}...")
    f = _upload_chunk(client, chunk, log)
    try:
        contents: list = [f, ANALYSIS_PROMPT]
        if transcript_data:
            contents.append(
                f"Trascrizione di SUPPORTO (fonte: {transcript_source}). "
                f"Usala come guida per i contenuti, ma fidati del tuo ascolto diretto per la fonetica:\n"
                f"{json.dumps(transcript_data[:80], ensure_ascii=False)}"
            )
        log(f"  Analisi diagnostica (Base, chiamata unica) con {model}...")
        response = call_gemini_with_retry(client=client, model=model, contents=contents,
                                          system_prompt=SYSTEM_PROMPT, log=log)
    finally:
        _delete_remote(client, f, log)
    report = AssessmentReport.model_validate_json(response.text)
    secs = int(round(chunk.end))
    report.audio_sample_duration = f"{secs // 60}m {secs % 60:02d}s"
    report.analysis_mode, report.n_chunks = "base", None
    return report


def _chunk_prompt(chunk: AudioChunk) -> str:
    return (f"Spezzone {chunk.index} di {chunk.n_chunks}: minuti "
            f"{fmt_mmss(chunk.start)}-{fmt_mmss(chunk.end)} della lezione. "
            "Elenca: 8-12 errori morfosintattici (grammar_table), 5-8 imprecisioni fonetiche (phonetics_table), "
            "3-6 calchi lessicali (lexical_table), distribuiti su tutto lo spezzone.")


def _analyze_advanced(client, audio_path: Path, model: str, log, progress) -> AssessmentReport:
    """Modalità Avanzata: spezzoni in parallelo, unione, sintesi finale solo testo."""
    chunks = chunking.make_chunks(audio_path, chunking.CHUNK_SECONDS, chunking.OVERLAP_SECONDS,
                                  chunking.MIN_LAST_SECONDS)
    duration = chunks[-1].end
    log(f"  Audio di {duration / 60:.1f} min diviso in {len(chunks)} spezzoni (analisi Avanzata, {model}).")

    def one(chunk: AudioChunk):
        f = _upload_chunk(client, chunk, log)
        try:
            r = call_gemini_with_retry(client=client, model=model, contents=[f, _chunk_prompt(chunk)],
                                       system_prompt=CHUNK_SYSTEM_PROMPT, log=log, schema=ChunkAnalysis)
        finally:
            _delete_remote(client, f, log)
        analysis = ChunkAnalysis.model_validate_json(r.text)
        log(f"  [Spezzone {chunk.index}/{len(chunks)}] {len(analysis.grammar_table)} gram, "
            f"{len(analysis.phonetics_table)} phon, {len(analysis.lexical_table)} lex")
        return chunk, analysis

    results, done = [], 0
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHUNKS) as ex:
        futures = [ex.submit(one, c) for c in chunks]
        try:
            for fut in as_completed(futures):
                results.append(fut.result())   # uno spezzone fallito fa fallire la lezione
                done += 1
                if progress:
                    progress(f"Spezzone {done}/{len(chunks)}")
        except Exception:
            for fut in futures:
                fut.cancel()
            raise

    grammar, phonetics, lexical, notes = merge_chunks(results)
    log(f"  Voci dopo l'unione: {len(grammar)} gram, {len(phonetics)} phon, {len(lexical)} lex. Sintesi finale...")
    if progress:
        progress("Sintesi")
    r = call_gemini_with_retry(client=client, model=model,
                               contents=[build_synthesis_input(grammar, phonetics, lexical, notes, duration)],
                               system_prompt=SYNTHESIS_SYSTEM_PROMPT, log=log, schema=SynthesisOutput)
    return assemble_report(grammar, phonetics, lexical, SynthesisOutput.model_validate_json(r.text),
                           duration, len(chunks))


def analyze_audio(
    audio_path: Path | str,
    api_key: str,
    model: str,
    student_name: str,
    log: Callable[[str], None] = print,
    mode: str = "base",
    transcript_data: Optional[List] = None,
    transcript_source: str = "llm",
    progress: Optional[Callable[[str], None]] = None,
) -> AssessmentReport:
    """Analizza una lezione in modalità 'base' (chiamata unica) o 'avanzata' (spezzoni + sintesi)
    e applica la validazione deterministica."""
    client = genai.Client(api_key=api_key)
    path = Path(audio_path)
    if mode == "avanzata":
        raw = _analyze_advanced(client, path, model, log, progress)
    else:
        raw = _analyze_base(client, path, model, log, transcript_data, transcript_source)
    raw.student_name = student_name

    log(f"  Validazione deterministica (transcript_source={transcript_source})...")
    validated = validate_and_filter_report(raw, transcript_data or [], transcript_source=transcript_source)
    if validated.validation_stats:
        vs = validated.validation_stats
        log(f"  [Validazione] Proposte: {vs.total_proposed} | Validate: {vs.total_validated} | Scartate: {vs.total_discarded}")
    return validated


def load_report(json_path: Path | str) -> Optional[AssessmentReport]:
    """Carica un AssessmentReport da file JSON se esistente e valido, altrimenti None."""
    p = Path(json_path)
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        return AssessmentReport.model_validate(raw_data)
    except Exception:
        return None


def _render_pdf(html_output_path: Path, pdf_output_path: Path, rendered_html: str,
                log: Callable[[str], None]) -> bool:
    """Genera il PDF con Edge headless, in alternativa WeasyPrint. Restituisce True se riuscito."""
    pdf_generated = False

    # Un PDF di un rendering precedente non deve sembrare appena generato
    try:
        pdf_output_path.unlink(missing_ok=True)
    except OSError as e:
        log(f"  [AVVISO] Impossibile sostituire il PDF esistente (forse e aperto): {e}")

    # 1. Tentativo con Microsoft Edge headless
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_bin = next((p for p in edge_paths if os.path.exists(p)), None)
    if not edge_bin:
        edge_bin = shutil.which("msedge")

    if edge_bin:
        try:
            abs_html_uri = html_output_path.resolve().as_uri()
            abs_pdf = str(pdf_output_path.resolve())
            cmd = [
                edge_bin,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--prefer-css-page-size",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=5000",
                f"--print-to-pdf={abs_pdf}",
                abs_html_uri,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if pdf_output_path.is_file() and pdf_output_path.stat().st_size > 0:
                pdf_generated = True
                log(f"  Report PDF (Edge): {pdf_output_path.resolve()}")
        except Exception as e:
            log(f"  [AVVISO] Errore esecuzione Edge per PDF: {e}")

    # 2. Fallback WeasyPrint se disponibile
    if not pdf_generated:
        try:
            from weasyprint import HTML  # type: ignore

            HTML(string=rendered_html).write_pdf(str(pdf_output_path.resolve()))
            if pdf_output_path.is_file() and pdf_output_path.stat().st_size > 0:
                pdf_generated = True
                log(f"  Report PDF (WeasyPrint): {pdf_output_path.resolve()}")
        except Exception:
            pass

    return pdf_generated


def render_report(
    report: AssessmentReport,
    base_path: Path,
    session_summary: Optional[Dict],
    log: Callable[[str], None] = print,
) -> None:
    """Renderizza il report in formato HTML e PDF:
    - Template Jinja caricato da resource_path('templates') con autoescape
    - PDF tentato via Microsoft Edge headless (as_uri() per gestire spazi),
      fallback su WeasyPrint se disponibile, altrimenti solo HTML.
    """
    templates_dir = resource_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.globals.update(diff=correction_diff, timeline=timeline, num=num, signed=signed)
    template = env.get_template("report_template.html")
    rendered_html = template.render(data=report, session_summary=session_summary,
                                    shown=select_for_display(report))

    base = Path(base_path)
    html_output_path = base.with_suffix(".html")
    pdf_output_path = base.with_suffix(".pdf")

    html_output_path.write_text(rendered_html, encoding="utf-8")
    log(f"  Report HTML: {html_output_path.resolve()}")

    pdf_generated = _render_pdf(html_output_path, pdf_output_path, rendered_html, log)

    if not pdf_generated:
        log("  [AVVISO] PDF non generato. Il report HTML e comunque utilizzabile.")


def process_single_audio(
    audio_path: Path | str,
    student_name: str,
    model_name: str,
    output_dir: Path | str,
    api_key: Optional[str] = None,
    log: Callable[[str], None] = print,
    transcript_data: Optional[List] = None,
    transcript_source: str = "llm",
    mode: str = "base",
    force: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Elabora un singolo file audio per la generazione del report diagnostico scritto:
    1. Risolve la cartella di destinazione della lezione
    2. Copia l'audio sorgente se non presente
    3. Riusa report.json se esistente, altrimenti invoca analyze_audio
    4. Imposta session_date e student_name
    5. Salva report.json ed errori.csv
    6. Aggiorna lo storico sessions.jsonl in output_dir
    7. Renderizza HTML e PDF
    """
    src_audio = Path(audio_path)
    if not src_audio.is_file():
        raise FileNotFoundError(f"File audio non trovato: {src_audio}")

    out_root = Path(output_dir)
    lesson_dir = resolve_lesson_dir(out_root, student_name, src_audio)
    audio_copy = lesson_dir / src_audio.name

    # 1. Copia preventiva audio
    if not audio_copy.exists():
        log(f"  [1/5] Copia preventiva audio in: {audio_copy}")
        shutil.copy2(src_audio, audio_copy)
    else:
        log(f"  [1/5] Copia audio gia presente in: {audio_copy}")

    json_path = lesson_dir / "report.json"
    report = None if force else load_report(json_path)

    if report:
        log("  [2/5] Dati diagnostici gia presenti in report.json (riutilizzo istantaneo senza ricarico cloud)...")
    else:
        resolved_key = api_key
        if not resolved_key:
            resolved_key, _ = get_api_key()
        if not resolved_key:
            raise ValueError(
                "Chiave API Gemini non trovata. Inserisci la tua chiave dal pulsante 'Chiave API…' o imposta la variabile d'ambiente GEMINI_API_KEY."
            )

        report = analyze_audio(
            audio_path=audio_copy,
            api_key=resolved_key,
            model=model_name,
            student_name=student_name,
            log=log,
            transcript_data=transcript_data,
            transcript_source=transcript_source,
            mode=mode,
            progress=progress,
        )

    # Impostazione data e studente
    d = lesson_date(src_audio)
    report.session_date = format_date_it(d)
    report.student_name = student_name

    # Salva report.json aggiornato
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    # Esportazione CSV
    csv_path = lesson_dir / "errori.csv"
    export_csv(report, str(csv_path))
    log(f"  [3/5] CSV errori esportato in: {csv_path}")

    # Aggiornamento sessione longitudinale in output_dir
    sessions_file = out_root / "sessions.jsonl"
    log("  [4/5] Registrazione checkpoint longitudinale (sessions.jsonl)...")
    upsert_session(report, sessions_file, src_audio.name, d.isoformat())

    # Rendering
    log("  [5/5] Rendering report HTML e PDF nativo...")
    session_summary = get_session_summary(sessions_file, src_audio.name, student_name=student_name)
    report_base = lesson_dir / f"Report_{lesson_dir.name}"
    render_report(report, report_base, session_summary, log=log)

    return str(lesson_dir.resolve())


def process_single_audio_review(
    audio_path: Path | str,
    student_name: str,
    model_name: str,
    output_dir: Path | str,
    api_key: Optional[str] = None,
    log: Callable[[str], None] = print,
    stop_check: Optional[Callable[[], bool]] = None,
    mode: str = "base",
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """Elabora l'Audio Review didattico in formato MP3:
    1. Risolve la cartella unificata della lezione
    2. NON copia l'audio sorgente
    3. Riusa report.json se esistente, altrimenti esegue l'analisi
    4. Sintetizza la traccia MP3 con sintesi vocale neurale Cambridge RP
    """
    from audio_tutor import generate_audio_review

    src_audio = Path(audio_path)
    if not src_audio.is_file():
        raise FileNotFoundError(f"File audio non trovato: {src_audio}")

    out_root = Path(output_dir)
    lesson_dir = resolve_lesson_dir(out_root, student_name, src_audio)
    json_path = lesson_dir / "report.json"
    mp3_out_path = lesson_dir / f"Audio_Review_{lesson_dir.name}.mp3"

    report = load_report(json_path)
    if report:
        log("  [1/2] Report diagnostico esistente rilevato in report.json (riutilizzo istantaneo)...")
    else:
        resolved_key = api_key
        if not resolved_key:
            resolved_key, _ = get_api_key()
        if not resolved_key:
            raise ValueError(
                "Chiave API Gemini non trovata. Inserisci la tua chiave dal pulsante 'Chiave API…' o imposta la variabile d'ambiente GEMINI_API_KEY."
            )

        log(f"  [1/2] Nessun report pregresso trovato. Avvio analisi multimodale audio ({model_name})...")
        report = analyze_audio(
            audio_path=src_audio,
            api_key=resolved_key,
            model=model_name,
            student_name=student_name,
            log=log,
            mode=mode,
            progress=progress,
        )
        d = lesson_date(src_audio)
        report.session_date = format_date_it(d)
        report.student_name = student_name

        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

    log("  [2/2] Generazione sintesi vocale Cambridge RP (Sonia & Ryan)...")
    mp3_res = generate_audio_review(
        report_data=report,
        output_mp3_path=str(mp3_out_path),
        log_callback=log,
        stop_check=stop_check,
    )

    log(f"  Audio Review completato: {mp3_res}")
    return mp3_res


def render_from_json(json_path: Path | str, log: Callable[[str], None] = print) -> None:
    """Rigenera il report HTML/PDF direttamente da un file JSON esistente,
    senza alterare lo storico delle sessioni."""
    jp = Path(json_path)
    report = load_report(jp)
    if not report:
        raise ValueError(f"Impossibile caricare o validare il report JSON da: {jp}")

    report_base = jp.parent / f"Report_{jp.parent.name}"
    log(f"Rendering da JSON per: {jp.resolve()}...")
    render_report(report, report_base, session_summary=None, log=log)


def main():
    if len(sys.argv) == 1:
        # Avvio interfaccia grafica desktop (GUI)
        from app_gui import launch_gui

        launch_gui()
        return

    settings = load_settings()

    parser = argparse.ArgumentParser(
        description="English Assessment Engine — Diagnostic Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi d'uso:
  # Analisi di una lezione
  python generate_report.py --audio lezione.m4a

  # Specificando studente e cartella output esplicita
  python generate_report.py --audio lezione.m4a --student-name Mario --output-dir D:\\Report

  # Generazione anche dell'Audio Review MP3
  python generate_report.py --audio lezione.m4a --generate-audio

  # Rigenerazione solo rendering da file JSON
  python generate_report.py --from-json /percorso/a/report.json

  # Avvio GUI Desktop
  python generate_report.py
        """,
    )
    parser.add_argument("--audio", help="Percorso del file audio (.m4a, .mp3, .wav, ecc.)")
    parser.add_argument("--student-name", default=None, help="Nome dello studente (default: impostazioni utente)")
    parser.add_argument("--output-dir", default=None, help="Cartella principale per i report (default: impostazioni utente)")
    parser.add_argument("--model", default=None, choices=MODELS, help=f"Modello Gemini multimodale (default: {settings.model})")
    parser.add_argument("--from-transcript", help="Carica trascrizione di supporto da file JSON")
    parser.add_argument(
        "--transcript-source",
        default="llm",
        choices=["llm", "whisper", "manual"],
        help="Origine della trascrizione: 'llm', 'whisper', 'manual'. Default: llm",
    )
    parser.add_argument("--from-json", help="Rigenera report HTML/PDF a partire da un report.json esistente")
    parser.add_argument("--generate-audio", action="store_true", help="Genera anche la traccia didattica Audio Review MP3")
    parser.add_argument("--mode", default=None, choices=["base", "avanzata"],
                        help=f"Tipo di analisi: 'base' = 1 chiamata, 'avanzata' = spezzoni + sintesi (default: {settings.analysis_mode})")
    parser.add_argument("--force", action="store_true", help="Rianalizza anche se esiste già un report.json")
    parser.add_argument("--audio-only", action="store_true", help="Genera SOLO la traccia Audio Review MP3 (senza report scritto)")

    args = parser.parse_args()

    try:
        if args.from_json:
            render_from_json(args.from_json)
            return

        if not args.audio:
            parser.error("Specificare un file audio con --audio oppure usare --from-json.")

        student = (args.student_name or settings.student_name or "").strip()
        if not student:
            parser.error("Nome studente mancante. Specificalo con --student-name o configuralo nelle impostazioni.")

        out_dir = (args.output_dir or settings.output_dir or "").strip()
        if not out_dir:
            parser.error("Cartella output non configurata. Specificala con --output-dir o configurala nelle impostazioni.")

        model = (args.model or settings.model or DEFAULT_MODEL).strip()
        mode = args.mode or settings.analysis_mode

        transcript_data = None
        if args.from_transcript:
            with open(args.from_transcript, "r", encoding="utf-8") as f:
                transcript_data = json.load(f)

        if args.audio_only:
            process_single_audio_review(
                audio_path=args.audio,
                student_name=student,
                model_name=model,
                output_dir=out_dir,
                mode=mode,
            )
        else:
            process_single_audio(
                audio_path=args.audio,
                student_name=student,
                model_name=model,
                output_dir=out_dir,
                transcript_data=transcript_data,
                transcript_source=args.transcript_source,
                mode=mode,
                force=args.force,
            )
            if args.generate_audio:
                process_single_audio_review(
                    audio_path=args.audio,
                    student_name=student,
                    model_name=model,
                    output_dir=out_dir,
                    mode=mode,
                )

    except Exception as e:
        print(f"\n[ERRORE FATALE] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
