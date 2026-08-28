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

import logging
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.utils.context_utils import Aclosing

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config
from app.sub_agents.college_intake_agent import college_intake_agent
from app.sub_agents.conflict_agent import conflict_pipeline
from app.sub_agents.essay_matching_agent import essay_matching_pipeline
from app.sub_agents.priority_agent import priority_pipeline
from app.sub_agents.readiness_agent import readiness_pipeline
from app.sub_agents.requirements_agent import (
    branding_extraction_agent,
    deadlines_extraction_agent,
    requirements_pipeline,
)
from app.sub_agents.research_agent import (
    branding_research_agent,
    college_research_agent,
    deadlines_research_agent,
)
from app.sub_agents.task_planning_agent import task_planning_pipeline
from app.tools import firestore_tools as ft

logger = logging.getLogger(__name__)

# .agents-cli-spec.md § Architecture step 3, now complete: conflict_pipeline
# (Milestone 10) and essay_matching_pipeline (Milestone 11) both only read
# Requirements/Recommendations/StudentMaterials — neither depends on the
# other's output — so they run concurrently, exactly as originally spec'd.
cross_college_analysis = ParallelAgent(
    name="cross_college_analysis",
    description="Detects cross-college conflicts and scores essay reuse-fit concurrently.",
    sub_agents=[conflict_pipeline, essay_matching_pipeline],
)


quick_research_pipeline = SequentialAgent(
    name="quick_research_pipeline",
    description="Researches and persists a college's branding first (the "
    "smallest, fastest possible call), then its deadlines — two separate "
    "research-then-extract steps, not one bundled call, so color/logo can "
    "land without waiting on deadline queries too.",
    sub_agents=[
        branding_research_agent,
        branding_extraction_agent,
        deadlines_research_agent,
        deadlines_extraction_agent,
    ],
)

detailed_research_pipeline = SequentialAgent(
    name="detailed_research_pipeline",
    description="Runs college_research_agent's full research call, then "
    "structures and persists the detailed Requirement + ResearchSource docs.",
    sub_agents=[college_research_agent, requirements_pipeline],
)

# Both branches research the SAME college concurrently — quick_research_
# pipeline with two small, targeted research calls (branding, then
# deadlines), detailed_research_pipeline with one much broader one (every
# other requirement category). See requirements_agent.py's "Stage 2: quick
# branding pass, then quick deadlines pass" comment for why this needs to
# be genuine concurrency (a ParallelAgent), not just a faster sequential
# step: the quick branch finishing while the detailed branch is STILL
# running is exactly what lets the Colleges table reveal color/logo/
# deadlines without waiting on essay prompts, recommendation rules, etc.
# Session state writes from each branch land under distinct output_keys/
# Firestore fields (see requirements_agent.py's branding_extraction_agent/
# deadlines_extraction_agent vs. requirements_agent — deliberately
# disjoint), so nothing here reads a value the other branch is mid-write on.
per_college_pipeline = ParallelAgent(
    name="per_college_pipeline",
    sub_agents=[detailed_research_pipeline, quick_research_pipeline],
)


class PerCollegeResearchAndExtraction(BaseAgent):
    """Runs per_college_pipeline once per college in `new_college_names`,
    one college at a time, instead of researching every newly-requested
    college in a single batched call.

    Found live, in two steps. First: college_research_agent and
    requirements_agent each write ALL researched colleges' data to session
    state in ONE LLM call (their `output_key` replaces the whole value), so
    with every college batched into that one call, every college's data
    became known at the exact same instant — no matter how requirements_
    agent.py's persist stage staggered its OWN Firestore writes afterward (a
    few hundred ms apart), the entire reveal was compressed into the last
    few seconds of an otherwise multi-minute run. Looping per college instead
    (below) fixed that — each college's row visibly completes at the real
    moment ITS OWN research finishes, spread naturally across the whole run.

    Second, within a single college's own research: college_research_agent's
    single broad research pass (deadlines, testing, recommendations, essay
    prompts, portfolio, interview, financial aid, ...) had to fully finish
    before ANY of it — including color/logo/deadlines, which have nothing to
    do with essay prompts — could be extracted and shown. per_college_
    pipeline (above) is what fixes that: quick_research_pipeline runs its
    own small, narrowly-scoped research calls genuinely CONCURRENTLY with
    detailed_research_pipeline's broad one, so color/logo/deadlines land as
    soon as those much smaller calls finish, not after the whole broad one
    does — and branding (color/logo) is researched and extracted in its OWN
    first step, before deadlines' own step even starts, so it doesn't wait
    on deadline queries either.

    Every college's row already exists by the time this loop runs —
    college_intake_agent creates them all up front (see its module
    docstring for why that's fast enough to do eagerly). This loop instead
    owns each college's loading-spinner lifecycle: flips `researching` true
    and `research_stage` to "logo" right as it reaches that college (see
    firestore_tools.start_college_research), then clears both and advances
    PipelineProgress once its requirements are persisted
    (firestore_tools.finish_college_research).

    A college's research genuinely failing partway through still aborts the
    whole turn here (no per-college try/except) — consistent with
    api.py's _run_pipeline_with_auto_restart, which retries the entire
    Orchestrator turn on any failure; college_intake_agent already treats
    any college with zero Requirement docs (including one this loop hadn't
    reached yet) as still needing research, so a retry picks up exactly
    where this loop left off rather than re-doing already-persisted work.
    """

    def __init__(self, name: str = "per_college_research_and_extraction"):
        super().__init__(
            name=name,
            description=(
                "Researches and extracts requirements for each newly "
                "requested college one at a time, so the Colleges table "
                "fills in progressively rather than all at once."
            ),
            sub_agents=[per_college_pipeline],
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        college_names: list[str] = list(ctx.session.state.get("new_college_names", []))
        if not college_names:
            return
        user_id = ctx.session.user_id
        # college_intake_agent already created every one of these colleges'
        # rows (and populated this mapping) up front — this loop only
        # drives the loading-spinner state, never row creation.
        name_to_id: dict[str, str] = dict(
            ctx.session.state.get("college_name_to_id", {})
        )
        for college_name in college_names:
            college_id = name_to_id[college_name]
            ft.start_college_research(user_id, college_id)
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        # Scopes state down to just this one college before
                        # delegating — every research agent in both
                        # branches keys its `{new_college_names?}` template
                        # off this same list, so a single-item list here is
                        # what makes each of their output keys
                        # (raw_research_findings, branding_research_
                        # findings, deadlines_research_findings, and
                        # everything downstream of them) cover exactly this
                        # one college.
                        "new_college_names": [college_name],
                    }
                ),
            )
            async with Aclosing(per_college_pipeline.run_async(ctx)) as agen:
                async for event in agen:
                    yield event
            try:
                ft.finish_college_research(user_id, college_id)
                ft.advance_pipeline_progress(user_id)
            except Exception:
                logger.warning(
                    "Failed to clear researching flag / advance progress for %r",
                    college_name,
                    exc_info=True,
                )


per_college_research_and_extraction = PerCollegeResearchAndExtraction()

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
        per_college_research_and_extraction,
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
   List them in the SAME ORDER the student mentioned them — that order
   becomes the order colleges are researched and shown in on the Colleges
   table, so if the student named Harvard first, Harvard must be first in
   this list too, not reordered.
2. Call `record_requested_colleges` with that list, in that same order.
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
