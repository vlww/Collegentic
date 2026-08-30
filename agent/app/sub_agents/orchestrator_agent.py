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

import asyncio
import logging
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools import ToolContext
from google.adk.tools.agent_tool import AgentTool
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config, llm_timeout_config
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
# branding pass, then quick deadlines pass" comment for why the quick branch
# finishing while the detailed branch is STILL running is exactly what lets
# the Colleges table reveal color/logo/deadlines without waiting on essay
# prompts, recommendation rules, etc.
#
# Run as two INDEPENDENTLY timed-out and retried branches (see
# _run_stage_with_retry / _research_one_college below) rather than one
# ParallelAgent under a single shared Runner+timeout, which is how this
# used to be wired. Found live: quick_research_pipeline's own LLM calls can
# hit the same "hung gRPC channel — no response, no error, no timeout"
# failure mode documented on _COLLEGE_RESEARCH_TIMEOUT_SECONDS below, and
# under the old single-timeout wiring that forced a full retry of BOTH
# branches together — discarding an already-succeeded (expensive,
# broad-research) detailed_research_pipeline run just because the small
# branding/deadlines branch got stuck, and burning another full detailed
# research call on every retry. Decoupled, a stuck quick branch only
# retries itself (two small calls, cheap) and never touches the detailed
# branch's progress; see _research_one_college for why only the detailed
# branch's success is required for a college to count as "researched".
#
# Session state writes from each branch land under distinct output_keys/
# Firestore fields (see requirements_agent.py's branding_extraction_agent/
# deadlines_extraction_agent vs. requirements_agent — deliberately
# disjoint), so nothing here reads a value the other branch is mid-write on,
# which is exactly what makes fully independent sessions/runners for the
# two branches safe.

# See _run_stage_with_retry's use of these, below, for why they exist.
_DETAILED_RESEARCH_TIMEOUT_SECONDS = 240
_DETAILED_RESEARCH_MAX_ATTEMPTS = 3
# Quick research is two small, targeted calls (plus a bounded, non-LLM logo
# lookup — see requirements_agent.py's _LOGO_LOOKUP_TIMEOUT_SECONDS) rather
# than one broad google_search-grounded pass, so it gets a shorter ceiling
# than detailed research — tight enough that a genuinely stuck call is
# caught and retried well before it could ever cost as much as one detailed
# research attempt.
_QUICK_RESEARCH_TIMEOUT_SECONDS = 150
_QUICK_RESEARCH_MAX_ATTEMPTS = 3


