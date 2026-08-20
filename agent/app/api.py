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

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from google.genai import types
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.schemas import (
    ConflictStatus,
    MaterialType,
    Readiness,
    ReadinessBreakdown,
    RequirementStatus,
    StudentMaterial,
    TaskStatus,
)
from app.tools import firestore_tools as ft
from app.tools.scoring import (
    compute_priority_score,
    compute_readiness_score,
    resolve_effective_deadline,
)

# No "/api" prefix here: the frontend's Vite dev proxy (and, per the plan,
# Cloud Run's static-serving setup later) strips a leading "/api" from every
# request before forwarding to this backend — matching /health and every
# ADK-generated route (/run_sse, /apps/..., etc.), none of which carry that
# prefix either. The frontend always calls "/api/...".
router = APIRouter()


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
        user_id, college_id, requirement_id, body.status.value, completion_percentage
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
    for college in colleges:
        requirements = ft.get_requirements(user_id, [college.id])
        result = compute_readiness_score(requirements, college.deadlines)
        readiness = Readiness(
            score=result.score,
            breakdown=ReadinessBreakdown(
                requirements=result.requirements,
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
    reply_parts: list[str] = []
    async for event in runner.run_async(
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=body.message)]
        ),
        user_id=user_id,
        session_id=session.id,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    reply_parts.append(part.text)
    return OrchestratorMessageResponse(reply="".join(reply_parts))
