"""Grammar checking facade over ``src.utils.proofing``.

Moved out of ``src/ui/enhanced_text_editor.py`` in piece R.3, unchanged, so
chapters can be checked without the editor (no Qt here). The old import
path still works.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


class GrammarChecker:
    """Grammar checking facade over ``src.utils.proofing``.

    ``check_text`` always applies the fast built-in rules; with
    ``use_full_check`` it also runs LanguageTool (blocking — the editor's
    highlighter uses a background worker instead).
    """

    def __init__(self):
        self._ignored_rules: Set[str] = set()
        from src.utils.proofing import LanguageToolEngine
        ok, why = LanguageToolEngine.prerequisites()
        print("Grammar checker: LanguageTool available" if ok
              else f"Grammar checker: built-in rules only ({why})")

    def check_text(self, text: str, use_full_check: bool = False) -> List[Tuple[int, int, str, str, List[str]]]:
        """Check text for grammar errors.

        Returns:
            List of (start, end, error_text, message, suggestions)
        """
        from src.utils.proofing import LanguageToolEngine, builtin_grammar, merge_issues
        lt = LanguageToolEngine.get().check(text) if use_full_check else []
        issues = merge_issues(lt, builtin_grammar(text))
        return [i.as_tuple() for i in issues if i.rule_id not in self._ignored_rules]

    def ignore_rule(self, rule_id: str):
        """Ignore a specific grammar rule."""
        self._ignored_rules.add(rule_id)

    def is_available(self) -> bool:
        """Built-in rules are always available."""
        return True
