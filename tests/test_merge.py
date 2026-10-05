import json

from chunking import AudioChunk
from schema import (AssessmentReport, ChunkAnalysis, CriticalRule, GrammarEntry, LexicalEntry,
                    PhoneticEntry, ProsodyAndToneAnalysis, SynthesisOutput)
import merge


def _g(quote, ts, conf=0.9):
    return GrammarEntry(entry_id="x", audio_quote=quote, correction=quote + " (ok)", error_type="T",
                        l1_interference="-", rule_and_example="-", llm_confidence=conf, timestamp_derived=ts)


def _p(term, ts):
    return PhoneticEntry(entry_id="x", term=term, perceived_ipa="-", category="Altro", practical_drill="-",
                         timestamp_derived=ts)


def _chunk(i, start, end, grammar=(), phon=()):
    return (AudioChunk(i, 2, start, end, b""),
            ChunkAnalysis(grammar_table=list(grammar), phonetics_table=list(phon), lexical_table=[],
                          prosody_notes=f"p{i}", fluency_notes=f"f{i}", topic=f"t{i}"))


def test_old_report_json_still_valid(sample_report):
    data = json.loads(sample_report.model_dump_json())
    data.pop("analysis_mode"), data.pop("n_chunks")
    r = AssessmentReport.model_validate(data)
    assert r.analysis_mode == "base" and r.n_chunks is None


def test_merge_absolute_times_overlap_dedup_and_ids():
    a = _chunk(1, 0, 600, [_g("I go in Spain last summer", "09:50", 0.8), _g("she go to work", "01:10")])
    b = _chunk(2, 570, 1200, [_g("I go in Spain last summer", "00:20", 0.95), _g("he don't like", "05:00")])
    gram, phon, lex, notes = merge.merge_chunks([b, a])
    assert [(g.audio_quote, g.timestamp_derived) for g in gram] == [
        ("she go to work", "01:10"), ("I go in Spain last summer", "09:50"), ("he don't like", "14:30")]
    assert gram[1].llm_confidence == 0.95
    assert [g.entry_id for g in gram] == ["gram_1", "gram_2", "gram_3"]
    assert [n["chunk"] for n in notes] == [1, 2]


def test_merge_bad_timestamps_fall_back_to_chunk_start():
    c = _chunk(2, 570, 1170, [_g("x one", "99:99"), _g("x two", None)], [_p("think", "nonsense")])
    gram, phon, _, _ = merge.merge_chunks([c])
    assert {g.timestamp_derived for g in gram} == {"09:30"}
    assert phon[0].timestamp_derived == "09:30" and phon[0].entry_id == "phon_1"


def test_select_distributed_covers_all_parts():
    entries = [_g(f"q{b}{k}", f"{b * 10 + k:02d}:00", conf=0.5 + k / 100) for b in range(3) for k in range(10)]
    chosen = merge.select_distributed(entries, 6, duration=1800, n_buckets=3)
    assert len(chosen) == 6
    assert sorted({int(g.timestamp_derived[:2]) // 10 for g in chosen}) == [0, 1, 2]
    assert chosen == sorted(chosen, key=lambda g: g.timestamp_derived)
    assert merge.select_distributed(entries[:4], 20, duration=1800, n_buckets=3) == entries[:4]


def test_assemble_report_removes_dangling_refs():
    gram = [_g("a", "00:10")]
    gram[0].entry_id = "gram_1"
    synth = SynthesisOutput(
        cefr_level="B1", main_topic="t", session_focus="f", executive_summary="s",
        prosody_and_tone=ProsodyAndToneAnalysis(intonation_pattern="-", speech_rhythm="-",
                                                tone_confidence="-", pause_profile="-"),
        score_phonetics=6, desc_phonetics="-", score_grammar=6, desc_grammar="-", score_lexicon=6,
        desc_lexicon="-", score_fluency=6, desc_fluency="-", score_autonomy=6, desc_autonomy="-",
        critical_matrix=[CriticalRule(priority="ALTA", title="t", description="d", refs=["gram_1", "gram_99"])],
        protocol_notes=[])
    r = merge.assemble_report(gram, [], [], synth, duration=2665, n_chunks=5)
    assert r.critical_matrix[0].refs == ["gram_1"]
    assert (r.analysis_mode, r.n_chunks, r.audio_sample_duration) == ("avanzata", 5, "44m 25s")
    payload = json.loads(merge.build_synthesis_input(gram, [], [], [{"chunk": 1}], 2665))
    assert payload["grammar"][0]["id"] == "gram_1" and payload["duration_minutes"] == 44.4
