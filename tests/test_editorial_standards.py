"""Every Critique report carries the same rules for putting a finding."""

from src.ai.editorial_standards import MARK, STANDARDS_COMPACT, with_standards


def test_added_once_and_shorter_for_small_models():
    full = with_standards("You are an editor.")
    assert full.startswith("You are an editor.") and MARK in full
    assert "Passage, effect, option" in full and "ask instead of instructing" in full
    assert "never change that format" in full
    assert with_standards(full) == full                        # twice does nothing
    compact = with_standards("You are an editor.", compact=True)
    assert compact.endswith(STANDARDS_COMPACT) and len(compact) < len(full)
    assert with_standards("") .startswith(MARK)


def test_every_report_call_is_sent_and_recorded_with_them():
    from src.ai import chapter_analysis_agent as caa

    class LLM:
        def __init__(self):
            self.systems = []

        def generate_text(self, prompt, system="", **kw):
            self.systems.append(system)
            return "A finding."

    analyzer_cls = next(c for c in vars(caa).values()
                        if isinstance(c, type) and "_generate" in vars(c))
    a = analyzer_cls.__new__(analyzer_cls)
    a.compact = False
    llm = LLM()
    assert a._generate(llm, "prompt", "You are a developmental editor.", 100) == "A finding."
    assert MARK in llm.systems[0] and llm.systems[0].count(MARK) == 1
    a._section = caa.ReportSection.__new__(caa.ReportSection)
    a._section.calls = []
    a._record_call("Full report", "report", "You are a developmental editor.", "p", "out")
    assert MARK in a._section.calls[0]["system"]               # recorded as it was sent
