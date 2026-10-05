"""
audio_tutor.py — Modulo Didattico Audio Review & Shadowing (BETA)

Genera una traccia audio MP3 di ripasso e shadowing per la lezione con sintesi parallela ad alte prestazioni:
- Voce Tutor (en-GB-SoniaNeural): introduce la sessione, cita l'errore dello studente e guida i drill fonetici.
- Voce Madrelingua (en-GB-RyanNeural): pronuncia la correzione corretta con accento nativo Cambridge RP,
  rispetta una pausa di 3.5 secondi per lo shadowing (ripetizione a voce alta dell'allievo),
  e ripete la frase corretta a scopo di consolidamento mnemonico.
"""

import os
import re
import asyncio
import tempfile
from typing import List, Dict, Optional, Callable
import edge_tts

from schema import AssessmentReport
from merge import select_for_audio_review

# Frame silenzioso standard MPEG-2 Layer III mono 24kHz @ 48kbps (144 byte per frame, ~24ms)
_SILENT_FRAME = b'\xff\xf3\x64\xc4' + (b'\x00' * 140)


def get_silence_bytes(duration_seconds: float) -> bytes:
    """Genera frame MP3 conformi di silenzio assoluto per la durata specificata."""
    frame_count = max(1, int(round(duration_seconds / 0.024)))
    return _SILENT_FRAME * frame_count


