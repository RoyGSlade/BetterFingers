"""Regression tests for the two Wave 11B corrections to the parity collector.

Both defects were invisible: the ledger regenerated cleanly, the validator
passed, and the numbers were wrong. So each rule gets a test that fails if the
rule is ever relaxed, rather than relying on anyone re-deriving it.

1. COMMENTS ARE NOT EVIDENCE. ``parity_evidence`` resolves an id by looking for
   it anywhere in reachable source. Until this fix "anywhere" included comments,
   so a module that merely mentioned ``#backendStatus`` while explaining what
   replaced it made that row resolve in production -- and the row could then
   reach ``wired`` on a sentence. That inflates the wired count, which is the
   one number Gate 11 exists to make trustworthy.

2. ENDPOINT NEEDLES MUST BE MATCHABLE. Coverage used ``\\b<needle>\\b``. ``\\b``
   asserts a word/non-word transition, so ``\\b/personas/interview/answer``
   requires a word character immediately before the leading slash -- and a QA
   stub writes ``'POST /personas/interview/answer'``, where it is a space. Every
   endpoint row was reported uncovered however thoroughly it was exercised.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_evidence as pe  # noqa: E402


# --- 1. comments are not evidence -------------------------------------------


def test_js_line_comments_are_stripped():
    stripped = pe.strip_js_comments("const a = 1; // mentions #backendStatus\nconst b = 2;")
    assert "#backendStatus" not in stripped
    assert "const a = 1;" in stripped
    assert "const b = 2;" in stripped


def test_js_block_comments_are_stripped_across_lines():
    stripped = pe.strip_js_comments("a;\n/* replaces the legacy\n   #backendStatus card */\nb;")
    assert "#backendStatus" not in stripped
    assert "a;" in stripped and "b;" in stripped


def test_a_double_slash_inside_a_string_is_not_a_comment():
    """The reason this is a scanner and not a regex."""
    for quote in ("'", '"', "`"):
        source = f"const url = {quote}https://example.test/x{quote}; const keep = 1;"
        assert pe.strip_js_comments(source) == source


def test_an_escaped_quote_does_not_end_a_string():
    source = r"""const s = "he said \"hi\" // not a comment"; const keep = 1;"""
    assert pe.strip_js_comments(source) == source


def test_a_regex_literal_survives():
    source = "const re = /foo/; const keep = 1;"
    assert pe.strip_js_comments(source) == source


def test_html_comments_are_stripped_but_prose_apostrophes_are_safe():
    html = (
        "<!-- the old #backendStatus card lived here -->\n"
        "<p>the user's draft</p>\n"
        '<div id="sdStatusBackendValue"></div>\n'
    )
    stripped = pe.strip_comments(Path("page.html"), html)
    assert "#backendStatus" not in stripped
    # The apostrophe must not have opened a string that swallowed the markup
    # after it -- that is exactly why HTML is not run through the JS scanner.
    assert 'id="sdStatusBackendValue"' in stripped
    assert "the user's draft" in stripped


def test_js_comments_inside_html_script_blocks_are_stripped():
    html = '<script type="module">\n// mentions #backendStatus\nconst keep = 1;\n</script>'
    stripped = pe.strip_comments(Path("page.html"), html)
    assert "#backendStatus" not in stripped
    assert "const keep = 1;" in stripped


def test_stripping_preserves_line_count():
    """Blank the comment, do not delete it: neighbouring tokens must not join."""
    source = "a/* x */b;\nc; // y\nd;"
    stripped = pe.strip_js_comments(source)
    assert stripped.count("\n") == source.count("\n")
    assert "ab;" not in stripped


def test_a_commented_out_id_does_not_anchor_a_row(tmp_path):
    """End to end, through the real Closure builder."""
    page = tmp_path / "page.html"
    page.write_text(
        "<!-- <div id=\"ghostControl\"></div> -->\n"
        '<div id="realControl"></div>\n',
        encoding="utf-8",
    )
    closure = pe.Closure.build("t", page, tmp_path / "missing.js")
    assert "realControl" in closure.element_ids
    assert "ghostControl" not in closure.element_ids
    index = pe.build_id_index(closure)
    assert pe.resolve_id("realControl", closure, index) == "realControl"
    assert pe.resolve_id("ghostControl", closure, index) is None


# --- 2. endpoint needles must be matchable ----------------------------------


def _coverage(qa_text: str) -> pe.Coverage:
    return pe.Coverage(qa_files=[("scenario.mjs", qa_text)], unit_files=[])


def test_an_endpoint_needle_matches_a_stub_key():
    coverage = _coverage("'POST /personas/interview/answer': (req) => ({}),")
    qa, _unit = coverage.files_naming("/personas/interview/answer")
    assert qa == ["scenario.mjs"]


def test_an_endpoint_needle_does_not_match_a_longer_path():
    coverage = _coverage("'POST /personas/interview/answers': (req) => ({}),")
    qa, _unit = coverage.files_naming("/personas/interview/answer")
    assert qa == []


def test_an_identifier_needle_is_still_bounded_both_ways():
    coverage = _coverage("await page.click('#foundryChatLogExtra');")
    qa, _unit = coverage.files_naming("foundryChatLog")
    assert qa == []

    coverage = _coverage("await page.click('#foundryChatLog');")
    qa, _unit = coverage.files_naming("foundryChatLog")
    assert qa == ["scenario.mjs"]


def test_an_identifier_needle_does_not_match_a_namespaced_id():
    coverage = _coverage("await page.click('#sdFoundryChatLog');")
    qa, _unit = coverage.files_naming("foundryChatLog")
    assert qa == []


def test_a_path_segment_needle_does_not_match_a_longer_segment_neighbour():
    """The `/` in the lookaround: `answer` must not match inside a path."""
    coverage = _coverage("'POST /personas/interview/answer': (req) => ({}),")
    qa, _unit = coverage.files_naming("answer")
    assert qa == []
