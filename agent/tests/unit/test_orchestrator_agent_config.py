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

from google.adk.agents import ParallelAgent
from google.adk.tools.agent_tool import AgentTool

from app.agent import root_agent
from app.sub_agents.orchestrator_agent import (
    college_intake_pipeline,
    cross_college_analysis,
    orchestrator_agent,
    per_college_pipeline,
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
        "per_college_research_and_extraction",
        "cross_college_analysis",
        "task_planning_pipeline",
        "priority_pipeline",
        "readiness_pipeline",
    ]


def test_per_college_stage_has_no_static_sub_agents() -> None:
    """per_college_research_and_extraction deliberately does NOT declare
    per_college_pipeline via `sub_agents=[...]` — it runs it dynamically,
    once per college, each against its own throwaway child session (see
    its docstring), so per_college_pipeline must stay unparented and free
    to be reused as a fresh Runner's root agent for each of those sessions."""
    stage = next(
        agent
        for agent in college_intake_pipeline.sub_agents
        if agent.name == "per_college_research_and_extraction"
    )
    assert stage.sub_agents == []
    assert per_college_pipeline.parent_agent is None


def test_per_college_pipeline_runs_quick_and_detailed_research_concurrently() -> None:
    """detailed_research_pipeline (college_research_agent's broad pass ->
    requirements_pipeline) and quick_research_pipeline (branding_research_
    agent -> branding_extraction_agent -> deadlines_research_agent ->
    deadlines_extraction_agent) must be genuine PARALLEL branches, not
    sequential steps — that's what lets color/logo/deadlines land without
    waiting on the broad pass's unrelated categories (essay prompts,
    recommendations, ...) to finish first. See requirements_agent.py's
    "Stage 2" comment for the full reasoning."""
    assert isinstance(per_college_pipeline, ParallelAgent)
    branch_names = {agent.name for agent in per_college_pipeline.sub_agents}
    assert branch_names == {"detailed_research_pipeline", "quick_research_pipeline"}

    detailed = next(
        a for a in per_college_pipeline.sub_agents if a.name == "detailed_research_pipeline"
    )
    assert [a.name for a in detailed.sub_agents] == [
        "college_research_agent",
        "requirements_pipeline",
    ]

    quick = next(
        a for a in per_college_pipeline.sub_agents if a.name == "quick_research_pipeline"
    )
    # Branding (research then extract) must come entirely BEFORE deadlines
    # (research then extract) — not interleaved or bundled — so color/logo
    # can land without waiting on deadline queries too.
    assert [a.name for a in quick.sub_agents] == [
        "branding_research_agent",
        "branding_extraction_agent",
        "deadlines_research_agent",
        "deadlines_extraction_agent",
    ]


def test_cross_college_analysis_runs_conflict_and_essay_matching_concurrently() -> None:
    branch_names = {agent.name for agent in cross_college_analysis.sub_agents}
    assert branch_names == {"conflict_pipeline", "essay_matching_pipeline"}