def clean_tts_text(text: str) -> str:
    """Sanitizza il testo da pronunciare rimuovendo caratteri IPA non standard, markup o artefatti."""
    if not text:
        return ""
    t = text.strip()
    t = t.replace('"', '').replace('“', '').replace('”', '').replace("’", "'")
    t = re.sub(r'\[\s*\d{1,2}:\d{2}\s*\]', '', t)
    t = re.sub(r'/([^/]+)/', r'\1', t)
    t = re.sub(r'\([^\)]*\)', '', t)
    # Rimuovi simboli fonetici IPA o caratteri unicode fuori dall'alfabeto latino standard
    t = re.sub(r'[^\w\s\.,\?!;:\'\-]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def build_drill_script(report: AssessmentReport) -> List[Dict]:
    """Costruisce la sequenza di blocchi didattici per l'Audio Review."""
    student_name = clean_tts_text(report.student_name or "Student")
    session_date = clean_tts_text(report.session_date or "today's session")

    script: List[Dict] = []
    seg_id = 0

    def next_id():
        nonlocal seg_id
        seg_id += 1
        return seg_id

    # 1. INTRODUZIONE TUTOR
    intro_text = (
        f"Hello {student_name}. Welcome to your Cambridge speaking review for the session on {session_date}. "
        f"Listen carefully to each mistake quoted from your audio, then practice the correct sentence during the pause."
    )
    script.append({
        "order": next_id(),
        "type": "speech",
        "speaker": "tutor",
        "text": intro_text
    })
    script.append({
        "order": next_id(),
        "type": "silence",
        "duration": 1.5
    })

    # 2. SEZIONE GRAMMATICA
    grammar_items = select_for_audio_review(report)
    for i, g in enumerate(grammar_items, start=1):
        quote = clean_tts_text(g.audio_quote)
        corr = clean_tts_text(g.correction)
        if not quote or not corr:
            continue

        # Tutor cita l'errore dello studente
        script.append({
            "order": next_id(),
            "type": "speech",
            "speaker": "tutor",
            "text": f"Mistake number {i}. The student said: {quote}."
        })
        script.append({
            "order": next_id(),
            "type": "silence",
            "duration": 0.8
        })

        # Madrelingua pronuncia la versione corretta
        script.append({
            "order": next_id(),
            "type": "speech",
            "speaker": "native",
            "text": f"Correct version: {corr}."
        })

        # Pausa per lo Shadowing (3.5 secondi)
        script.append({
            "order": next_id(),
            "type": "silence",
            "duration": 3.5
        })

        # Madrelingua ripete per consolidamento
        script.append({
            "order": next_id(),
            "type": "speech",
            "speaker": "native",
            "text": f"Listen again: {corr}."
        })
        script.append({
            "order": next_id(),
            "type": "silence",
            "duration": 1.5
        })

    # 3. SEZIONE FONETICA (Top 6 parole chiave con drill nativo)
    phonetic_items = (report.phonetics_table or [])[:6]
    if phonetic_items:
        script.append({
            "order": next_id(),
            "type": "speech",
            "speaker": "tutor",
            "text": "Now, let us practice key pronunciation drills."
        })
        script.append({
            "order": next_id(),
            "type": "silence",
            "duration": 1.2
        })

        for p in phonetic_items:
            term = clean_tts_text(p.term)
            if not term:
                continue

            # Tutor introduce la parola
            script.append({
                "order": next_id(),
                "type": "speech",
                "speaker": "tutor",
                "text": f"Pronunciation focus for the word: {term}."
            })
            script.append({
                "order": next_id(),
                "type": "silence",
                "duration": 0.8
            })

            # Madrelingua pronuncia la parola due volte con pausa di ripetizione
            script.append({
                "order": next_id(),
                "type": "speech",
                "speaker": "native",
                "text": f"Listen: {term}."
            })
            script.append({
                "order": next_id(),
                "type": "silence",
                "duration": 2.0
            })
            script.append({
                "order": next_id(),
                "type": "speech",
                "speaker": "native",
                "text": f"Repeat: {term}."
            })
            script.append({
                "order": next_id(),
                "type": "silence",
                "duration": 2.0
            })

    # 4. CONCLUSIONE TUTOR
    outro_text = (
        f"Review session completed. Great work, {student_name}. "
        f"Practicing these sentences every day will build your natural English fluency. See you at the next lesson!"
    )
    script.append({
        "order": next_id(),
        "type": "speech",
        "speaker": "tutor",
        "text": outro_text
    })

    return script


async def _synthesize_script_async(
    script: List[Dict],
    output_mp3_path: str,
    voice_tutor: str = "en-GB-SoniaNeural",
    voice_native: str = "en-GB-RyanNeural",
    log_callback: Callable[[str], None] = print,
    stop_check: Optional[Callable[[], bool]] = None
) -> str:
    """Esegue la sintesi vocale in parallelo veloce e assembla l'MP3 finale atomico."""
    tmp_output = output_mp3_path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(output_mp3_path)), exist_ok=True)

    speech_items = [item for item in script if item["type"] == "speech"]
    total_speech = len(speech_items)

    log_callback(f"     [Audio Review] Sintesi parallela di {total_speech} frasi vocali (Cambridge Voices)...")

    semaphore = asyncio.Semaphore(5)
    completed_count = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        async def fetch_speech(order_id: int, text: str, voice: str):
            nonlocal completed_count
            if stop_check and stop_check():
                return
            dest_file = os.path.join(temp_dir, f"speech_{order_id:04d}.mp3")
            async with semaphore:
                try:
                    c = edge_tts.Communicate(text, voice=voice)
                    await c.save(dest_file)
                    completed_count += 1
                    if completed_count % 5 == 0 or completed_count == total_speech:
                        pct = int((completed_count / total_speech) * 100)
                        log_callback(f"     [Audio Review] Voci sintetizzate: {pct}% ({completed_count}/{total_speech})")
                except Exception as e:
                    log_callback(f"     [AVVISO Audio Review] Voce #{order_id} non riuscita ({e})")

        tasks = []
        for item in speech_items:
            v = voice_tutor if item["speaker"] == "tutor" else voice_native
            tasks.append(fetch_speech(item["order"], item["text"], v))

        await asyncio.gather(*tasks)

        if stop_check and stop_check():
            log_callback("     [Audio Review] Operazione interrotta dall'utente.")
            return ""

        log_callback("     [Audio Review] Assemblaggio traccia finale con pause didattiche...")

        # Assemblaggio ordinato
        with open(tmp_output, "wb") as out_f:
            for item in script:
                if item["type"] == "silence":
                    out_f.write(get_silence_bytes(item["duration"]))
                elif item["type"] == "speech":
                    seg_file = os.path.join(temp_dir, f"speech_{item['order']:04d}.mp3")
                    if os.path.exists(seg_file):
                        with open(seg_file, "rb") as sf:
                            out_f.write(sf.read())

    if os.path.exists(output_mp3_path):
        try:
            os.remove(output_mp3_path)
        except Exception:
            pass

    os.rename(tmp_output, output_mp3_path)
    file_size_kb = os.path.getsize(output_mp3_path) / 1024
    log_callback(f"     [Audio Review] Traccia MP3 completata: {file_size_kb:.1f} KB ({os.path.basename(output_mp3_path)})")
    return output_mp3_path


def generate_audio_review(
    report_data: AssessmentReport,
    output_mp3_path: str,
    voice_tutor: str = "en-GB-SoniaNeural",
    voice_native: str = "en-GB-RyanNeural",
    log_callback: Callable[[str], None] = print,
    stop_check: Optional[Callable[[], bool]] = None
) -> str:
    """Interfaccia sincrona per generare l'Audio Review didattico in MP3."""
    if not (report_data.grammar_table or report_data.phonetics_table):
        log_callback("     [Audio Review] Nessun errore presente nel report per la sintesi audio.")
        return ""

    script = build_drill_script(report_data)
    return asyncio.run(_synthesize_script_async(
        script, output_mp3_path, voice_tutor, voice_native, log_callback, stop_check
    ))
