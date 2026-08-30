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

"""REST API for the frontend: read-only Firestore CRUD + one route that
invokes the Orchestrator. Mounted onto the ADK-generated FastAPI app via a
single `app.include_router(api_router)` call in fast_api_app.py — additive,
doesn't touch the generated serving/session/A2A wiring.

Every route is scoped by an `X-User-Id` header — the client-generated UUID
from .agents-cli-spec.md § Data Sources & Auth (no login yet).

GET routes are plain `def`, not `async def`: the Firestore client
(`google-cloud-firestore`) is synchronous, and FastAPI runs sync route
functions in a threadpool automatically so they don't block the event loop.
The orchestrator route is `async def` because `Runner.run_async` is a
coroutine.

Each call to /orchestrator/messages creates a fresh session on the app's
shared session service (app.state.runner, set up in fast_api_app.py's
lifespan) rather than reusing one across requests — the frontend doesn't
yet support multi-turn back-and-forth with the Orchestrator (e.g. answering
a disambiguation question), just one-shot "here are my colleges" submissions.
Revisit when a real chat surface (Student Advisor Agent) is built.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.config import config
from app.demo_data import seed_demo_data
from app.schemas import (
    AgentRunStatus,
    College,
    ConflictStatus,
    MaterialType,
    Readiness,
    ReadinessBreakdown,
    Recommendation,
    RecommendationStatus,
    RecommenderType,
    RequirementStatus,
    StudentMaterial,
    Task,
    TaskStatus,
)
from app.sub_agents.task_planning_agent import task_planning_pipeline
from app.tools import firestore_tools as ft
from app.tools.essay_matching import recompute_essay_matches
from app.tools.grammar_check import check_grammar
from app.tools.scoring import (
    compute_priority_score,
    compute_readiness_score,
    recommendations_for_college,
    resolve_effective_deadline,
)

# No "/api" prefix here: the frontend's Vite dev proxy (and, per the plan,
# Cloud Run's static-serving setup later) strips a leading "/api" from every
# request before forwarding to this backend — matching /health and every
# ADK-generated route (/run_sse, /apps/..., etc.), none of which carry that
# prefix either. The frontend always calls "/api/...".
router = APIRouter()
logger = logging.getLogger(__name__)


async def _run_pipeline_with_auto_restart(
    user_id: str,
    create_session,
    run_session,
    failure_detail: str,
):
    """Runs `run_session(session)` against a freshly created `session`, and
    if it raises, automatically restarts the ENTIRE pipeline from scratch —
    a brand-new session, the same input — up to config.max_pipeline_attempts
    times before giving up.

    An unhandled exception partway through a pipeline (LLM output
    validation, a transient google_search/Firestore error, ...) used to
    leave that turn's AgentRun docs stuck "running" forever and require a
    human to notice the error and manually resend the exact same request to
    recover — awkward for a student, and worse for a hackathon judge who
    isn't hosting/babysitting this themselves. Every pipeline this backs
    (college_intake_pipeline via the Orchestrator, task_planning_pipeline
    via /tasks/replan) is already built to resume cleanly from a fresh run
    of the same input rather than duplicating work or corrupting state —
    e.g. college_intake_agent only re-researches a college with zero
    Requirement docs (see its module docstring: "that's what makes 'resume
    after an error' work by just re-submitting the same names") — so
    retrying automatically here, instead of surfacing the error and waiting
    for someone to retry it by hand, is safe and closes that gap.

    Each failed attempt's still-"running" AgentRun docs are marked failed
    (for Agent Activity visibility) before the next attempt starts, exactly
    as a single failed run always was.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, config.max_pipeline_attempts + 1):
        session = await create_session()
        try:
            # asyncio.shield, not a plain await: these pipelines run real
            # web research and can take a minute or two, and a client
            # disconnect (tab closed, page refreshed) mid-attempt shouldn't
            # cancel the pipeline out from under itself — see
            # send_orchestrator_message's original docstring note for the
            # full reasoning (local uvicorn doesn't cancel on disconnect,
            # but that's not guaranteed under every deployment target).
            return await asyncio.shield(run_session(session))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            logger.exception(
                "Pipeline run failed for user %s (attempt %d/%d)",
                user_id, attempt, config.max_pipeline_attempts,
            )
            for run in ft.get_agent_runs(user_id, pipeline_run_id=session.id):
                if run.status == AgentRunStatus.RUNNING:
                    ft.fail_agent_run(user_id, run.id, error_message=str(exc))  # type: ignore[arg-type]
    raise HTTPException(status_code=502, detail=failure_detail) from last_exc


