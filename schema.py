from pydantic import BaseModel, Field
from typing import List, Optional, Dict

# ============================================================
# SOURCE TAGGING — Provenienza di ogni dato
# ============================================================
# "deterministic"    → Calcolato da algoritmo, riproducibile (IPA dict, Praat, speech rate)
# "asr"              → Prodotto da un sistema ASR dedicato (Whisper)
# "llm_perceptual"   → Giudizio percettivo del modello multimodale (Gemini)
# "dictionary"       → Lookup da risorse lessicografiche offline
# "not_computed"     → Non ancora calcolato (placeholder per fasi future)
# ============================================================


class ProsodyAndToneAnalysis(BaseModel):
    """Valutazione PERCETTIVA della prosodia — NON misurazioni strumentali."""
    intonation_pattern: str = Field(description="Descrizione qualitativa del pattern di intonazione percepito (es. 'Intonazione ascendente su frasi affermative')")
    speech_rhythm: str = Field(description="Ritmo del parlato percepito (es. 'Syllable-timed da interferenza L1 italiana')")
    tone_confidence: str = Field(description="Valutazione qualitativa del tono di voce (es. 'Esitante nei costrutti complessi, più fluido nel lessico quotidiano')")
    pause_profile: str = Field(description="Profilo qualitativo delle pause (es. 'Frequenti pause piene uh/um prima dei verbi modali')")
    source: str = Field(default="llm_perceptual", description="Provenienza: sempre llm_perceptual per questa sezione")


class PhoneticEntry(BaseModel):
    entry_id: str = Field(description="Identificativo univoco, es. 'phon_1'")
    term: str = Field(description="Parola precisa pronunciata dall'allievo")
    perceived_ipa: str = Field(description="Trascrizione fonetica percepita dall'allievo, es. /kli-mænt/")
    target_ipa: Optional[str] = Field(default=None, description="Standard IPA — compilato dal validatore via dizionario offline")
    category: str = Field(description="Categoria: 'Spostamento d'Accento', 'Consonante Silente', 'Neutralizzazione Vocale', 'Dentale Sorda/Sonora', 'Altro'")
    stress_displacement: str = Field(default="Standard", description="Spostamento dell'accento tonico percepito dall'audio")
    practical_drill: str = Field(description="Esercizio pratico e concreto di articolazione/ripetizione")
    source: str = Field(default="llm_perceptual", description="Provenienza: llm_perceptual | dictionary (per target_ipa)")
    llm_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidenza AUTO-DICHIARATA dal modello (NON calibrata)")
    verified_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidenza calcolata dal validatore (fuzzy match / 100). Compilata solo con transcript ASR indipendente.")
    timestamp_derived: Optional[str] = Field(default=None, description="Momento dell'audio [MM:SS] in cui compare la voce")


class GrammarEntry(BaseModel):
    entry_id: str = Field(description="Identificativo univoco, es. 'gram_1'")
    audio_quote: str = Field(description="Citazione testuale esatta dall'audio del solo studente")
    correction: str = Field(description="Frase corretta secondo gli standard B1/B2")
    error_type: str = Field(description="Tipo di errore, es. 'Sintassi Modale', 'Deriva Preposizionale', 'Accordo Soggetto-Verbo', 'Inversione Domanda'")
    l1_interference: str = Field(description="Spiegazione del calco dall'italiano (perché l'italiano ha causato l'errore)")
    rule_and_example: str = Field(description="Regola grammaticale ed esempio pratico mnemonico")
    source: str = Field(default="llm_perceptual", description="Provenienza: llm_perceptual")
    llm_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidenza AUTO-DICHIARATA dal modello (NON calibrata)")
    verified_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidenza calcolata dal validatore. Compilata solo se transcript da ASR indipendente.")
    timestamp_derived: Optional[str] = Field(default=None, description="Timestamp dell'audio [MM:SS] — affidabile solo se da ASR, approssimativo se da LLM")


