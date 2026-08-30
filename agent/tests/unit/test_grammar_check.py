# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for app/tools/grammar_check.py's pure functions — no
Firestore, no model calls. `check_grammar` itself (the genai.Client-backed
entry point) needs real credentials, so it isn't exercised here.
"""

from app.tools.grammar_check import (
    GrammarIssue,
    _grounded_issues,
    _parse_raw_candidates,
)


def test_grounded_issues_keeps_verbatim_matches() -> None:
    text = "I has went to the store yesterday."
    issues = [
        GrammarIssue(original="I has went", suggestion="I went", explanation="Tense error."),
    ]
    assert _grounded_issues(issues, text) == issues


def test_grounded_issues_drops_hallucinated_text() -> None:
    text = "I has went to the store yesterday."
    issues = [
        GrammarIssue(
            original="not actually in the essay",
            suggestion="fixed",
            explanation="Made up.",
        ),
    ]
    assert _grounded_issues(issues, text) == []


def test_grounded_issues_drops_empty_original() -> None:
    text = "Some essay text."
    issues = [GrammarIssue(original="", suggestion="x", explanation="y")]
    assert _grounded_issues(issues, text) == []


def test_parse_raw_candidates_plain_json() -> None:
    raw = '[{"original": "a", "suggestion": "b", "explanation": "c"}]'
    assert _parse_raw_candidates(raw) == [
        {"original": "a", "suggestion": "b", "explanation": "c"}
    ]


def test_parse_raw_candidates_extracts_array_from_prose_wrapper() -> None:
    raw = 'Here are the mistakes:\n[{"original": "a", "suggestion": "b", "explanation": "c"}]\nDone.'
    assert _parse_raw_candidates(raw) == [
        {"original": "a", "suggestion": "b", "explanation": "c"}
    ]


def test_parse_raw_candidates_empty_list_when_no_mistakes() -> None:
    assert _parse_raw_candidates("[]") == []


def test_parse_raw_candidates_garbage_returns_empty() -> None:
    assert _parse_raw_candidates("not json at all") == []
