"""R.4: one implementation of each style check. The Critique's numbers
(ProWritingAnalyzer) come from the editor's style checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = ("Glass was thrown across the floor. The ship was sunk by a mine, and he ran quickly. "
        "She shouted loudly. At the end of the day it was all of a sudden over. "
        "It was the one that he had been thinking of when he was out in the boat with them. "
        "The light from the lamp spilled over the table and the lamp's light caught the knife.")


def test_the_critique_counts_what_the_editor_flags():
    from src.utils import style_checks as sc
    from src.utils.writing_stats import ProWritingAnalyzer
    stats = ProWritingAnalyzer().analyze(TEXT)
    editor = sc.analyze_document(TEXT, {"passive", "adverb", "cliche", "sticky_sentence", "echo",
                                        "long_sentence"})
    by_kind = {k: [i for i in editor if i.kind == k] for k in ("adverb", "cliche", "echo")}
    assert stats.adverb_count == len(by_kind["adverb"])
    assert sorted(stats.adverbs) == sorted({i.text.lower() for i in by_kind["adverb"]})
    assert stats.cliches == list(dict.fromkeys(i.text.lower() for i in by_kind["cliche"]))
    assert stats.echo_count == len(by_kind["echo"])
    # Irregular passives, which the Critique used to miss, now count.
    assert stats.passive_count == 2
    assert stats.sticky_sentence_count >= 1


def test_the_critiques_fields_keep_their_shape():
    from src.utils.writing_stats import ProWritingAnalyzer
    s = ProWritingAnalyzer().analyze(TEXT)
    assert all(isinstance(e, tuple) and len(e) == 3 and e[1] < e[2] for e in s.echoes)
    assert isinstance(s.passive_sentences, list) and isinstance(s.sticky_sentences, list)
    assert 0 <= s.passive_percentage <= 100 and 0 <= s.adverb_percentage <= 100
    assert 0 < s.avg_glue_index < 1


def test_no_second_copy_of_the_word_lists():
    from src.utils import style_checks as sc
    from src.utils.writing_stats import ProWritingAnalyzer
    assert ProWritingAnalyzer.GLUE_WORDS == frozenset(sc.GLUE)
    assert ProWritingAnalyzer.CLICHES == frozenset(sc.CLICHES)
    source = (ROOT / "src" / "utils" / "writing_stats.py").read_text()
    for gone in ("COMMON_ADVERBS", "PASSIVE_HELPERS", "passive_pattern"):
        assert gone not in source


def test_stored_names_of_the_style_checks_are_unchanged():
    """Style sheets, ignore lists and highlight settings store these names."""
    from src.utils import style_checks as sc
    assert set(sc.KINDS) == {"passive", "adverb", "intensifier", "wordy", "cliche",
                             "repeated_start", "echo", "preference", "long_sentence",
                             "hard_sentence", "sticky_sentence"}


def test_empty_text_still_gives_empty_stats():
    from src.utils.writing_stats import ProWritingAnalyzer
    s = ProWritingAnalyzer().analyze("")
    assert s.passive_count == s.adverb_count == s.echo_count == 0