class LexicalEntry(BaseModel):
    entry_id: str = Field(description="Identificativo univoco, es. 'lex_1'")
    used_term: str = Field(description="Termine o espressione usata dall'allievo")
    calque_or_error: str = Field(description="Spiegazione del calco linguistico o errore di registro")
    target_term: str = Field(description="Termine o locuzione target corretta")
    language_register: str = Field(description="Registro: 'Business', 'Informal', 'Neutral'")
    context_note: str = Field(description="Contesto d'uso ed impatto comunicativo")
    source: str = Field(default="llm_perceptual", description="Provenienza: llm_perceptual")
    llm_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidenza AUTO-DICHIARATA dal modello (NON calibrata)")
    verified_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidenza calcolata dal validatore.")
    timestamp_derived: Optional[str] = Field(default=None, description="Momento dell'audio [MM:SS] in cui compare la voce")


class CriticalRule(BaseModel):
    priority: str = Field(description="Priorità tassativa: 'ALTA', 'MEDIA' o 'BASSA'")
    title: str = Field(description="Titolo sintetico della regola")
    description: str = Field(description="Trattazione operativa ed esempi")
    refs: List[str] = Field(default_factory=list, description="Elenco di entry_id collegati, es. ['gram_1', 'phon_2']")


class ProtocolNote(BaseModel):
    category: str = Field(description="Categoria: 'Punto di Forza', 'Azione Correttiva', 'Obiettivo Prossima Sessione'")
    title: str = Field(description="Titolo sintetico")
    details: str = Field(description="Indicazione didattica operativa")


class DiscardReasonEntry(BaseModel):
    reason: str = Field(description="Motivo dello scarto")
    count: int = Field(description="Numero di voci scartate")


class ValidationStats(BaseModel):
    total_proposed: int = 0
    total_validated: int = 0
    total_discarded: int = 0
    transcript_source: str = Field(default="llm", description="Origine transcript usato per validazione: 'llm' | 'whisper' | 'manual'")
    validation_note: str = Field(
        default="",
        description="Nota sulla qualità della validazione (es. 'Validazione circolare: transcript e diagnosi dalla stessa fonte LLM')"
    )
    discard_reasons: List[DiscardReasonEntry] = Field(default_factory=list)


# ============================================================
# CAF METRICS — Placeholder per Fase 2 (deterministiche)
# ============================================================
class CAFMetrics(BaseModel):
    """Metriche Complexity-Accuracy-Fluency. Tutte deterministiche quando calcolate."""
    words_per_minute: Optional[float] = Field(default=None, description="WPM calcolato da word count / speech duration")
    mean_length_of_run: Optional[float] = Field(default=None, description="Media parole tra pause > 500ms")
    type_token_ratio: Optional[float] = Field(default=None, description="Rapporto tipi/token lessicali")
    pause_ratio: Optional[float] = Field(default=None, description="silence_duration / total_duration")
    articulation_rate: Optional[float] = Field(default=None, description="Sillabe/sec escludendo pause (da Praat)")
    source: str = Field(default="not_computed", description="'deterministic' quando calcolato, 'not_computed' altrimenti")


