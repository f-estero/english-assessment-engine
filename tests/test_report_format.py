from schema import GrammarEntry, LexicalEntry, PhoneticEntry
import report_format as rf


def test_correction_diff_marks_only_changed_words():
    html = str(rf.correction_diff("I go in Spain last summer", "I went to Spain last summer"))
    assert html == ('I <del>go in</del> <ins>went to</ins> Spain last summer')


def test_correction_diff_insertion_and_case_insensitive_equal():
    assert str(rf.correction_diff("Because is not covered", "Because it is not covered")) == \
        "Because <ins>it</ins> is not covered"
    assert str(rf.correction_diff("Hello", "hello")) == "Hello"


def test_correction_diff_escapes_html():
    html = str(rf.correction_diff("<b>x</b> go", "<b>x</b> goes"))
    assert "<b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html and "<del>go</del> <ins>goes</ins>" in html


def test_timeline_points_and_counts(sample_report):
    r = sample_report.model_copy(deep=True)
    r.audio_sample_duration = "10m 00s"
    r.grammar_table[0].timestamp_derived = "05:00"
    r.grammar_table[1].timestamp_derived = None          # senza minuto: escluso dai punti
    r.phonetics_table[0].timestamp_derived = "10:00"
    t = rf.timeline(r)
    assert t["minutes"] == 10
    assert [(p["kind"], p["pct"]) for p in t["points"]] == [("grammar", 50.0), ("phonetics", 100.0)]
    assert t["counts"] == {"grammar": 2, "phonetics": 1, "lexical": 1}


def test_number_format_italian():
    assert rf.num(6.0) == "6,0" and rf.num(5.55) == "5,6" and rf.signed(0.3) == "+0,3" and rf.signed(-1) == "−1,0"
