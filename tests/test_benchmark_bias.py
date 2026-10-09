"""Regression tests for the stale-bias metric (review: benchmark missed bias).

Locks in the two predictions from the real benchmark report where the old
last-two-words heuristic read 0.00 but the answers clearly contained the
superseded value.
"""

from __future__ import annotations

from mnemo.eval.dataset import QAPair


def _answered_stale(qa: QAPair, prediction: str) -> bool:
    """Mirror of the benchmark's stale-bias check."""
    return bool(
        qa.is_update_query
        and qa.stale_value
        and qa.stale_value.lower() in prediction.lower()
    )


def _qa(stale_value: str) -> QAPair:
    return QAPair(
        question="q",
        answer="the-new-value",
        relevant_fact="The new value is set.",
        is_update_query=True,
        stale_value=stale_value,
    )


def test_stale_bias_detects_blended_editor_answer():
    # From the real report: gold was "VS Code", LLM answered with both.
    qa = _qa(stale_value="Neovim")
    assert _answered_stale(qa, "You use VS Code and Neovim as your editors.")


def test_stale_bias_detects_blended_language_answer():
    qa = _qa(stale_value="Python")
    assert _answered_stale(qa, "You prefer Python and TypeScript.")


def test_stale_bias_clean_when_only_new_value():
    qa = _qa(stale_value="Bucharest")
    assert not _answered_stale(qa, "You live in Amsterdam.")


def test_stale_bias_requires_update_query():
    qa = QAPair(
        question="q", answer="a", relevant_fact="f", is_update_query=False, stale_value="Python"
    )
    assert not _answered_stale(qa, "You prefer Python.")


def test_stale_bias_requires_stale_value():
    qa = _qa(stale_value="")
    assert not _answered_stale(qa, "You prefer Python.")