# ============================================================
# REPORT PRINCIPALE
# ============================================================
class AssessmentReport(BaseModel):
    session_date: str = Field(description="Data della sessione, es. '05 Settembre 2026'")
    cefr_level: str = Field(description="Livello stimato, es. 'CEFR A2+ (Transizione B1)'")
    teacher_name: str = Field(description="Nome docente o indicazione della sessione")
    student_name: Optional[str] = Field(default="Studente", description="Nome dello studente")
    audio_sample_duration: str = Field(description="Durata audio analizzato, es. '46m 18s'")
    main_topic: str = Field(description="Topic principale della conversazione")
    session_focus: str = Field(description="Aree grammaticali e comunicative di focus")

    executive_summary: str = Field(description="Sintesi di 5-6 righe strettamente fattuali sul profilo linguistico")
    prosody_and_tone: Optional[ProsodyAndToneAnalysis] = Field(default=None, description="Valutazione PERCETTIVA della prosodia e del tono di voce")

    # Punteggi
    score_phonetics: float = Field(description="Punteggio Fonetica su 10 (peso 20%)")
    desc_phonetics: str = Field(description="Giustificazione fattuale fonetica ancorata alle voci")
    score_grammar: float = Field(description="Punteggio Grammatica su 10 (peso 25%)")
    desc_grammar: str = Field(description="Giustificazione fattuale grammatica ancorata alle voci")
    score_lexicon: float = Field(description="Punteggio Lessico su 10 (peso 20%)")
    desc_lexicon: str = Field(description="Giustificazione fattuale lessico ancorata alle voci")
    score_fluency: float = Field(description="Punteggio Fluency su 10 (peso 20%)")
    desc_fluency: str = Field(description="Giustificazione fattuale fluidità")
    score_autonomy: float = Field(description="Punteggio Autonomia su 10 (peso 15%)")
    desc_autonomy: str = Field(description="Giustificazione fattuale autonomia")

    # Sezioni analitiche
    phonetics_table: List[PhoneticEntry] = Field(default_factory=list, description="Voci fonetiche rilevate dall'ascolto dell'audio")
    grammar_table: List[GrammarEntry] = Field(default_factory=list, description="Errori morfosintattici citati dall'audio dello studente")
    lexical_table: List[LexicalEntry] = Field(default_factory=list, description="Calchi lessicali e scelte idiomatiche errate dello studente")
    critical_matrix: List[CriticalRule] = Field(default_factory=list, description="Regole cardine da fissare")
    protocol_notes: List[ProtocolNote] = Field(default_factory=list, description="Note del protocollo formativo finale")

    # Metriche e validazione
    caf_metrics: Optional[CAFMetrics] = Field(default=None, description="Metriche CAF (Fase 2)")
    validation_stats: Optional[ValidationStats] = Field(default=None, description="Statistiche del validatore deterministico")

    # Compilati dal codice, mai dal modello
    analysis_mode: str = Field(default="base", description="'base' (chiamata unica) o 'avanzata' (spezzoni + sintesi)")
    n_chunks: Optional[int] = Field(default=None, description="Numero di spezzoni analizzati (solo modalità avanzata)")


# ============================================================
# MODALITÀ AVANZATA — output del modello per spezzone e sintesi finale
# ============================================================
class ChunkAnalysis(BaseModel):
    """Voci rilevate in UNO spezzone audio; i timestamp sono relativi all'inizio dello spezzone."""
    grammar_table: List[GrammarEntry] = Field(default_factory=list, description="Errori morfosintattici dello studente")
    phonetics_table: List[PhoneticEntry] = Field(default_factory=list, description="Imprecisioni fonetiche dello studente")
    lexical_table: List[LexicalEntry] = Field(default_factory=list, description="Calchi lessicali dello studente")
    prosody_notes: str = Field(description="2-4 frasi percettive su intonazione, ritmo e pause in questo spezzone")
    fluency_notes: str = Field(description="2-3 frasi su scorrevolezza, esitazioni e autocorrezioni")
    topic: str = Field(default="", description="Argomento dello spezzone in una riga")


class SynthesisOutput(BaseModel):
    """Valutazione complessiva della lezione, scritta a partire dalle voci di tutti gli spezzoni."""
    cefr_level: str = Field(description="Livello stimato, es. 'CEFR A2+ (Transizione B1)'")
    main_topic: str = Field(description="Topic principale della conversazione")
    session_focus: str = Field(description="Aree grammaticali e comunicative di focus")
    executive_summary: str = Field(description="Sintesi di 5-6 righe strettamente fattuali")
    prosody_and_tone: ProsodyAndToneAnalysis
    score_phonetics: float = Field(description="Punteggio Fonetica su 10")
    desc_phonetics: str = Field(description="Giustificazione che cita gli id delle voci")
    score_grammar: float = Field(description="Punteggio Grammatica su 10")
    desc_grammar: str = Field(description="Giustificazione che cita gli id delle voci")
    score_lexicon: float = Field(description="Punteggio Lessico su 10")
    desc_lexicon: str = Field(description="Giustificazione che cita gli id delle voci")
    score_fluency: float = Field(description="Punteggio Fluency su 10")
    desc_fluency: str = Field(description="Giustificazione fattuale")
    score_autonomy: float = Field(description="Punteggio Autonomia su 10")
    desc_autonomy: str = Field(description="Giustificazione fattuale")
    critical_matrix: List[CriticalRule] = Field(default_factory=list, description="4-6 regole cardine con refs agli id esistenti")
    protocol_notes: List[ProtocolNote] = Field(default_factory=list, description="5-8 note formative")
