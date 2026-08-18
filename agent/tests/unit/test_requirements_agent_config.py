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
    _is_official_source,
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
    .agents-cli-spec.md § Constraints."""
    assert requirements_confidence_loop.max_iterations == 2


def test_requirements_pipeline_order() -> None:
    assert requirements_pipeline.sub_agents == [
        requirements_confidence_loop,
        requirements_agent,
    ]
