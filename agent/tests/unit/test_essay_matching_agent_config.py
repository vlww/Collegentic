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

"""Structural checks on the Essay Matching Agent's wiring — no model calls,
no Firestore. Live behavior is covered by
tests/integration/test_essay_matching_agent.py.
"""

from app.sub_agents.essay_matching_agent import (
    EssayContextAgent,
    essay_analysis_agent,
    essay_matching_pipeline,
)


def test_essay_analysis_agent_has_no_tools() -> None:
    """It only reasons over pre-gathered facts — never sees raw Firestore,
    and per .agents-cli-spec.md § Constraints, it has no essay-editing
    tool at all: it can only score reuse-fit, never rewrite text."""
    assert essay_analysis_agent.tools == []


def test_essay_analysis_agent_output_schema_wired() -> None:
    assert essay_analysis_agent.output_key == "essay_analysis"
    assert essay_analysis_agent.output_schema is not None


def test_context_agent_logs_activity() -> None:
    agent = EssayContextAgent()
    assert agent.before_agent_callback is not None
    assert agent.after_agent_callback is not None


def test_pipeline_order() -> None:
    assert [agent.name for agent in essay_matching_pipeline.sub_agents] == [
        "essay_context_agent",
        "essay_analysis_agent",
    ]