def require_user_id(x_user_id: str | None = Header(default=None)) -> str:
    if not x_user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header is required")
    return x_user_id


@router.get("/colleges")
def list_colleges(user_id: str = Depends(require_user_id)) -> list[dict]:
    colleges = ft.get_tracked_colleges(user_id)
    return [college.model_dump(mode="json", by_alias=True) for college in colleges]


@router.get("/pipeline-progress")
def get_pipeline_progress(user_id: str = Depends(require_user_id)) -> dict | None:
    """Powers the Colleges page's progress bar — see
    firestore_tools.start_pipeline_progress's docstring for why this exists
    separately from just counting rows in `colleges`. Polled only while a
    research submission is in flight; null once nothing has ever run."""
    progress = ft.get_pipeline_progress(user_id)
    return progress.model_dump(mode="json", by_alias=True) if progress else None


@router.get("/colleges/{college_id}")
def get_college(college_id: str, user_id: str = Depends(require_user_id)) -> dict:
    college = ft.get_college(user_id, college_id)
    if college is None:
        raise HTTPException(status_code=404, detail="College not found")
    return college.model_dump(mode="json", by_alias=True)


@router.delete("/colleges/{college_id}")
def delete_college(college_id: str, user_id: str = Depends(require_user_id)) -> dict:
    """Drops a college the student isn't applying to after all — see
    ft.delete_college for the full cleanup (requirements, essay prompts,
    research sources, tasks, essay matches, conflicts, recommendations)."""
    if ft.get_college(user_id, college_id) is None:
        raise HTTPException(status_code=404, detail="College not found")
    ft.delete_college(user_id, college_id)
    return {"id": college_id}


@router.get("/requirements")
def list_requirements(
    college_ids: str | None = None, user_id: str = Depends(require_user_id)
) -> list[dict]:
    """`college_ids` is an optional comma-separated list; omitted means
    every requirement across every tracked college (for the cross-college
    Requirements page)."""
    if college_ids:
        ids = [i for i in college_ids.split(",") if i]
    else:
        ids = [college.id for college in ft.get_tracked_colleges(user_id)]
    requirements = ft.get_requirements(user_id, ids)
    return [req.model_dump(mode="json", by_alias=True) for req in requirements]


