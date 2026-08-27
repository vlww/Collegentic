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
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from google.genai import types
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.demo_data import seed_demo_data
from app.schemas import (
    AgentRunStatus,
    ConflictStatus,
    MaterialType,
    Readiness,
    ReadinessBreakdown,
    Recommendation,
    RecommendationStatus,
    RecommenderType,
    RequirementStatus,
    StudentMaterial,
    TaskStatus,
)
from app.tools import firestore_tools as ft
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


def require_user_id(x_user_id: str | None = Header(default=None)) -> str:
    if not x_user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header is required")
    return x_user_id


@router.get("/colleges")
def list_colleges(user_id: str = Depends(require_user_id)) -> list[dict]:
    colleges = ft.get_tracked_colleges(user_id)
    return [college.model_dump(mode="json", by_alias=True) for college in colleges]


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


@router.get("/tasks")
def list_tasks(
    college_id: str | None = None, user_id: str = Depends(require_user_id)
) -> list[dict]:
    tasks = ft.get_tasks(user_id, college_id)
    return [task.model_dump(mode="json", by_alias=True) for task in tasks]


@router.post("/priorities/recompute")
def recompute_priorities(user_id: str = Depends(require_user_id)) -> list[dict]:
    """Refreshes every non-Done task's priority score AND explanation,
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
    """
    tasks = [task for task in ft.get_tasks(user_id) if task.status != TaskStatus.DONE]
    colleges_by_id = {
        college.id: college for college in ft.get_tracked_colleges(user_id)
    }
    for task in tasks:
        college = colleges_by_id.get(task.college_id) if task.college_id else None
        effective_deadline = resolve_effective_deadline(
            task.deadline, college.deadlines if college else None
        )
        breakdown = compute_priority_score(
            deadline=effective_deadline,
            estimated_minutes=task.estimated_minutes,
            required=task.required,
            status=task.status.value,
            has_dependencies=bool(task.dependencies),
            category=task.category,
        )
        ft.update_task_priority(
            user_id, task.id, breakdown.score, breakdown.explanation_facts
        )
    return [
        task.model_dump(mode="json", by_alias=True) for task in ft.get_tasks(user_id)
    ]


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
    google_search, no college_intake_pipeline) for every already-tracked
    college, overwriting logoUrl with whatever it finds now.

    Exists because the logo-picking LOGIC has changed several times without
    any of a college's underlying research changing — college_intake_agent
    only re-researches a college with zero Requirement docs, so a college
    researched under an earlier version of the picker stays stuck with
    whatever it returned back then, even after later fixes. This is the
    "just re-run today's picker against my existing colleges" escape
    hatch — safe and free to call any time, same
    deterministic-recompute-no-LLM shape as /priorities/recompute and
    /readiness/recompute above.
    """
    # Local import: requirements_agent.py constructs LlmAgent/ADK objects
    # at module load time, which needs config loaded first (dotenv) —
    # fine once the app has started (this only runs when the route is
    # actually called), but importing it at api.py's own module top level
    # would run before fast_api_app.py's load_dotenv() call.
    from app.sub_agents.requirements_agent import _fetch_college_logo

    colleges = ft.get_tracked_colleges(user_id)
    for i, college in enumerate(colleges):
        if i > 0:
            time.sleep(0.5)
        try:
            logo_url = _fetch_college_logo(college.name)
        except Exception:
            logger.warning(
                "Logo refresh failed for %r, leaving it unchanged", college.name,
                exc_info=True,
            )
            continue
        if logo_url:
            ft.update_college_branding(user_id, college.id, {"logoUrl": logo_url})
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
    StudentMaterial comes into existence; essay_analysis_agent
    (app/sub_agents/essay_matching_agent.py) only ever reads these, never
    writes or edits their text."""
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
    material = next(m for m in ft.get_student_materials(user_id) if m.id == material_id)
    return material.model_dump(mode="json", by_alias=True)


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
    return [
        match.model_dump(mode="json", by_alias=True)
        for match in ft.get_essay_matches(user_id)
    ]


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
    session = await runner.session_service.create_session(
        app_name=request.app.state.agent_app_name, user_id=user_id
    )
    # asyncio.shield, not a plain await: college_intake_pipeline runs real
    # web research across several agents and can take a minute or two, and
    # this endpoint's task is what a client disconnect (tab closed, page
    # refreshed) would cancel. Local uvicorn was confirmed NOT to do this by
    # default, but that's not guaranteed under every deployment target this
    # app runs behind (Cloud Run's request handling and any reverse proxy in
    # front of it are different code paths) — shield() makes the pipeline
    # immune to that class of cancellation regardless, at zero cost: a
    # cancelled caller still raises CancelledError here (nothing to send a
    # departed browser anyway), but _run_orchestrator keeps running to
    # completion in the background either way, matching the "autonomous-OK,
    # no approval gate" research/extraction work .agents-cli-spec.md §
    # Constraints describes.
    try:
        reply = await asyncio.shield(
            _run_orchestrator(runner, user_id, session.id, body.message)
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # An unhandled exception partway through college_intake_pipeline
        # (LLM output validation, a transient google_search error, ...)
        # otherwise leaves that turn's AgentRun docs stuck in "running"
        # forever — Agent Activity would show a pipeline that looks like
        # it's still going when it's actually dead. Close them out as
        # failed, with the real error, so a partial run is visible and
        # diagnosable instead of silently vanishing.
        logger.exception("Orchestrator pipeline failed for user %s", user_id)
        for run in ft.get_agent_runs(user_id, pipeline_run_id=session.id):
            if run.status == AgentRunStatus.RUNNING:
                ft.fail_agent_run(user_id, run.id, error_message=str(exc))  # type: ignore[arg-type]
        raise HTTPException(
            status_code=502,
            detail="Research hit an error partway through — some colleges may be "
            "incomplete. Check Agent Activity for details, then try again.",
        ) from exc
    return OrchestratorMessageResponse(reply=reply)
