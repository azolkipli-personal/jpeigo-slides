"""A model's reasoning wrapper must never reach a slide.

`minimax-m3` answered a translation request with
`<think>The user wants me to translate Japanese to English…`, and nothing in the app
stripped it, so that text would have been injected into the deck verbatim.
"""
from app.core.textnorm import has_reasoning, strip_reasoning


def test_closed_wrapper_is_removed():
    assert strip_reasoning('<think>plan the answer</think>月次報告') == '月次報告'
    assert strip_reasoning('<THINKING>plan</THINKING>\nHello') == 'Hello'


def test_unclosed_wrapper_means_no_answer():
    """The budget ran out mid-thought: there is no translation to return."""
    assert strip_reasoning('<think>The user wants me to translate Japanese to En') == ''
    assert strip_reasoning('<think>') == ''


def test_wrapper_can_sit_between_the_answer_and_the_end():
    assert strip_reasoning('Hallo\n<reasoning>why</reasoning>') == 'Hallo'


def test_stray_closing_tag_is_removed():
    assert strip_reasoning('Hallo</think>') == 'Hallo'


def test_ordinary_angle_brackets_are_untouched():
    """Translations contain HTML and placeholders; stripping must be tag-specific."""
    for text in ('<span>no</span>', 'a < b > c', 'SLIDE_1<ANCHOR>', '2 < 3 and 4 > 1'):
        assert strip_reasoning(text) == text


def test_has_reasoning_reports_without_cleaning():
    assert has_reasoning('<think>x</think>y')
    assert has_reasoning('<think>unclosed')
    assert not has_reasoning('plain translation')


def test_empty_input_is_safe():
    assert strip_reasoning('') == ''
    assert not has_reasoning('')
