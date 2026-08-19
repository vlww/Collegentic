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

"""Structural checks on the Readiness Agent's wiring — no model calls, no
Firestore. Live behavior is covered by
tests/integration/test_readiness_agent.py.
"""

from app.sub_agents.readiness_agent import (
    CollegeReadinessContextAgent,
    readiness_explanation_agent,
    readiness_pipeline,
)


def test_readiness_explanation_agent_has_no_tools() -> None:
    """It only rewrites pre-computed facts into a sentence — never sees the
    raw requirement data or Firestore, so it can't invent a fact scoring.py
    didn't already compute."""
    assert readiness_explanation_agent.tools == []


def test_readiness_explanation_agent_output_schema_wired() -> None:
    assert readiness_explanation_agent.output_key == "readiness_explanations"
    assert readiness_explanation_agent.output_schema is not None


def test_context_agent_logs_activity() -> None:
    agent = CollegeReadinessContextAgent()
    assert agent.before_agent_callback is not None
    assert agent.after_agent_callback is not None


def test_pipeline_order() -> None:
    assert [agent.name for agent in readiness_pipeline.sub_agents] == [
        "college_readiness_context_agent",
        "readiness_explanation_agent",
    ]
