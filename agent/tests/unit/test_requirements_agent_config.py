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

"""Structural + pure-function checks for the Requirements Agent — no model
calls, no Firestore. Live behavior is covered by
tests/integration/test_requirements_agent.py.
"""

from app.sub_agents.requirements_agent import (
    _KNOWN_SCHOOL_COLORS,
    _is_official_source,
    _known_college_key,
    _match_logobrands_entry,
    branding_extraction_agent,
    deadlines_extraction_agent,
    requirements_agent,
    requirements_confidence_loop,
    requirements_pipeline,
)


def test_official_source_heuristic() -> None:
    assert _is_official_source("https://admissions.mit.edu/apply") is True
    assert _is_official_source("https://www.rice.edu/financial-aid") is True
    assert _is_official_source("https://apply.commonapp.org/") is True
    assert _is_official_source("https://studentaid.gov/fafsa") is True
    assert _is_official_source("https://www.collegeadvisor.com/blog") is False
    assert _is_official_source("https://en.wikipedia.org/wiki/MIT") is False


def test_official_source_heuristic_uses_title_for_grounding_redirect_urls() -> None:
    """Regression test: found live that Gemini's grounding chunks return an
    opaque vertexaisearch.cloud.google.com redirect as `url`, never the real
    page — domain must come from `title` in that case."""
    redirect_url = (
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQE_abc123"
    )
    assert _is_official_source(redirect_url, title="rice.edu") is True
    assert _is_official_source(redirect_url, title="collegevine.com") is False
    assert (
        _is_official_source(redirect_url) is False
    )  # no title, no real domain to check


def test_requirements_agent_has_no_tools() -> None:
    """It only structures findings already gathered by the Research Agent —
    per .agents-cli-spec.md it must never search or invent on its own."""
    assert requirements_agent.tools == []


def test_requirements_agent_output_schema_wired() -> None:
    assert requirements_agent.output_key == "extracted_requirements"
    assert requirements_agent.output_schema is not None


def test_confidence_loop_is_bounded() -> None:
    """Cost control: capped below deep-search's default of 5 — see
    .agents-cli-spec.md § Constraints. Lowered to 1 (see config.py) since
    the per-college research loop (orchestrator_agent.py's
    PerCollegeResearchAndExtraction) pays this cost once PER COLLEGE now,
    not once per pipeline run."""
    assert requirements_confidence_loop.max_iterations == 1


def test_logobrands_never_matches_washu_to_university_of_washington() -> None:
    """Regression test: found live that "Washington University in St.
    Louis" (a D3 school) picked up University of Washington's logo, because
    they coincidentally share the single word "washington" and
    _match_logobrands_entry's Jaccard scoring has no absolute floor — any
    entry with nonzero overlap wins if it's the only one. WashU must never
    match here at all, regardless of score, so it falls through to the
    Wikipedia lookup for its own real logo instead."""
    entries = (("washington washington huskies", "https://example.com/uw.png"),)
    assert _match_logobrands_entry("Washington University in St. Louis", entries) is None
    # The real school this entry belongs to must still match normally.
    assert (
        _match_logobrands_entry("University of Washington", entries)
        == "https://example.com/uw.png"
    )


def test_washu_color_is_pinned_to_green_not_red() -> None:
    """Regression test: found live that college_research_agent's
    google_search-grounded pass non-deterministically reported WashU's
    primary color as red rather than green — genuine source ambiguity
    (WashU's own Wikipedia infobox lists "Red and green"), not something a
    prompt tweak reliably fixes run to run. Green must always win,
    regardless of what a given research pass reports."""
    colors = _KNOWN_SCHOOL_COLORS[_known_college_key("Washington University in St. Louis")]
    assert colors["primary"].upper() == "#2C5234"


def test_requirements_pipeline_order() -> None:
    """branding_extraction_agent/deadlines_extraction_agent are NOT in this
    pipeline — they now run in a separate, parallel branch (quick_research_
    pipeline, see orchestrator_agent.py's per_college_pipeline) so they
    don't have to wait behind requirements_confidence_loop's own real
    research pass."""
    assert requirements_pipeline.sub_agents == [
        requirements_confidence_loop,
        requirements_agent,
    ]


def test_branding_and_deadlines_extraction_agents_have_no_tools() -> None:
    """Same reasoning as requirements_agent: they only structure findings
    already gathered by their own research agent, never search on their
    own."""
    assert branding_extraction_agent.tools == []
    assert deadlines_extraction_agent.tools == []


def test_branding_and_deadlines_extraction_agents_output_schema_wired() -> None:
    assert branding_extraction_agent.output_key == "branding_extraction"
    assert branding_extraction_agent.output_schema is not None
    assert deadlines_extraction_agent.output_key == "deadlines_extraction"
    assert deadlines_extraction_agent.output_schema is not None