class PerCollegeResearchAndExtraction(BaseAgent):
    """Runs detailed_research_pipeline and quick_research_pipeline for
    EVERY college in `new_college_names` concurrently — a separate, fully
    isolated child session per college per branch — instead of researching
    every newly-requested college in a single batched call, or one college
    fully at a time.

    Found live, in three steps. First: college_research_agent and
    requirements_agent each write ALL researched colleges' data to session
    state in ONE LLM call (their `output_key` replaces the whole value), so
    with every college batched into that one call, every college's data
    became known at the exact same instant. Second: looping per college
    SEQUENTIALLY (an earlier version of this class) fixed that — each
    college's row visibly completed at the real moment ITS OWN research
    finished — but for a student requesting several colleges at once, total
    wait time was N colleges x one college's research time, one full research
    pass strictly after another.

    Third, and what this class does now: colleges are researched
    CONCURRENTLY, and — see _run_stage_with_retry/_research_one_college
    below — each college's two branches (detailed_research_pipeline,
    quick_research_pipeline) ALSO run concurrently and are timed out/
    retried independently rather than as one joined unit. Each branch run
    gets its own throwaway session (a fresh Runner + InMemorySessionService,
    mirroring exactly how AgentTool.run_async spins up a child session per
    call — see google/adk/tools/agent_tool.py) seeded with ONLY
    `new_college_names` (this one college) and `college_name_to_id`. This
    isn't just a faster version of the old per-college loop — it's a
    REQUIRED fix, not an optimization: every research/extraction agent
    writes its findings to a session-state `output_key`
    (raw_research_findings, branding_research_findings, ...), and
    collect_research_sources_callback (app/callbacks.py) scans a session's
    ENTIRE event history for grounding sources. Running multiple colleges'
    pipelines against the SAME shared session concurrently would let one
    college's output_key writes clobber another's mid-flight, and would mix
    each college's citation sources into the same pool — wrong, not just
    messy (e.g. an MIT essay requirement could end up citing a source
    that's actually about Rice). Fully separate sessions make that
    impossible: each college's state lives in its own isolated dict, with
    nothing to collide with a sibling researched at the same moment.

    Firestore writes (every ft.* call in every persist callback throughout
    both branches) are NOT scoped to a session, though — they're keyed by
    user_id, so they land in the same place regardless of which child
    session made them, which is exactly what lets the Colleges table fill
    in correctly with every college's real data despite each running in
    total isolation from the others.

    Every college's row already exists by the time this runs — college_
    intake_agent creates them all up front (see its module docstring for
    why that's fast enough to do eagerly). This class starts EVERY
    college's loading-spinner lifecycle up front too (all rows flip to
    `researching=true`, `research_stage="logo"` together — see firestore_
    tools.start_college_research), then clears each one and advances
    PipelineProgress as ITS OWN task finishes, independent of the others.

    Any single college's DETAILED research failing (every retry exhausted)
    still aborts the whole turn (asyncio.TaskGroup cancels every other
    in-flight college's task the moment one raises) — consistent with
    api.py's _run_pipeline_with_auto_restart, which retries the entire
    Orchestrator turn on any failure; college_intake_agent already treats
    any college with zero Requirement docs (including one whose concurrent
    research got cancelled here) as still needing research, so a retry
    picks up exactly where this left off rather than re-doing
    already-persisted work. The QUICK branch (branding/deadlines) failing
    every retry does NOT abort anything — see _research_one_college.
    """

    def __init__(self, name: str = "per_college_research_and_extraction"):
        super().__init__(
            name=name,
            description=(
                "Researches and extracts requirements for every newly "
                "requested college CONCURRENTLY (each in its own isolated "
                "session), so the Colleges table fills in for every "
                "requested college at once rather than one at a time."
            ),
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        college_names: list[str] = list(ctx.session.state.get("new_college_names", []))
        if not college_names:
            return
        user_id = ctx.session.user_id
        # college_intake_agent already created every one of these colleges'
        # rows (and populated this mapping) up front — this only drives the
        # loading-spinner state, never row creation.
        name_to_id: dict[str, str] = dict(
            ctx.session.state.get("college_name_to_id", {})
        )

        # Every row starts spinning together, not one at a time — matches
        # the concurrency below (all colleges' research genuinely starts at
        # the same moment).
        for college_name in college_names:
            try:
                ft.start_college_research(user_id, name_to_id[college_name])
            except Exception:
                logger.warning(
                    "Failed to start research state for %r", college_name,
                    exc_info=True,
                )

        yield Event(author=self.name)

        # Two Runners (one per branch), each reused for every college's own
        # throwaway session — the same mechanism a production ADK server
        # already relies on to serve many concurrent real USERS against one
        # shared agent tree (see fast_api_app.py's own top-level `runner`),
        # just applied to N colleges x 2 branches within a single request
        # instead of N users across many requests. Two Runners rather than
        # one running per_college_pipeline (a ParallelAgent over both
        # branches) is what lets the branches below be timed out and
        # retried independently — see the comment above
        # _DETAILED_RESEARCH_TIMEOUT_SECONDS for why that split matters.
        def _make_runner(agent: BaseAgent) -> Runner:
            return Runner(
                app_name=ctx.session.app_name,
                agent=agent,
                artifact_service=ctx.artifact_service,
                session_service=InMemorySessionService(),
                memory_service=InMemoryMemoryService(),
                credential_service=ctx.credential_service,
                plugins=list(ctx.plugin_manager.plugins),
            )

        detailed_runner = _make_runner(detailed_research_pipeline)
        quick_runner = _make_runner(quick_research_pipeline)

        async def _run_stage_with_retry(
            runner: Runner,
            college_name: str,
            college_id: str,
            *,
            timeout: float,
            max_attempts: int,
            label: str,
        ) -> bool:
            """Runs `runner`'s agent once for this college, retrying in a
            fresh session up to `max_attempts` times on failure/timeout.
            Never raises — returns whether it eventually succeeded — so a
            persistently-stuck branch can't force a retry of a DIFFERENT,
            independently-run branch for the same college (found live: the
            quick branding/deadlines branch occasionally hits the same
            hung-gRPC-channel failure mode described below while the
            detailed branch researches fine, and discarding an
            already-succeeded detailed_research_pipeline run — the
            expensive one — just because the small branch got stuck is
            exactly the wasted-cost failure mode this split avoids)."""

            async def _attempt() -> None:
                session = await runner.session_service.create_session(
                    app_name=runner.app_name,
                    user_id=user_id,
                    state={
                        "new_college_names": [college_name],
                        "college_name_to_id": {college_name: college_id},
                    },
                )

                async def _drain() -> None:
                    async with Aclosing(
                        runner.run_async(
                            user_id=user_id,
                            session_id=session.id,
                            new_message=types.Content(
                                role="user",
                                parts=[types.Part.from_text(text="research")],
                            ),
                        )
                    ) as agen:
                        async for _event in agen:
                            pass

                # A ceiling so one stuck call can never hang this whole
                # request forever. Found live: running several colleges'
                # Gemini calls fully concurrently occasionally produced what
                # looked like a hung gRPC channel — no response, no error,
                # no timeout — rather than a slow-but-eventually-completing
                # call; asyncio.TaskGroup itself has no built-in timeout, so
                # without this a single stuck call blocked every other
                # (already-in-progress, otherwise completing fine) college
                # indefinitely.
                await asyncio.wait_for(_drain(), timeout=timeout)

            for attempt in range(1, max_attempts + 1):
                try:
                    await _attempt()
                    return True
                except Exception:
                    logger.warning(
                        "%s attempt %d/%d failed for %r, %s",
                        label, attempt, max_attempts, college_name,
                        "retrying" if attempt < max_attempts
                        else "giving up on this stage",
                        exc_info=True,
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(2.0)
            return False

        async def _research_one_college(college_name: str) -> None:
            college_id = name_to_id[college_name]

            # Both branches run CONCURRENTLY (asyncio.gather, not
            # sequential awaits) and are individually retried — see
            # _run_stage_with_retry. Only the detailed branch's outcome
            # determines whether this college counts as "researched": it's
            # the one that actually produces Requirement docs, which is
            # what college_intake_agent checks to decide a college still
            # needs research. The quick branch (branding/deadlines) is
            # enrichment — worth retrying on its own, but its failure
            # shouldn't void an otherwise-successful detailed research pass
            # for this college, nor abort the other colleges' concurrent
            # research below.
            detailed_ok, _quick_ok = await asyncio.gather(
                _run_stage_with_retry(
                    detailed_runner, college_name, college_id,
                    timeout=_DETAILED_RESEARCH_TIMEOUT_SECONDS,
                    max_attempts=_DETAILED_RESEARCH_MAX_ATTEMPTS,
                    label="Detailed research",
                ),
                _run_stage_with_retry(
                    quick_runner, college_name, college_id,
                    timeout=_QUICK_RESEARCH_TIMEOUT_SECONDS,
                    max_attempts=_QUICK_RESEARCH_MAX_ATTEMPTS,
                    label="Quick (branding/deadlines) research",
                ),
            )

            # Clear the loading spinner regardless of outcome — `researching`
            # doubles as college_intake_agent's "already being worked on"
            # signal (see its own comment on that check), so leaving it True
            # would make a future retry of this whole pipeline run (api.py's
            # _run_pipeline_with_auto_restart, or the student's own "Resume
            # research") skip this college forever, believing it's still in
            # flight. Found live: an earlier version only cleared this on
            # the WHOLE per-college pipeline settling, so a college whose
            # quick branch alone kept failing could leave its row appearing
            # to have "frozen" even though its (successful) requirements
            # were sitting right there.
            try:
                ft.finish_college_research(user_id, college_id)
            except Exception:
                logger.warning(
                    "Failed to clear researching flag for %r",
                    college_name, exc_info=True,
                )

            if not detailed_ok:
                # Do NOT call advance_pipeline_progress: this college's
                # requirements were never actually persisted, so counting it
                # as completed here would be a lie (found live: an earlier
                # version called this unconditionally, so a college that
                # failed every retry still advanced the progress bar to
                # 100% while its row kept reading "Not researched yet").
                # Still raises, aborting the whole TaskGroup — consistent
                # with api.py's _run_pipeline_with_auto_restart, which
                # retries the entire Orchestrator turn on any failure.
                raise RuntimeError(
                    f"Detailed research exhausted every retry for {college_name!r}"
                )

            try:
                ft.advance_pipeline_progress(user_id)
            except Exception:
                logger.warning(
                    "Failed to advance progress for %r", college_name,
                    exc_info=True,
                )

        try:
            async with asyncio.TaskGroup() as tg:
                for college_name in college_names:
                    tg.create_task(_research_one_college(college_name))
        finally:
            await detailed_runner.close()
            await quick_runner.close()


per_college_research_and_extraction = PerCollegeResearchAndExtraction()

# How many times task_planning_pipeline/priority_pipeline/readiness_pipeline
# each get retried in place — see _with_retry.
_STAGE_RETRY_MAX_ATTEMPTS = 3


def _with_retry(agent: BaseAgent, name: str, *, required: bool = True) -> BaseAgent:
    """Wraps `agent` so its whole run is retried, in place, up to
    _STAGE_RETRY_MAX_ATTEMPTS times before giving up — found live:
    task_planning_agent (a single batched LLM call over every tracked
    college's requirements) failed outright on a transient error with no
    recovery short of api.py's outer _run_pipeline_with_auto_restart
    redoing the ENTIRE turn (including per-college research that already
    succeeded). Safe to just re-run this stage from scratch: task_planning_
    pipeline/priority_pipeline/readiness_pipeline's own *ContextAgents all
    re-read straight from Firestore rather than trusting state a failed
    attempt might have partially written (same reasoning their own
    docstrings already give for re-scanning everything on every run), and
    their Firestore writes are idempotent upserts (deduped by
    source_requirement_id / college_id), so a retry never duplicates
    anything a partially-failed attempt already wrote.

    `required=False` additionally swallows the failure once every retry is
    exhausted, instead of re-raising it and aborting whatever in
    college_intake_pipeline's sub_agents list comes after this stage.
    Used for priority_pipeline: found live (a student tracking 8 colleges,
    20+ open tasks) that priority_explanation_agent's batched call can keep
    hitting DEADLINE_EXCEEDED even after every retry, and neither
    readiness_pipeline nor cross_college_analysis reads Tasks/priority at
    all (see college_intake_pipeline's own comment on that) — so letting a
    priority-scoring failure abort the rest of the run was pure collateral
    damage, and specifically why Cross-College Conflicts (conflict_pipeline,
    inside cross_college_analysis) could end up never running: it never
    even got a turn. A run that gives up here just leaves that run's tasks
    with whatever priority score/explanation they already had — the next
    successful run (or POST /tasks/recompute-priorities) fixes them up
    again, same as any other stage recomputing from scratch every time.

    Deliberately NOT wired via `sub_agents=[...]` — same reasoning as
    detailed_research_pipeline/quick_research_pipeline in
    PerCollegeResearchAndExtraction above: `agent` needs to stay unparented
    so it can keep being reused as some other Runner's own root agent
    elsewhere (task_planning_pipeline directly backs POST /tasks/replan) —
    an agent can only have one parent.
    """

    class _RetryingStage(BaseAgent):
        async def _run_async_impl(
            self, ctx: InvocationContext
        ) -> AsyncGenerator[Event, None]:
            last_exc: BaseException | None = None
            for attempt in range(1, _STAGE_RETRY_MAX_ATTEMPTS + 1):
                try:
                    async with Aclosing(agent.run_async(ctx)) as agen:
                        async for event in agen:
                            yield event
                    return
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "%s attempt %d/%d failed, %s",
                        name, attempt, _STAGE_RETRY_MAX_ATTEMPTS,
                        "retrying" if attempt < _STAGE_RETRY_MAX_ATTEMPTS
                        else "giving up",
                        exc_info=True,
                    )
                    if attempt < _STAGE_RETRY_MAX_ATTEMPTS:
                        await asyncio.sleep(2.0)
            if required:
                raise last_exc
            logger.warning(
                "%s failed after every retry and isn't required for the "
                "rest of college_intake_pipeline — continuing without it.",
                name, exc_info=last_exc,
            )

    return _RetryingStage(name=f"{name}_with_retry")


def _pipeline_stage_marker(stage: str, name: str) -> BaseAgent:
    """Tiny step that just flips PipelineProgress.stage (see its docstring)
    — lets the Colleges page show a genuinely distinct progress indicator
    for "planning tasks and scoring readiness" instead of a frozen, already-
    100%-full research progress bar for however long that remaining stretch
    takes."""

    class _StageMarker(BaseAgent):
        async def _run_async_impl(
            self, ctx: InvocationContext
        ) -> AsyncGenerator[Event, None]:
            try:
                ft.set_pipeline_stage(ctx.session.user_id, stage)
            except Exception:
                logger.warning(
                    "Failed to set pipeline stage to %r", stage, exc_info=True
                )
            yield Event(author=self.name)

    return _StageMarker(name=name)


# readiness_pipeline only reads Requirements/CollegeDeadlines/Recommendations
# (see readiness_agent.py's CollegeReadinessContextAgent) — it never reads
# Tasks, so in principle it doesn't need to wait on task_planning_pipeline/
# priority_pipeline at all. Tried running it concurrently with that chain
# (a ParallelAgent, like cross_college_analysis above) instead of after it;
# reverted — found live that two structured-output LlmAgents (priority_
# explanation_agent and readiness_explanation_agent) running concurrently
# against the SAME shared session occasionally cross-contaminated each
# other's output_schema validation (readiness's own parse getting fed
# priority's task-shaped JSON instead), unlike cross_college_analysis's
# pairing which hasn't shown this. Not worth that risk for a stage this
# cheap already (one deterministic pass + one batched LLM call) — kept
# sequential, same as task_planning_pipeline -> priority_pipeline's own
# real dependency.
college_intake_pipeline = SequentialAgent(
    name="college_intake_pipeline",
    description=(
        "Researches and extracts structured, sourced requirements for "
        "newly requested colleges, plans tasks from the full requirement "
        "set across every tracked college, scores and explains each task's "
        "priority, scores and explains every tracked college's application "
        "readiness, then detects cross-college conflicts and scores essay "
        "reuse-fit."
    ),
    sub_agents=[
        college_intake_agent,
        per_college_research_and_extraction,
        # Ordered ahead of cross_college_analysis deliberately: neither
        # reads the other's output (task_planning_agent.py's own docstring
        # notes it reasons from Requirements alone — conflict/essay-match
        # findings aren't read yet — and cross_college_analysis, per its own
        # comment below, only reads Requirements/Recommendations/
        # StudentMaterials, never Tasks/priority/readiness), so there's no
        # correctness reason for Tasks and Readiness — the two things a
        # student actually watches for right after research finishes — to
        # sit behind two more full LLM calls (conflict detection + essay
        # matching) that don't feed either of them.
        _pipeline_stage_marker("planning", "pipeline_stage_planning"),
        _with_retry(task_planning_pipeline, "task_planning_pipeline"),
        _with_retry(priority_pipeline, "priority_pipeline", required=False),
        _with_retry(readiness_pipeline, "readiness_pipeline"),
        # "essays", not "done", ahead of cross_college_analysis — that step
        # (essay_matching_pipeline + conflict_pipeline) still has real work
        # left at this point. The "done" marker used to sit HERE, before
        # cross_college_analysis ran at all: the frontend would show "Tasks
        # planned and readiness scored" — and stop polling entirely, see
        # Colleges.tsx's `pollingActive` — while essay prompts were still
        # being structured and conflicts still being detected underneath
        # it. This stage exists so EssayProgressBar (Colleges.tsx) has
        # something honest to show for that stretch instead.
        _pipeline_stage_marker("essays", "pipeline_stage_essays"),
        cross_college_analysis,
        _pipeline_stage_marker("done", "pipeline_stage_done"),
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
    generate_content_config=llm_timeout_config(),
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
