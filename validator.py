import re
import eng_to_ipa as ipa_lib
from rapidfuzz import fuzz
from typing import List, Dict, Tuple, Optional
from schema import (
    AssessmentReport, GrammarEntry, PhoneticEntry, LexicalEntry,
    CriticalRule, ValidationStats, DiscardReasonEntry
)


def format_timestamp(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"


def extract_transcript_text(transcript_data: List[Dict]) -> str:
    """Restituisce tutto il testo pronunciato dallo studente."""
    student_texts = []
    for seg in transcript_data:
        speaker = seg.get("speaker", "STUDENT").upper()
        if speaker in ["STUDENT", "STUDENTE"]:
            student_texts.append(seg.get("text", ""))
    return " ".join(student_texts)


def find_best_transcript_match(
    quote: str,
    transcript_data: List[Dict],
    min_score: float = 80.0
) -> Optional[Tuple[Dict, float]]:
    """Cerca la citazione nei segmenti dello studente nel transcript."""
    cleaned_quote = quote.strip().lower()
    if not cleaned_quote:
        return None

    best_match = None
    best_score = 0.0

    for seg in transcript_data:
        speaker = seg.get("speaker", "STUDENT").upper()
        if speaker in ["STUDENT", "STUDENTE"]:
            seg_text = seg.get("text", "").lower()
            score = fuzz.partial_ratio(cleaned_quote, seg_text)
            if score > best_score:
                best_score = score
                best_match = seg

    if best_score >= min_score and best_match is not None:
        return best_match, best_score
    return None


def lookup_target_ipa(word: str) -> Optional[str]:
    """Cerca la trascrizione IPA ufficiale usando eng-to-ipa."""
    clean_word = re.sub(r'[^a-zA-Z]', '', word).lower()
    if not clean_word:
        return None
    res = ipa_lib.convert(clean_word)
    if res and not res.endswith('*'):
        return f"/{res}/"
    return None


def validate_and_filter_report(
    report_data: AssessmentReport,
    transcript_data: Optional[List[Dict]] = None,
    transcript_source: str = "llm"
) -> AssessmentReport:
    """
    Filtra deterministicamente l'output del modello.

    La qualità della validazione dipende dalla PROVENIENZA del transcript:
    - transcript_source="llm"     → validazione CIRCOLARE. Il fuzzy match NON produce verified_confidence.
    - transcript_source="whisper" → validazione INCROCIATA. Il fuzzy match popola verified_confidence.
    - transcript_source="manual"  → validazione GOLD STANDARD.
    """
    is_independent_transcript = transcript_source in ["whisper", "manual"]

    stats = ValidationStats(transcript_source=transcript_source)

    if not is_independent_transcript and transcript_data:
        stats.validation_note = (
            "⚠️ Validazione circolare: transcript e diagnosi provengono dalla stessa fonte LLM. "
            "La colonna 'Verificata' non è compilata. Per validazione reale, usa --transcript-source whisper."
        )
    elif is_independent_transcript and transcript_data:
        stats.validation_note = (
            f"✅ Validazione incrociata: diagnosi LLM validata contro transcript {transcript_source.upper()} indipendente."
        )
    else:
        stats.validation_note = "ℹ️ Nessun transcript disponibile. Validazione limitata a deduplicazione e lookup IPA."

    discard_reasons: Dict[str, int] = {}

    def record_discard(reason: str):
        stats.total_discarded += 1
        discard_reasons[reason] = discard_reasons.get(reason, 0) + 1

    # --- 1. VALIDAZIONE GRAMMATICA ---
    valid_grammar: List[GrammarEntry] = []
    seen_grammar_keys = set()

    for entry in report_data.grammar_table:
        stats.total_proposed += 1
        quote = entry.audio_quote.strip()

        # Tagging: tutto ciò che viene dal modello è llm_perceptual
        entry.source = "llm_perceptual"

        # Controllo 1: Correzione != Quote (evitiamo falsi positivi)
        if entry.correction.strip().lower() == quote.lower():
            record_discard("correction_equals_quote")
            continue

        # Controllo 2: Ancoraggio testuale e timestamp (se transcript disponibile)
        derived_time = None
        if transcript_data:
            match_res = find_best_transcript_match(quote, transcript_data, min_score=75.0)
            if not match_res:
                record_discard("quote_not_anchored_in_transcript")
                continue
            seg, score = match_res
            start_sec = seg.get("start", 0.0)
            derived_time = format_timestamp(start_sec)

            # verified_confidence SOLO se il transcript è indipendente
            if is_independent_transcript:
                entry.verified_confidence = round(score / 100.0, 3)

        # Controllo 3: Deduplicazione
        dedup_key = (quote.lower(), entry.error_type.lower())
        if dedup_key in seen_grammar_keys:
            record_discard("duplicate_entry")
            continue
        seen_grammar_keys.add(dedup_key)

        # Aggiorna timestamp
        if derived_time:
            entry.timestamp_derived = derived_time

        valid_grammar.append(entry)
        stats.total_validated += 1

    report_data.grammar_table = valid_grammar

    # --- 2. VALIDAZIONE FONETICA ---
    valid_phonetics: List[PhoneticEntry] = []
    seen_phonetic_terms = set()
    full_student_text = extract_transcript_text(transcript_data) if transcript_data else ""

    for entry in report_data.phonetics_table:
        stats.total_proposed += 1
        term = entry.term.strip()
        clean_term = re.sub(r'[^a-zA-Z]', '', term).lower()

        # Tagging iniziale
        entry.source = "llm_perceptual"

        # Controllo 1: La parola deve esistere nel transcript dello studente
        if transcript_data and clean_term:
            if clean_term not in full_student_text.lower():
                record_discard("phonetic_term_not_in_transcript")
                continue
            # verified_confidence solo se transcript indipendente
            if is_independent_transcript:
                entry.verified_confidence = 1.0  # Match esatto nel transcript

        # Controllo 2: Deduplicazione
        if clean_term in seen_phonetic_terms:
            record_discard("duplicate_phonetic_term")
            continue
        seen_phonetic_terms.add(clean_term)

        # Controllo 3: Lookup IPA da dizionario offline → source diventa "dictionary" per target_ipa
        ipa_target = lookup_target_ipa(term)
        if ipa_target:
            entry.target_ipa = ipa_target
            # Il target_ipa è deterministico/da dizionario, ma l'entry nel suo complesso resta llm_perceptual
        elif not entry.target_ipa:
            entry.target_ipa = "N/D"

        valid_phonetics.append(entry)
        stats.total_validated += 1

    report_data.phonetics_table = valid_phonetics

    # --- 3. VALIDAZIONE LESSICALE ---
    valid_lexical: List[LexicalEntry] = []
    seen_lexical_terms = set()

    for entry in report_data.lexical_table:
        stats.total_proposed += 1
        used = entry.used_term.strip().lower()

        # Tagging
        entry.source = "llm_perceptual"

        if used in seen_lexical_terms:
            record_discard("duplicate_lexical_term")
            continue
        seen_lexical_terms.add(used)

        # Normalizzazione registro
        if entry.language_register not in ["Business", "Informal", "Neutral"]:
            entry.language_register = "Neutral"

        valid_lexical.append(entry)
        stats.total_validated += 1

    report_data.lexical_table = valid_lexical

    # --- 4. CORREZIONE PRIORITÀ CRITICAL MATRIX ---
    for rule in report_data.critical_matrix:
        prio = rule.priority.upper().strip()
        if prio not in ["ALTA", "MEDIA", "BASSA"]:
            rule.priority = "BASSA" if prio == "BUONA" else "MEDIA"

    # --- 5. STATISTICHE DI VALIDAZIONE ---
    stats.discard_reasons = [
        DiscardReasonEntry(reason=k, count=v) for k, v in discard_reasons.items()
    ]
    report_data.validation_stats = stats

    return report_data