class RequirementProgressUpdate(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    status: RequirementStatus
    completion_percentage: float | None = None
    student_notes: str | None = None


# A requirement's completion_percentage when the caller sets only `status` —
# lets the Requirements page offer one status dropdown per requirement
# rather than a second percentage input, while still feeding
# compute_readiness_score a graduated (not binary) completion signal. The
# caller can still pass an explicit completion_percentage to override this.
_STATUS_DEFAULT_COMPLETION = {
    RequirementStatus.NOT_STARTED: 0.0,
    RequirementStatus.PLANNING: 15.0,
    RequirementStatus.IN_PROGRESS: 40.0,
    RequirementStatus.NEARLY_COMPLETE: 75.0,
    RequirementStatus.COMPLETE: 100.0,
    RequirementStatus.SUBMITTED: 100.0,
    RequirementStatus.VERIFIED: 100.0,
}


@router.patch("/colleges/{college_id}/requirements/{requirement_id}")
def update_requirement_progress(
    college_id: str,
    requirement_id: str,
    body: RequirementProgressUpdate,
    user_id: str = Depends(require_user_id),
) -> dict:
    """The one place a student directly asserts their own progress on a
    requirement (e.g. "I've drafted this essay") — not an agent inference,
    so no human-in-the-loop approval gate applies (.agents-cli-spec.md §
    Human-in-the-Loop only gates agent-derived completions). Feeds
    compute_readiness_score; the frontend calls POST /readiness/recompute
    right after this to refresh the affected college's score."""
    completion_percentage = (
        body.completion_percentage
        if body.completion_percentage is not None
        else _STATUS_DEFAULT_COMPLETION[body.status]
    )
    ft.update_requirement_progress(
        user_id,
        college_id,
        requirement_id,
        body.status.value,
        completion_percentage,
        body.student_notes,
    )
    return {"status": "ok"}


def _effective_deadline(task: Task, colleges_by_id: dict[str, College]) -> datetime | None:
    college = colleges_by_id.get(task.college_id) if task.college_id else None
    return resolve_effective_deadline(task.deadline, college.deadlines if college else None)


# Matches a whole clause/sentence mentioning verification — e.g. "Note:
# double-check details if needed." task_planning_agent.py's instructions no
# longer generate this (the Tasks page's confidence badge already covers
# it), but tasks planned before that change still have it stored verbatim;
# stripped at read time rather than requiring every account to re-plan.
_VERIFICATION_CLAUSE_RE = re.compile(
    r"(?:^|(?<=[.!?]\s))[^.!?]*\b(?:verify|double-check|double check)\b[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)
# Matches only an "X to Y words recommended" RANGE — not a plain "650 words"
# limit, and not a genuine required range like "250-650 words" (no
# "recommended"), which is real constraint info worth keeping. This is
# specifically the extra "recommended" range some school pages publish on
# top of the actual limit — noise, per requirements_agent.py's description
# field instruction.
_WORD_RANGE_RE = re.compile(
    r"\(?\s*\d+\s*(?:-|to)\s*\d+\s*words?\s*recommended\s*\)?",
    re.IGNORECASE,
)


def _clean_task_description(description: str | None) -> str | None:
    if not description:
        return description
    cleaned = _VERIFICATION_CLAUSE_RE.sub("", description)
    cleaned = _WORD_RANGE_RE.sub("", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s+([.!?,;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or None


def _dump_task(task: Task, effective_deadline: datetime | None) -> dict:
    """Same `Task` JSON shape every route already returns, plus
    `effectiveDeadline` — see recompute_priorities' docstring for why this
    exists: most tasks have no `deadline` of their own, so callers that
    display a date (Today's Priorities, the Tasks page) need the resolved
    college-deadline fallback rather than a mostly-null field."""
    return {
        **task.model_dump(mode="json", by_alias=True),
        "description": _clean_task_description(task.description),
        "effectiveDeadline": effective_deadline.isoformat() if effective_deadline else None,
    }


@router.get("/tasks")
def list_tasks(
    college_id: str | None = None, user_id: str = Depends(require_user_id)
) -> list[dict]:
    tasks = ft.get_tasks(user_id, college_id)
    colleges_by_id = {
        college.id: college for college in ft.get_tracked_colleges(user_id)
    }
    return [_dump_task(task, _effective_deadline(task, colleges_by_id)) for task in tasks]


@router.post("/tasks/replan")
async def replan_tasks(user_id: str = Depends(require_user_id)) -> list[dict]:
    """Re-runs task_planning_pipeline directly, for every already-tracked
    college, bypassing orchestrator_agent's own "skip college_intake_pipeline
    if everything's already researched" judgment call — the only way an
    already-researched college's tasks would otherwise get replanned is
    naming a new college in the same /orchestrator/messages turn (which
    re-scans existing colleges' requirements as a side effect) or a failed-
    run retry. A student who just wants task_planning_agent's latest output
    (e.g. after its title-format instructions changed) shouldn't have to
    re-add every college to get it.

    task_planning_pipeline is self-contained by design (TaskContextAgent
    reads Requirements straight from Firestore rather than trusting
    upstream pipeline state — see task_planning_agent.py's module
    docstring), so it's safe to run in isolation like this; the same
    InMemoryRunner shape already backs
    tests/integration/test_task_planning_agent.py. Existing tasks get their
    title/description/category refreshed in place rather than duplicated
    (see firestore_tools.save_tasks).
    """
    runner = InMemoryRunner(agent=task_planning_pipeline, app_name="task_replan")

    async def _create_session():
        return await runner.session_service.create_session(
            app_name="task_replan",
            user_id=user_id,
            state={"force_full_replan": True},
        )

    async def _run(session) -> None:
        async for _ in runner.run_async(
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text="replan")]
            ),
            user_id=user_id,
            session_id=session.id,
        ):
            pass

    await _run_pipeline_with_auto_restart(
        user_id,
        _create_session,
        _run,
        failure_detail="Refreshing tasks hit an error partway through, even after "
        "automatically retrying. Check Agent Activity for details, then try "
        "again.",
    )
    colleges_by_id = {
        college.id: college for college in ft.get_tracked_colleges(user_id)
    }
    return [
        _dump_task(task, _effective_deadline(task, colleges_by_id))
        for task in ft.get_tasks(user_id)
    ]


@router.post("/priorities/recompute")
def recompute_priorities(
    limit: int | None = None, user_id: str = Depends(require_user_id)
) -> list[dict]:
    """Refreshes non-Done tasks' priority score AND explanation,
    deterministically — no LLM call (app/tools/scoring.py). Deadlines march
    forward daily even when no new college research happens, so the full
    agent pipeline (app/sub_agents/priority_agent.py, which additionally
    rewrites the explanation as a nicer LLM sentence) isn't the only way
    scores get refreshed.

    Overwrites the explanation with the freshly-computed `explanation_facts`
    (plain but 100% accurate), rather than preserving whatever sentence was
    last written — found live (Milestone 8): leaving the old LLM sentence in
    place while the score moved on produced a self-contradicting result (a
    task the badge now read as "Medium priority" whose own explanation text
    still said "score of 34.0", because that sentence had literally baked in
    the pre-recompute number). A plain, current sentence beats a polished,
    wrong one.

    `limit`: Today's Priorities only ever displays the top 5, and scoring
    itself is pure math (cheap) — the actual cost is Firestore round trips.
    So every open task still gets scored in memory, but only the top `limit`
    get their score persisted (one batched write) and returned, instead of
    every open task getting its own sequential `.update()` plus a full
    re-fetch at the end. Omit `limit` for the Tasks page's "Refresh", which
    needs every task's score written and returned.

    Each returned task also carries an `effectiveDeadline` — the same
    college-deadline fallback used for scoring (see
    resolve_effective_deadline's docstring for why most tasks have no
    `deadline` of their own), so callers like Today's Priorities can show a
    real date instead of "-" without duplicating that resolution logic
    client-side. `Task.deadline` itself is still never overwritten in
    Firestore.
    """
    all_tasks = ft.get_tasks(user_id)
    open_tasks = [task for task in all_tasks if task.status != TaskStatus.DONE]
    colleges_by_id = {
        college.id: college for college in ft.get_tracked_colleges(user_id)
    }

    scored: list[tuple[Task, float, str, datetime | None]] = []
    for task in open_tasks:
        effective_deadline = _effective_deadline(task, colleges_by_id)
        breakdown = compute_priority_score(
            deadline=effective_deadline,
            estimated_minutes=task.estimated_minutes,
            required=task.required,
            status=task.status.value,
            has_dependencies=bool(task.dependencies),
            category=task.category,
        )
        scored.append(
            (task, breakdown.score, breakdown.explanation_facts, effective_deadline)
        )
    scored.sort(key=lambda item: item[1], reverse=True)

    to_persist = scored[:limit] if limit is not None else scored
    ft.batch_update_task_priorities(
        user_id,
        [
            (task.id, score, explanation)
            for task, score, explanation, _ in to_persist
        ],
    )

    if limit is not None:
        return [_dump_task(task, deadline) for task, score, _, deadline in to_persist]

    for task, score, explanation, _ in to_persist:
        task.priority_score = score
        task.priority_explanation = explanation
    done_tasks = [task for task in all_tasks if task.status == TaskStatus.DONE]
    deadline_by_task_id = {task.id: deadline for task, _, _, deadline in scored}
    return [
        _dump_task(task, deadline_by_task_id.get(task.id)) for task in open_tasks
    ] + [_dump_task(task, _effective_deadline(task, colleges_by_id)) for task in done_tasks]


@router.post("/readiness/recompute")
def recompute_readiness(user_id: str = Depends(require_user_id)) -> list[dict]:
    """Refreshes every tracked college's readiness score AND breakdown,
    deterministically — no LLM call (app/tools/scoring.py), same reasoning
    as /priorities/recompute. Called by the frontend right after a manual
    requirement-progress update so the Readiness page reflects it
    immediately rather than waiting for the next full pipeline run.

    Overwrites `explanation` with the freshly-computed `explanation_facts`
    (plain but accurate) rather than preserving a stale LLM sentence — same
    self-contradiction bug recompute_priorities fixes (Milestone 8): a score
    that moved on while its old sentence still cited the previous number.
    """
    colleges = ft.get_tracked_colleges(user_id)
    all_recommendations = ft.get_recommendations(user_id)
    test_scores_submitted = ft.get_test_scores_submitted(user_id)
    for college in colleges:
        requirements = ft.get_requirements(user_id, [college.id])
        # Same guard as readiness_agent.py's CollegeReadinessContextAgent —
        # a college with zero requirements hasn't actually been researched
        # yet, so scoring it would just persist compute_readiness_score's
        # vacuous "owes nothing" default (a flat 80%) as if it were real.
        if not requirements:
            continue
        college_recommendations = recommendations_for_college(
            all_recommendations, college.id
        )
        result = compute_readiness_score(
            requirements, college.deadlines, college_recommendations, test_scores_submitted
        )
        readiness = Readiness(
            score=result.score,
            breakdown=ReadinessBreakdown(
                essays=result.essays,
                recommendations=result.recommendations,
                testing=result.testing,
                deadline=result.deadline,
            ),
            explanation=result.explanation_facts,
            computed_at=ft.now(),
        )
        ft.save_readiness(user_id, college.id, readiness)
    return [
        college.model_dump(mode="json", by_alias=True)
        for college in ft.get_tracked_colleges(user_id)
    ]


# --- My Progress: account-wide test scores + recommendations ----------------
# Both are self-reported once per student, not per college — see
# app/tools/scoring.py's compute_readiness_score for how each feeds
# readiness. Neither route recomputes readiness itself; the frontend calls
# POST /readiness/recompute right after, same pattern as
# update_requirement_progress above.


@router.get("/test-scores")
def get_test_scores(user_id: str = Depends(require_user_id)) -> dict:
    return {"submitted": ft.get_test_scores_submitted(user_id)}


class TestScoresUpdate(BaseModel):
    submitted: bool


@router.put("/test-scores")
def update_test_scores(
    body: TestScoresUpdate, user_id: str = Depends(require_user_id)
) -> dict:
    ft.set_test_scores_submitted(user_id, body.submitted)
    return {"submitted": body.submitted}


@router.get("/recommendations")
def list_recommendations(user_id: str = Depends(require_user_id)) -> list[dict]:
    return [
        rec.model_dump(mode="json", by_alias=True)
        for rec in ft.get_recommendations(user_id)
    ]


class RecommendationInput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    recommender_name: str | None = None
    recommender_type: RecommenderType
    status: RecommendationStatus = RecommendationStatus.NOT_REQUESTED
    college_ids: list[str] = []


@router.post("/recommendations")
def create_recommendation(
    body: RecommendationInput, user_id: str = Depends(require_user_id)
) -> dict:
    rec_id = ft.save_recommendation(user_id, Recommendation(**body.model_dump()))
    return {"id": rec_id}


@router.patch("/recommendations/{recommendation_id}")
def update_recommendation(
    recommendation_id: str,
    body: RecommendationInput,
    user_id: str = Depends(require_user_id),
) -> dict:
    ft.save_recommendation(
        user_id, Recommendation(id=recommendation_id, **body.model_dump())
    )
    return {"id": recommendation_id}


@router.delete("/recommendations/{recommendation_id}")
def delete_recommendation(
    recommendation_id: str, user_id: str = Depends(require_user_id)
) -> dict:
    ft.delete_recommendation(user_id, recommendation_id)
    return {"id": recommendation_id}


@router.post("/colleges/refresh-logos")
def refresh_college_logos(user_id: str = Depends(require_user_id)) -> list[dict]:
    """Re-runs just the deterministic logo lookup (app/sub_agents/
    requirements_agent.py's _fetch_college_logo — no LLM call, no
    google_search, no college_intake_pipeline) and re-applies any pinned
    school-color override (_KNOWN_SCHOOL_COLORS), for every already-tracked
    college — overwriting logoUrl/schoolColors with whatever they resolve to
    now.

    Exists because the logo-picking LOGIC (and, now, the color overrides)
    have changed several times without any of a college's underlying
    research changing — college_intake_agent only re-researches a college
    with zero Requirement docs, so a college researched under an earlier
    version of the picker, or before a school got a color pinned, stays
    stuck with whatever it returned back then, even after later fixes. This
    is the "just re-run today's picker against my existing colleges" escape
    hatch — safe and free to call any time, same
    deterministic-recompute-no-LLM shape as /priorities/recompute and
    /readiness/recompute above.
    """
    # Local import: requirements_agent.py constructs LlmAgent/ADK objects
    # at module load time, which needs config loaded first (dotenv) —
    # fine once the app has started (this only runs when the route is
    # actually called), but importing it at api.py's own module top level
    # would run before fast_api_app.py's load_dotenv() call.
    from app.sub_agents.requirements_agent import (
        _KNOWN_SCHOOL_COLORS,
        _fetch_college_logo,
        _known_college_key,
    )

    colleges = ft.get_tracked_colleges(user_id)
    for i, college in enumerate(colleges):
        if i > 0:
            time.sleep(0.5)
        fields: dict[str, str] = dict(
            _KNOWN_SCHOOL_COLORS.get(_known_college_key(college.name), {})
        )
        try:
            logo_url = _fetch_college_logo(college.name)
        except Exception:
            logger.warning(
                "Logo refresh failed for %r, leaving it unchanged", college.name,
                exc_info=True,
            )
            logo_url = None
        if logo_url:
            fields["logoUrl"] = logo_url
        if fields:
            ft.update_college_branding(user_id, college.id, fields)
    return [
        college.model_dump(mode="json", by_alias=True)
        for college in ft.get_tracked_colleges(user_id)
    ]


@router.get("/conflicts")
def list_conflicts(user_id: str = Depends(require_user_id)) -> list[dict]:
    return [
        conflict.model_dump(mode="json", by_alias=True)
        for conflict in ft.get_conflicts(user_id)
    ]


@router.post("/conflicts/{conflict_id}/acknowledge")
def acknowledge_conflict(
    conflict_id: str, user_id: str = Depends(require_user_id)
) -> dict:
    """The student has seen this conflict and is handling it themselves —
    keeps it visible (not resolved) but out of an "unseen" filter, if the
    frontend adds one later."""
    ft.update_conflict_status(user_id, conflict_id, ConflictStatus.ACKNOWLEDGED)
    return {"status": "ok"}


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: str, user_id: str = Depends(require_user_id)) -> dict:
    """The student has dealt with this conflict. A future conflict_agent run
    won't reopen it even if it re-detects the same underlying facts — see
    app/sub_agents/conflict_agent.py's fingerprint-merge docstring."""
    ft.update_conflict_status(user_id, conflict_id, ConflictStatus.RESOLVED)
    return {"status": "ok"}


class CreateMaterialRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    title: str
    type: MaterialType
    topic: str | None = None
    description: str | None = None
    partial_text: str | None = None
    word_count: int | None = None


@router.get("/materials")
def list_materials(user_id: str = Depends(require_user_id)) -> list[dict]:
    return [
        material.model_dump(mode="json", by_alias=True)
        for material in ft.get_student_materials(user_id)
    ]


@router.post("/materials")
def create_material(
    body: CreateMaterialRequest, user_id: str = Depends(require_user_id)
) -> dict:
    """The student's own essay/activity/note library — .agents-cli-spec.md
    § Constraints: "never edited by agents." This is the only way a
    StudentMaterial comes into existence; essay_matching_pipeline
    (app/sub_agents/essay_matching_agent.py) only ever reads these, never
    writes or edits their text.

    Recomputes essay matches synchronously right after saving — the fast,
    deterministic categorizer in app/tools/essay_matching.py is cheap
    enough (no LLM, no network call) to run inline here rather than
    waiting for the next college-research pipeline run. Without this, a
    student adding a material saw the Essay Map add the node with no
    connections until they happened to research another college — not
    slow, just never triggered."""
    material_id = ft.save_student_material(
        user_id,
        StudentMaterial(
            title=body.title,
            type=body.type,
            topic=body.topic,
            description=body.description,
            partial_text=body.partial_text,
            word_count=body.word_count,
        ),
    )
    recompute_essay_matches(user_id)
    material = next(m for m in ft.get_student_materials(user_id) if m.id == material_id)
    return material.model_dump(mode="json", by_alias=True)


@router.put("/materials/{material_id}")
def update_material(
    material_id: str, body: CreateMaterialRequest, user_id: str = Depends(require_user_id)
) -> dict:
    """The student editing their own existing material (Essays' "Your
    Materials" edit icon) — same "never edited by agents" constraint as
    create_material above, just overwriting title/type/topic/description/
    partialText/wordCount on the existing doc instead of making a new one.
    model_copy off the existing record (not a fresh StudentMaterial) so id,
    createdAt, and any agent-derived fields (completionPercentage, themes,
    status) survive the edit untouched."""
    existing = next((m for m in ft.get_student_materials(user_id) if m.id == material_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="Material not found")
    updated = existing.model_copy(
        update={
            "title": body.title,
            "type": body.type,
            "topic": body.topic,
            "description": body.description,
            "partial_text": body.partial_text,
            "word_count": body.word_count,
        }
    )
    ft.save_student_material(user_id, updated)
    # A material's category can change with an edit (e.g. its topic now
    # reads as "greatest challenge" instead of "why this major") — recompute
    # rather than leave a stale match pointing at the old category.
    recompute_essay_matches(user_id)
    material = next(m for m in ft.get_student_materials(user_id) if m.id == material_id)
    return material.model_dump(mode="json", by_alias=True)


@router.delete("/materials/{material_id}")
def delete_material(material_id: str, user_id: str = Depends(require_user_id)) -> dict:
    """The student removing one of their own materials (Essays' "Your
    Materials" trash icon) — same 404-if-missing / recompute-after shape as
    update_material above. recompute_essay_matches both re-matches any
    prompt that had this material as its best fit against whatever's left
    in its category, and (see essay_matching.py's orphan cleanup) deletes
    the match doc outright if nothing remains."""
    if not any(m.id == material_id for m in ft.get_student_materials(user_id)):
        raise HTTPException(status_code=404, detail="Material not found")
    ft.delete_student_material(user_id, material_id)
    recompute_essay_matches(user_id)
    return {"id": material_id}


@router.get("/essay-prompts")
def list_essay_prompts(
    college_ids: str | None = None, user_id: str = Depends(require_user_id)
) -> list[dict]:
    if college_ids:
        ids = [i for i in college_ids.split(",") if i]
    else:
        ids = [college.id for college in ft.get_tracked_colleges(user_id)]
    prompts = [
        prompt
        for college_id in ids
        for prompt in ft.get_essay_prompts(user_id, college_id)
    ]
    return [prompt.model_dump(mode="json", by_alias=True) for prompt in prompts]


@router.get("/essay-matches")
def list_essay_matches(user_id: str = Depends(require_user_id)) -> list[dict]:
    """Recomputes before reading, not just relying on the write-side
    triggers in create_material/update_material/essay_matching_pipeline —
    found live: those cover a material or college changing AFTER this
    endpoint's other triggers exist, but say nothing about data already in
    Firestore from before recompute_essay_matches was wired up (or added in
    the "wrong" order relative to it), which stays stuck at zero matches
    forever with no write ever happening again to re-trigger it. Cheap
    (pure Python, no network/LLM call — see essay_matching.py's module
    docstring), so recomputing on every read keeps this endpoint always
    correct instead of trusting stale writes."""
    recompute_essay_matches(user_id)
    return [
        match.model_dump(mode="json", by_alias=True)
        for match in ft.get_essay_matches(user_id)
    ]


class GrammarCheckRequest(BaseModel):
    text: str


@router.post("/grammar-check")
def grammar_check(
    body: GrammarCheckRequest, user_id: str = Depends(require_user_id)
) -> dict:
    """Essay Editor's "Check grammar" button — grammar/spelling/punctuation
    only (app/tools/grammar_check.py), on whatever text the student
    currently has in the editor. Takes raw `text` in the request body
    rather than a material id: the student may be checking unsaved edits
    that haven't gone through PUT /materials/{id} yet, and this doesn't
    read or write Firestore either way — X-User-Id is still required, same
    as every other route, purely for consistency.
    """
    issues = check_grammar(body.text)
    return {"issues": [issue.model_dump(mode="json", by_alias=True) for issue in issues]}


@router.get("/agent-runs")
def list_agent_runs(user_id: str = Depends(require_user_id)) -> list[dict]:
    """Powers the Agent Activity page — ft.get_agent_runs already returns
    every run sorted by startedAt; the frontend groups by pipelineRunId
    into one card per pipeline execution."""
    return [
        run.model_dump(mode="json", by_alias=True) for run in ft.get_agent_runs(user_id)
    ]


@router.post("/demo/seed")
def seed_demo(user_id: str = Depends(require_user_id)) -> dict:
    """Populates a full fictional student profile for `user_id` —
    .agents-cli-spec.md Example Use Case 2 ("Try Demo Mode"). Same
    X-User-Id-scoped pattern as every other route: the frontend mints a
    fresh id for the demo session (never reuses one) and just calls this
    once against it, so concurrent judges never collide. See
    app/demo_data.py for why this is hand-authored data, not a live
    pipeline run."""
    seed_demo_data(user_id)
    return {"status": "ok"}


@router.get("/research-sources")
def list_research_sources(
    ids: str, user_id: str = Depends(require_user_id)
) -> list[dict]:
    """`ids` is a required comma-separated list of ResearchSource doc ids —
    used by the "View Source" detail view. Empty result for any id that
    doesn't exist, rather than a 404, since callers typically batch-request
    every source a requirement cites."""
    id_list = [i for i in ids.split(",") if i]
    sources = ft.get_research_sources_by_ids(user_id, id_list)
    return [source.model_dump(mode="json", by_alias=True) for source in sources]


class OrchestratorMessageRequest(BaseModel):
    message: str


class OrchestratorMessageResponse(BaseModel):
    reply: str


async def _run_orchestrator(runner, user_id: str, session_id: str, message: str) -> str:
    reply_parts: list[str] = []
    async for event in runner.run_async(
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=message)]),
        user_id=user_id,
        session_id=session_id,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    reply_parts.append(part.text)
    return "".join(reply_parts)


@router.post("/orchestrator/messages")
async def send_orchestrator_message(
    body: OrchestratorMessageRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> OrchestratorMessageResponse:
    runner = request.app.state.runner
    agent_app_name = request.app.state.agent_app_name

    async def _create_session():
        return await runner.session_service.create_session(
            app_name=agent_app_name, user_id=user_id
        )

    async def _run(session) -> str:
        return await _run_orchestrator(runner, user_id, session.id, body.message)

    reply = await _run_pipeline_with_auto_restart(
        user_id,
        _create_session,
        _run,
        failure_detail="Research hit an error partway through, even after "
        "automatically retrying. Some colleges may be incomplete. Check "
        "Agent Activity for details.",
    )
    return OrchestratorMessageResponse(reply=reply)
