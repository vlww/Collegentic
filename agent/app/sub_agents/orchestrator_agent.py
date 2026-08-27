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

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config
from app.sub_agents.college_intake_agent import college_intake_agent
from app.sub_agents.conflict_agent import conflict_pipeline
from app.sub_agents.essay_matching_agent import essay_matching_pipeline
from app.sub_agents.priority_agent import priority_pipeline
from app.sub_agents.readiness_agent import readiness_pipeline
from app.sub_agents.requirements_agent import requirements_pipeline
from app.sub_agents.research_agent import college_research_agent
from app.sub_agents.task_planning_agent import task_planning_pipeline
from app.tools import firestore_tools as ft

# .agents-cli-spec.md § Architecture step 3, now complete: conflict_pipeline
# (Milestone 10) and essay_matching_pipeline (Milestone 11) both only read
# Requirements/Recommendations/StudentMaterials — neither depends on the
# other's output — so they run concurrently, exactly as originally spec'd.
cross_college_analysis = ParallelAgent(
    name="cross_college_analysis",
    description="Detects cross-college conflicts and scores essay reuse-fit concurrently.",
    sub_agents=[conflict_pipeline, essay_matching_pipeline],
)

college_intake_pipeline = SequentialAgent(
    name="college_intake_pipeline",
    description=(
        "Researches and extracts structured, sourced requirements for "
        "newly requested colleges, detects cross-college conflicts and "
        "scores essay reuse-fit, plans tasks from the full requirement set "
        "across every tracked college, scores and explains each task's "
        "priority, then scores and explains every tracked college's "
        "application readiness."
    ),
    sub_agents=[
        college_intake_agent,
        college_research_agent,
        requirements_pipeline,
        cross_college_analysis,
        task_planning_pipeline,
        priority_pipeline,
        readiness_pipeline,
    ],
)


def record_requested_colleges(
    college_names: list[str], tool_context: ToolContext
) -> dict:
    """Records the college names the student wants Collegentic to track.

    Call this once, with a clean list parsed from the student's message,
    before calling college_intake_pipeline.

    Args:
        college_names: College names as parsed from the student's message,
            with typos corrected and each name expanded to that school's
            full, common conversational name — what a person would actually
            say, not a shorthand or a misspelling of it (e.g. "UT
            knoxfille" -> "University of Tennessee, Knoxville", "A&M" ->
            "Texas A&M University") — unless the name they used is already
            the school's own unambiguous name (e.g. "MIT", "Georgia Tech").
            This exact string becomes the college's permanent display name
            everywhere in the app, so never pass through the student's raw
            typo or shorthand uncorrected.

    Returns:
        Confirmation of how many names were recorded.
    """
    tool_context.state["requested_colleges"] = college_names
    return {"status": "recorded", "count": len(college_names)}


def get_tracked_colleges_tool(tool_context: ToolContext) -> list[dict]:
    """Returns colleges already tracked for this student (name, status, and
    whether it still needs research).

    Use this if you want to tell the student which of their requested
    colleges are already tracked vs. newly added — never guess. Also use it
    before deciding to skip college_intake_pipeline: a tracked college can
    still have `needs_research=True` if an earlier research attempt on it
    was interrupted by an error (see .agents-cli-spec.md's pipeline error
    handling) — that's not the same as being fully researched, and still
    needs the pipeline call.
    """
    user_id = tool_context.user_id
    colleges = ft.get_tracked_colleges(user_id)
    try:
        researched_ids = {
            r.college_id for r in ft.get_requirements(user_id, [c.id for c in colleges])
        }
    except Exception:
        # Fail safe: if we can't tell, report every tracked college as
        # still needing research rather than letting this tool call — and
        # the whole orchestrator turn with it — error out over a transient
        # Firestore read.
        researched_ids = set()
    return [
        {
            "name": college.name,
            "status": college.status.value,
            "needs_research": college.id not in researched_ids,
        }
        for college in colleges
    ]


_ORCHESTRATOR_INSTRUCTION = """You are the Orchestrator for Collegentic, an
autonomous college-application taskmaster. A student tells you which
colleges they're applying to, in natural language — your job is to get
those colleges researched and tracked, then report back plainly. You do
not research or extract requirements yourself; that is entirely
college_intake_pipeline's job.

NAME NORMALIZATION IS CRITICAL — READ BEFORE PARSING: whatever string you
pass to `record_requested_colleges` becomes that college's permanent
display name, shown to the student everywhere in the app forever (the
table, readiness, deadlines, everywhere). Passing through the student's raw
typo or shorthand is a real, visible bug, not a harmless technicality.
Understand what the student means, then write the name a person would
actually SAY out loud for that school in conversation — correcting spelling
along the way — never their literal typed characters. Worked examples,
including real mistakes seen live:
  - "UT knoxfille" (typo + shorthand) -> "University of Tennessee, Knoxville"
  - "A&M" -> "Texas A&M University"
  - "UT" alone -> "University of Texas at Austin"
  - "harverd" -> "Harvard University"
  - "MIT", "Georgia Tech", "Caltech", "UCLA" -> unchanged (already each
    school's own unambiguous name/nickname, not a typo or a multi-school
    abbreviation)
Only ask the student which school they mean when a name is genuinely
ambiguous with no standard default referent at all (e.g. "Miami" alone,
evenly split between Ohio and Florida) — never ask just to confirm a
correction you're already confident about.

YOUR STEPS, IN ORDER:
1. Parse the student's message into a clean list of college names, applying
   NAME NORMALIZATION above to every single one before doing anything else.
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
   requirement, etc.), and roughly how many tasks were planned, translating
   all of it into plain sentences, never pasting raw JSON or internal field
   names. If anything came back flagged for verification, say so plainly
   rather than glossing over it. If any cross-college conflicts were
   detected (see CONFLICTS below), mention the genuinely important ones,
   like a real recommendation gap or deadline clustering the student should
   know about, in plain language.

Write in plain, ordinary prose: no markdown (no **bold**, no bullet lists,
no headers, no backtick code spans) and no em dashes. Use commas and
periods the way you'd write a normal text message to a friend.

If the student's message names zero colleges, ask them which colleges
they're applying to — do not call any tools yet. If every college they
named is already tracked AND `get_tracked_colleges` shows `needs_research`
false for every one of them, say so and skip calling
`college_intake_pipeline` (there's genuinely nothing to research). But if
any named college is tracked with `needs_research` true (an earlier
research attempt on it was interrupted by an error — e.g. the student is
retrying after being told to), still call `college_intake_pipeline` — do
NOT skip it just because the college is "already tracked"; the pipeline
will pick that college back up and finish it, and no-op for any college
that's genuinely already done.

FULL PIPELINE CONTEXT (populated only after college_intake_pipeline
returns — empty before that, ignore it until then):
RESEARCH FINDINGS: {raw_research_findings?}
CONFLICTS: {detected_conflicts?}
ESSAY ANALYSIS: {essay_analysis?}
PLANNED TASKS: {planned_tasks?}
READINESS: {college_readiness_context?}"""


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
