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

"""Structural checks on orchestrator_agent's wiring — no model calls, no
Firestore. Live behavior is covered by tests/integration/test_orchestrator_agent.py.
"""

from google.adk.tools.agent_tool import AgentTool

from app.agent import root_agent
from app.sub_agents.orchestrator_agent import (
    college_intake_pipeline,
    cross_college_analysis,
    orchestrator_agent,
)


def test_root_agent_is_the_orchestrator() -> None:
    assert root_agent is orchestrator_agent


def test_orchestrator_has_no_output_schema() -> None:
    """Must stay plain-text: an output_schema agent can't also delegate —
    see orchestrator_agent.py's module docstring."""
    assert orchestrator_agent.output_schema is None


def test_orchestrator_cannot_search_or_write_firestore_directly() -> None:
    """Per .agents-cli-spec.md, the Orchestrator does no specialized work
    itself — it only records the parsed college list, reads what's already
    tracked, and delegates the actual research/extraction."""
    tool_names = {
        getattr(t, "name", None) or getattr(t, "func", t).__name__
        for t in orchestrator_agent.tools
    }
    assert tool_names == {
        "record_requested_colleges",
        "get_tracked_colleges_tool",
        "college_intake_pipeline",
    }


def test_intake_pipeline_wrapped_via_agent_tool() -> None:
    pipeline_tools = [t for t in orchestrator_agent.tools if isinstance(t, AgentTool)]
    assert len(pipeline_tools) == 1
    assert pipeline_tools[0].agent is college_intake_pipeline


def test_intake_pipeline_stage_order() -> None:
    stage_names = [agent.name for agent in college_intake_pipeline.sub_agents]
    assert stage_names == [
        "college_intake_agent",
        "college_research_agent",
        "requirements_pipeline",
        "cross_college_analysis",
        "task_planning_pipeline",
        "priority_pipeline",
        "readiness_pipeline",
    ]


def test_cross_college_analysis_runs_conflict_and_essay_matching_concurrently() -> None:
    branch_names = {agent.name for agent in cross_college_analysis.sub_agents}
    assert branch_names == {"conflict_pipeline", "essay_matching_pipeline"}
