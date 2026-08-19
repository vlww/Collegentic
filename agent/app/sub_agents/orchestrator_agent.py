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

"""Orchestrator Agent — .agents-cli-spec.md § Orchestrator Agent.

Parses a student's natural-language message into a list of college names,
then runs `college_intake_pipeline` (college_intake_agent ->
college_research_agent -> requirements_pipeline, Milestones 3-4) and
summarizes the result in plain language. Does no research or extraction
itself — "the Orchestrator should not perform every specialized task
itself" (spec).

Wiring choice: the intake pipeline is attached via `AgentTool`, not
`sub_agents=[...]` transfer. ADK's docs now nudge toward `mode='single_turn'`
sub-agents for the simple one-LlmAgent-as-tool case, but that flag lives on
`LlmAgent` only — `college_intake_pipeline` is a `SequentialAgent` tree, and
`AgentTool` is what generically supports wrapping a composite tree. It also
gives the behavior this agent actually needs: control returns to the
Orchestrator after the pipeline finishes (a plain `sub_agents` transfer
would end the turn on the pipeline's raw structured JSON output instead),
and state flows both ways — confirmed by reading AgentTool's source
(google/adk/tools/agent_tool.py): it seeds the child session from a copy of
the caller's state (so `requested_colleges`, set below, reaches
college_intake_agent) and forwards every `state_delta` back to the parent
(so `raw_research_findings`, `extracted_requirements`, etc. all land back
in the Orchestrator's own session state after the call returns).

No approval gate before researching/extracting — unlike deep-search's
plan-then-approve flow. .agents-cli-spec.md § Constraints lists research,
requirement extraction, and derived-state updates as autonomous-OK; adding
an approval step here would also contradict § Welcome / Initial Setup's
"onboarding should be lightweight, not a repetitive questionnaire."
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config
from app.sub_agents.college_intake_agent import college_intake_agent
from app.sub_agents.priority_agent import priority_pipeline
from app.sub_agents.requirements_agent import requirements_pipeline
from app.sub_agents.research_agent import college_research_agent
from app.sub_agents.task_planning_agent import task_planning_pipeline
from app.tools import firestore_tools as ft

college_intake_pipeline = SequentialAgent(
    name="college_intake_pipeline",
    description=(
        "Researches and extracts structured, sourced requirements for "
        "newly requested colleges, plans tasks from the full requirement "
        "set across every tracked college, then scores and explains each "
        "task's priority."
    ),
    sub_agents=[
        college_intake_agent,
        college_research_agent,
        requirements_pipeline,
        task_planning_pipeline,
        priority_pipeline,
    ],
)


def record_requested_colleges(
    college_names: list[str], tool_context: ToolContext
) -> dict:
    """Records the college names the student wants Collegentic to track.

    Call this once, with a clean list parsed from the student's message,
    before calling college_intake_pipeline.

    Args:
        college_names: College names as parsed from the student's message —
            use their own phrasing/spelling unless it's genuinely ambiguous.

    Returns:
        Confirmation of how many names were recorded.
    """
    tool_context.state["requested_colleges"] = college_names
    return {"status": "recorded", "count": len(college_names)}


def get_tracked_colleges_tool(tool_context: ToolContext) -> list[dict]:
    """Returns colleges already tracked for this student (name + status).

    Use this if you want to tell the student which of their requested
    colleges are already tracked vs. newly added — never guess.
    """
    colleges = ft.get_tracked_colleges(tool_context.user_id)
    return [
        {"name": college.name, "status": college.status.value} for college in colleges
    ]


_ORCHESTRATOR_INSTRUCTION = """You are the Orchestrator for Collegentic, an
autonomous college-application taskmaster. A student tells you which
colleges they're applying to, in natural language — your job is to get
those colleges researched and tracked, then report back plainly. You do
not research or extract requirements yourself; that is entirely
college_intake_pipeline's job.

YOUR STEPS, IN ORDER:
1. Parse the student's message into a clean list of college names. Use the
   names/spelling they gave you unless it's genuinely ambiguous (e.g.
   "Miami" alone is ambiguous between Ohio and Florida — ask which one
   rather than guessing).
2. Call `record_requested_colleges` with that list.
3. Call `college_intake_pipeline` (pass a short one-line request string,
   e.g. "Research and track these colleges.") to research, extract
   requirements, and plan tasks for any newly added colleges. This runs
   real web research and can take a while — that's expected, do not treat
   it as an error. The tool's own return value is just the final planned
   task list (JSON) — for a richer summary, the full pipeline's state is
   available below once the call completes.
4. Once it returns, write a SHORT, friendly, plain-language summary for the
   student: how many colleges were researched, 1-2 genuinely notable
   things you found per college (a hard deadline, an unusual recommendation
   requirement, etc.), and roughly how many tasks were planned — translate
   all of it into plain sentences, never paste raw JSON or internal field
   names. If anything came back flagged for verification, say so plainly
   rather than glossing over it.

If the student's message names zero colleges, ask them which colleges
they're applying to — do not call any tools yet. If every college they
named is already tracked, say so via `get_tracked_colleges` and skip
calling `college_intake_pipeline` (there's nothing new to research).

FULL PIPELINE CONTEXT (populated only after college_intake_pipeline
returns — empty before that, ignore it until then):
RESEARCH FINDINGS: {raw_research_findings?}
PLANNED TASKS: {planned_tasks?}"""


orchestrator_agent = LlmAgent(
    model=config.worker_model,
    name="orchestrator_agent",
    description=(
        "Parses which colleges a student is applying to and coordinates "
        "researching and tracking them — never researches or extracts "
        "requirements itself."
    ),
    instruction=_ORCHESTRATOR_INSTRUCTION,
    tools=[
        record_requested_colleges,
        get_tracked_colleges_tool,
        AgentTool(college_intake_pipeline),
    ],
    before_agent_callback=log_agent_run_start,
    after_agent_callback=log_agent_run_complete,
)
