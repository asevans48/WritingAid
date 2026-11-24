"""Known false alarms, fixed: accented words and "I was not"."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.utils import editor_flags as ef
from src.utils.proofing import builtin_grammar, unaccented

TEXT = ("My Ántonia came to the door. I was not afraid of her. Señor Peña sat in the café "
        "with a naïve smile. Zoë and Chloé read Brontë. He was not there. I was not.")


def test_an_accented_word_is_one_word_and_no_flag():
    flags = ef.state_for_project(None).flags_for_text(TEXT)
    assert [(e.error_type, e.word) for _, e in flags] == []
    assert unaccented("café") == "cafe" and unaccented("Zoë") == "Zoe"


def test_a_misspelt_accented_word_is_flagged_whole():
    text = "She ordered a cafée and waited by the window for an hour."
    flags = ef.state_for_project(None).flags_for_text(text)
    assert [e.word for _, e in flags if e.error_type == ef.ErrorType.SPELLING] == ["cafée"]


def test_i_was_not_is_correct_and_real_agreement_errors_still_show():
    assert builtin_grammar("I was not afraid. I was not.") == []
    found = [i.text for i in builtin_grammar("I is tired and she have no money.")]
    assert "is" in " ".join(found) and "have" in " ".join(found)
