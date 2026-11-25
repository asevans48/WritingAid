"""Decision 9: "Fix all" is not offered for confused words (their/there,
its/it's …), whose right form depends on the sentence; it still is for a
repeated misspelling or an overused word."""

from types import SimpleNamespace as N

import pytest

from src.ui import fix_all
from src.utils.editor_flags import ErrorType


def err(word, fixes, kind=ErrorType.GRAMMAR, rule=""):
    return N(error_type=kind, word=word, suggestions=fixes, rule_id=rule, start=0, end=len(word))


@pytest.mark.parametrize("e", [
    err("Their", ["there"], rule="THEIR_THERE"),
    err("its", ["it's"], rule="ITS_ITS"),
    err("then", ["than"]),                                  # LanguageTool, no known rule id
    err("your", ["you're"], rule="YOUR_YOU_RE"),
    err("could of", ["could have", "could've"], rule="MODAL_OF"),
    err("loose", ["lose"], rule="CONFUSION_RULE_LOOSE_LOSE"),
    err("Its", ["It’s"]),                                    # curly apostrophe
])
def test_confused_words_get_no_fix_all(e):
    assert fix_all.is_confusable(e)
    assert not fix_all.can_fix_everywhere(e)


@pytest.mark.parametrize("e", [
    err("teh", ["the"], kind=ErrorType.SPELLING),
    err("recieve", ["receive"], kind=ErrorType.SPELLING),
    err("very", ["quite"], kind=ErrorType.OVERUSE),
    err("alot", ["a lot"], rule="ALOT_X"),
])
def test_other_flags_still_offer_fix_all(e):
    assert not fix_all.is_confusable(e)
    assert fix_all.can_fix_everywhere(e)
