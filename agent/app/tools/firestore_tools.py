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

"""Firestore read/write layer — the only module in the app that talks to
Firestore directly. See .agents-cli-spec.md § Firestore Schema for the
collection layout and § Constraints for why every write takes (or builds) a
validated `app.schemas` model rather than a raw dict.

There is no login yet: `user_id` is the client-generated UUID from
.agents-cli-spec.md § Data Sources & Auth — every function is scoped under
`users/{user_id}/...` and callers are trusted to pass the right one.

These are plain, JSON-in/Pydantic-out Python functions, not ADK tools yet.
Milestone 3+ wraps the subset an LLM agent actually needs behind thin
functions with JSON-serializable signatures (ADK tool-calling only passes
JSON-serializable arguments, never Python objects).

Deliberately avoids Firestore `collection_group` queries: our subcollections
(`requirements`, `essayPrompts`) repeat under every user, and a
collection_group query has no built-in per-user scoping. Cross-college reads
loop over the caller-supplied college ids instead — more reads, no
cross-tenant leak risk, fine at this scale.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import lru_cache
from typing import TypeVar

from google.cloud import firestore
from google.cloud.firestore_v1 import CollectionReference, FieldFilter

from app.schemas import (
    AgentRun,
    AgentRunStatus,
    College,
    Conflict,
    ConflictStatus,
    EssayMatch,
    EssayPrompt,
    FirestoreModel,
    PendingAction,
    PendingActionStatus,
    PipelineProgress,
    Readiness,
    Recommendation,
    Requirement,
    ResearchSource,
    StudentMaterial,
    Task,
    UserProfile,
)

ModelT = TypeVar("ModelT", bound=FirestoreModel)


@lru_cache(maxsize=1)
def _client() -> firestore.Client:
    return firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))


def now() -> datetime:
    return datetime.now(UTC)


# --- Path helpers -------------------------------------------------------


def _user_doc(user_id: str):
    return _client().collection("users").document(user_id)


def _colleges(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("colleges")


def _requirements(user_id: str, college_id: str) -> CollectionReference:
    return _colleges(user_id).document(college_id).collection("requirements")


def _research_sources(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("researchSources")


def _materials(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("materials")


def _essay_prompts(user_id: str, college_id: str) -> CollectionReference:
    return _colleges(user_id).document(college_id).collection("essayPrompts")


def _essay_matches(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("essayMatches")


def _tasks(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("tasks")


def _recommendations(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("recommendations")


def _conflicts(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("conflicts")


def _agent_runs(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("agentRuns")


def _pending_actions(user_id: str) -> CollectionReference:
    return _user_doc(user_id).collection("pendingActions")


def _pipeline_progress_doc(user_id: str):
    """Single doc (id always "current"), not a growing collection — see
    PipelineProgress's docstring."""
    return _user_doc(user_id).collection("pipelineProgress").document("current")


# --- Generic read/write helpers ----------------------------------------


def _read_all(collection: CollectionReference, model_cls: type[ModelT]) -> list[ModelT]:
    return [
        model_cls.model_validate({**doc.to_dict(), "id": doc.id})
        for doc in collection.stream()
    ]


def _upsert(collection: CollectionReference, model: ModelT) -> str:
    """Create (auto id) if `model.id` is unset, else overwrite that doc."""
    payload = model.model_dump(by_alias=True, exclude={"id"}, exclude_none=True)
    if model.id:
        collection.document(model.id).set(payload)
        return model.id
    _, doc_ref = collection.add(payload)
    return doc_ref.id


def _batch_upsert(
    items: Iterable[ModelT], collection_for: Callable[[ModelT], CollectionReference]
) -> list[str]:
    """Upsert many models in one commit. `collection_for` picks the target
    collection per item, so callers whose items nest under different parents
    (e.g. requirements under different colleges) still get one atomic batch.
    """
    batch = _client().batch()
    ids: list[str] = []
    for item in items:
        collection = collection_for(item)
        doc_ref = collection.document(item.id) if item.id else collection.document()
        payload = item.model_dump(by_alias=True, exclude={"id"}, exclude_none=True)
        batch.set(doc_ref, payload)
        ids.append(doc_ref.id)
    batch.commit()
    return ids


# --- users/{userId} -------------------------------------------------------


def get_user_profile(user_id: str) -> UserProfile | None:
    doc = _user_doc(user_id).get()
    if not doc.exists:
        return None
    return UserProfile.model_validate(doc.to_dict())


def save_user_profile(user_id: str, profile: UserProfile) -> None:
    payload = profile.model_dump(by_alias=True, exclude={"id"}, exclude_none=True)
    _user_doc(user_id).set(payload, merge=True)


_TEST_SCORES_SUBMITTED_FIELD = "testScoresSubmitted"


def get_test_scores_submitted(user_id: str) -> bool:
    """Whether the student has submitted standardized test scores — a
    single account-wide answer (My Progress), not per college: unlike
    Requirements, a test score isn't something a college's own research
    produces. Stored directly on the user doc rather than folded into
    UserProfile, which a LIVE (non-demo) account never otherwise has one
    of (see get_user_profile) — this needs to read/write independently of
    that doc's own required fields."""
    doc = _user_doc(user_id).get()
    if not doc.exists:
        return False
    return bool((doc.to_dict() or {}).get(_TEST_SCORES_SUBMITTED_FIELD, False))


def set_test_scores_submitted(user_id: str, submitted: bool) -> None:
    _user_doc(user_id).set({_TEST_SCORES_SUBMITTED_FIELD: submitted}, merge=True)


# --- Colleges ---------------------------------------------------------------


def get_tracked_colleges(user_id: str) -> list[College]:
    """Sorted by `created_at` — the order colleges were actually added in,
    which (per orchestrator_agent.py's PerCollegeResearchAndExtraction) now
    matches the order the student listed them in, so the Colleges table
    reads top-to-bottom the same way the student typed it. Sorted in
    Python, not via Firestore `.order_by("createdAt")`: a query ordered on
    a field excludes any document missing that field entirely, and every
    College doc from before this field existed (including every demo-seeded
    one — see demo_data.py) has no `created_at` at all, so an `order_by`
    query would silently drop them from the table."""
    colleges = _read_all(_colleges(user_id), College)
    return sorted(colleges, key=lambda c: c.created_at or datetime.min.replace(tzinfo=UTC))


def get_college(user_id: str, college_id: str) -> College | None:
    doc = _colleges(user_id).document(college_id).get()
    if not doc.exists:
        return None
    return College.model_validate({**doc.to_dict(), "id": doc.id})


def save_college(user_id: str, college: College) -> str:
    return _upsert(_colleges(user_id), college)


def create_college_placeholder(user_id: str, name: str) -> str:
    """Creates a brand-new College doc for every newly requested college
    right away (see college_intake_agent.py) — NOT researching yet
    (`researching` stays its False default), just a named row appearing on
    the table so a judge sees the full requested list take shape fast
    (this is pure Firestore bookkeeping, no LLM/search call, so it's cheap
    to do for every college up front), before the actual per-college
    research (orchestrator_agent.py's PerCollegeResearchAndExtraction) runs
    for every college concurrently. `created_at` is what
    get_tracked_colleges sorts by, so rows land in request order — research
    completion order can (and usually does) differ."""
    return save_college(user_id, College(name=name, created_at=now()))


def start_college_research(user_id: str, college_id: str) -> None:
    """Called right as PerCollegeResearchAndExtraction's loop reaches this
    college — flips on the loading-spinner signal and starts the field
    sequence at "logo" (see College.research_stage's docstring)."""
    _colleges(user_id).document(college_id).update(
        {"researching": True, "researchStage": "logo"}
    )


def advance_research_stage(user_id: str, college_id: str, stage: str) -> None:
    """Moves the ONE active loading spinner to `stage` — see
    College.research_stage's docstring for the field order this steps
    through."""
    _colleges(user_id).document(college_id).update({"researchStage": stage})


def finish_college_research(user_id: str, college_id: str) -> None:
    """Called once this college's requirements are fully persisted — clears
    every transient in-progress signal so no cell is left showing a
    spinner forever."""
    _colleges(user_id).document(college_id).update(
        {"researching": False, "researchStage": None}
    )


def save_readiness(user_id: str, college_id: str, readiness: Readiness) -> None:
    payload = readiness.model_dump(by_alias=True, exclude_none=True)
    _colleges(user_id).document(college_id).update({"readiness": payload})


def update_college_deadlines(
    user_id: str, college_id: str, fields: dict[str, str]
) -> None:
    """Partial update of College.deadlines — `fields` maps "ea"/"ed"/"rd"/
    "financialAid" to an ISO date string. Uses Firestore dot-path updates so
    fields not present in `fields` are left untouched, not clobbered."""
    if not fields:
        return
    payload = {
        f"deadlines.{key}": datetime.fromisoformat(value)
        for key, value in fields.items()
    }
    _colleges(user_id).document(college_id).update(payload)


def update_college_branding(
    user_id: str, college_id: str, fields: dict[str, str]
) -> None:
    """Partial update of College.schoolColors/logoUrl — `fields` maps
    "primary"/"secondary"/"logoUrl" to a value. Dot-path updates like
    update_college_deadlines, so setting only a primary color (say) doesn't
    clobber a secondary color set in an earlier research pass."""
    if not fields:
        return
    payload = {
        ("logoUrl" if key == "logoUrl" else f"schoolColors.{key}"): value
        for key, value in fields.items()
    }
    _colleges(user_id).document(college_id).update(payload)


# --- Requirements -------------------------------------------------------


def save_requirements(user_id: str, requirements: list[Requirement]) -> list[str]:
    return _batch_upsert(requirements, lambda r: _requirements(user_id, r.college_id))


def get_requirements(user_id: str, college_ids: list[str]) -> list[Requirement]:
    """Requirements live under colleges/{collegeId}/requirements, so a
    cross-college read is one query per college id rather than a
    collection_group scan (see module docstring)."""
    results: list[Requirement] = []
    for college_id in college_ids:
        results.extend(_read_all(_requirements(user_id, college_id), Requirement))
    return results


def update_requirement_progress(
    user_id: str,
    college_id: str,
    requirement_id: str,
    status: str,
    completion_percentage: float,
    student_notes: str | None = None,
) -> None:
    """Partial update of a Requirement's own progress fields — the one place
    a STUDENT directly asserts their own completion (not an agent inference,
    so no human-in-the-loop approval gate applies here; see
    .agents-cli-spec.md § Human-in-the-Loop). status/completionPercentage
    feed app/tools/scoring.py's compute_readiness_score; studentNotes is a
    free-text aside (e.g. an actual test score) the formula never reads, so
    it's fine to always overwrite alongside them — the frontend always
    submits the row's current notes value together with any status change,
    never just one or the other."""
    _requirements(user_id, college_id).document(requirement_id).update(
        {
            "status": status,
            "completionPercentage": completion_percentage,
            "studentNotes": student_notes,
        }
    )


# --- Research sources ---------------------------------------------------


def save_research_sources(user_id: str, sources: list[ResearchSource]) -> list[str]:
    return _batch_upsert(sources, lambda _s: _research_sources(user_id))


def get_research_sources(
    user_id: str, college_id: str | None = None
) -> list[ResearchSource]:
    query = _research_sources(user_id)
    if college_id:
        query = query.where(filter=FieldFilter("collegeId", "==", college_id))
    return _read_all(query, ResearchSource)


def get_research_sources_by_ids(
    user_id: str, source_ids: list[str]
) -> list[ResearchSource]:
    """Powers the "View Source" UI: a Requirement stores `source_ids`
    (specific doc ids), not a college_id filter, so this fetches those exact
    docs rather than querying by field."""
    collection = _research_sources(user_id)
    docs = (collection.document(source_id).get() for source_id in source_ids)
    return [
        ResearchSource.model_validate({**doc.to_dict(), "id": doc.id})
        for doc in docs
        if doc.exists
    ]


# --- Student materials (essays/activities/notes — never agent-edited) ---


def get_student_materials(user_id: str) -> list[StudentMaterial]:
    return _read_all(_materials(user_id), StudentMaterial)


def save_student_material(user_id: str, material: StudentMaterial) -> str:
    if material.created_at is None:
        material.created_at = now()
    material.updated_at = now()
    return _upsert(_materials(user_id), material)


# --- Essay prompts + matches ---------------------------------------------


def save_essay_prompts(user_id: str, prompts: list[EssayPrompt]) -> list[str]:
    return _batch_upsert(prompts, lambda p: _essay_prompts(user_id, p.college_id))


def get_essay_prompts(user_id: str, college_id: str) -> list[EssayPrompt]:
    return _read_all(_essay_prompts(user_id, college_id), EssayPrompt)


def save_essay_matches(user_id: str, matches: list[EssayMatch]) -> list[str]:
    return _batch_upsert(matches, lambda _m: _essay_matches(user_id))


def get_essay_matches(user_id: str) -> list[EssayMatch]:
    return _read_all(_essay_matches(user_id), EssayMatch)


# --- Tasks (dedupe-aware) ------------------------------------------------


def get_tasks(user_id: str, college_id: str | None = None) -> list[Task]:
    query = _tasks(user_id)
    if college_id:
        query = query.where(filter=FieldFilter("collegeId", "==", college_id))
    return _read_all(query, Task)


def save_tasks(user_id: str, tasks: list[Task]) -> list[str]:
    """Upserts explicit ids as-is. For new tasks (no `id`), matches by
    `source_requirement_id` to avoid duplicate tasks on re-runs — see
    .agents-cli-spec.md § Task Planning Agent ("avoid generating duplicate
    tasks"). When a match is found, refreshes title/description/category in
    place instead of leaving the original untouched: those three are pure
    LLM-synthesis output (task_planning_agent.py's ExtractedTask) with no
    other writer and no independent lifecycle, so a re-plan (e.g. after a
    prompt change, or `POST /tasks/replan`) should update them rather than
    leave a stale title stuck forever. Everything else — status, deadline,
    estimated_minutes, priority_score/explanation, dependencies — is left
    alone: those either have their own dedicated write path
    (update_task_priority) or are documented write-once elsewhere
    (Task.deadline, see app/api.py's recompute_priorities)."""
    collection = _tasks(user_id)
    ids: list[str] = []
    for task in tasks:
        if task.id:
            ids.append(_upsert(collection, task))
            continue
        if task.source_requirement_id:
            existing = list(
                collection.where(
                    filter=FieldFilter(
                        "sourceRequirementId", "==", task.source_requirement_id
                    )
                )
                .limit(1)
                .stream()
            )
            if existing:
                existing_id = existing[0].id
                collection.document(existing_id).update(
                    {
                        "title": task.title,
                        "description": task.description,
                        "category": task.category,
                    }
                )
                ids.append(existing_id)
                continue
        ids.append(_upsert(collection, task))
    return ids


def update_task_priority(
    user_id: str, task_id: str, score: float, explanation: str
) -> None:
    """Partial update of a Task's priority fields — Milestone 8's Priority
    Agent calls this once per task after computing scoring.py's deterministic
    score and an LLM-composed explanation for it."""
    _tasks(user_id).document(task_id).update(
        {"priorityScore": score, "priorityExplanation": explanation}
    )


def batch_update_task_priorities(
    user_id: str, updates: list[tuple[str, float, str]]
) -> None:
    """Same partial update as `update_task_priority`, for many tasks in one
    commit — app/api.py's recompute_priorities used to issue one sequential
    `.update()` per task, which is what made switching to the Dashboard take
    several seconds once a student had more than a handful of open tasks."""
    if not updates:
        return
    collection = _tasks(user_id)
    batch = _client().batch()
    for task_id, score, explanation in updates:
        batch.update(
            collection.document(task_id),
            {"priorityScore": score, "priorityExplanation": explanation},
        )
    batch.commit()


# --- Recommendations -------------------------------------------------------


def get_recommendations(user_id: str) -> list[Recommendation]:
    return _read_all(_recommendations(user_id), Recommendation)


def save_recommendation(user_id: str, recommendation: Recommendation) -> str:
    return _upsert(_recommendations(user_id), recommendation)


def delete_recommendation(user_id: str, recommendation_id: str) -> None:
    _recommendations(user_id).document(recommendation_id).delete()


# --- Conflicts ------------------------------------------------------------


def get_conflicts(user_id: str) -> list[Conflict]:
    return _read_all(_conflicts(user_id), Conflict)


def save_conflicts(user_id: str, conflicts: list[Conflict]) -> list[str]:
    return _batch_upsert(conflicts, lambda _c: _conflicts(user_id))


def update_conflict_status(
    user_id: str, conflict_id: str, status: ConflictStatus
) -> None:
    """Powers both the student's Acknowledge/Resolve actions (app/api.py) and
    the Conflict Agent's own auto-resolve-if-no-longer-detected step
    (app/sub_agents/conflict_agent.py) — never reopens a conflict, only ever
    moves it toward acknowledged/resolved."""
    _conflicts(user_id).document(conflict_id).update({"status": status.value})


# --- Delete -----------------------------------------------------------------


def delete_college(user_id: str, college_id: str) -> None:
    """Removes a College doc and everything derived from researching it, so
    dropping it from the list doesn't leave orphaned rows visible elsewhere
    in the app: its requirements/essayPrompts subcollections, researchSources,
    tasks, and essayMatches all get deleted outright (nothing else references
    them); a Conflict naming this college gets deleted too, since a conflict
    about a college that no longer exists isn't meaningful; a Recommendation
    naming this college among others just has the id stripped out of its
    list (deleted outright only if this was its last college), since a
    recommender request can span colleges that shouldn't disappear with one
    of them.

    One batch commit: a partial delete would be worse than the original
    state (student sees the college gone from the list but its tasks/
    conflicts still lingering elsewhere with a now-dangling college_id)."""
    batch = _client().batch()

    for doc in _requirements(user_id, college_id).stream():
        batch.delete(doc.reference)
    for doc in _essay_prompts(user_id, college_id).stream():
        batch.delete(doc.reference)
    for doc in _research_sources(user_id).where(
        filter=FieldFilter("collegeId", "==", college_id)
    ).stream():
        batch.delete(doc.reference)
    for doc in _tasks(user_id).where(
        filter=FieldFilter("collegeId", "==", college_id)
    ).stream():
        batch.delete(doc.reference)
    for doc in _essay_matches(user_id).where(
        filter=FieldFilter("collegeId", "==", college_id)
    ).stream():
        batch.delete(doc.reference)
    for doc in _conflicts(user_id).where(
        filter=FieldFilter("collegeIds", "array_contains", college_id)
    ).stream():
        batch.delete(doc.reference)
    for doc in _recommendations(user_id).where(
        filter=FieldFilter("collegeIds", "array_contains", college_id)
    ).stream():
        remaining = [cid for cid in doc.to_dict().get("collegeIds", []) if cid != college_id]
        if remaining:
            batch.update(doc.reference, {"collegeIds": remaining})
        else:
            batch.delete(doc.reference)

    batch.delete(_colleges(user_id).document(college_id))
    batch.commit()


# --- Agent activity ---------------------------------------------------------


def start_agent_run(
    user_id: str,
    pipeline_run_id: str,
    agent_name: str,
    related_college_ids: list[str] | None = None,
) -> str:
    run = AgentRun(
        pipeline_run_id=pipeline_run_id,
        agent_name=agent_name,
        status=AgentRunStatus.RUNNING,
        started_at=now(),
        related_college_ids=related_college_ids or [],
    )
    return _upsert(_agent_runs(user_id), run)


def seed_agent_run(
    user_id: str,
    pipeline_run_id: str,
    agent_name: str,
    started_at: datetime,
    completed_at: datetime,
    summary: str,
) -> str:
    """Writes a fully-formed, already-completed AgentRun with explicit
    (possibly backdated) timestamps — used only by app/demo_data.py to seed
    a plausible-looking activity history for Demo Mode. Real pipeline runs
    always go through start_agent_run/complete_agent_run instead, which
    stamp `now()` themselves at the moment each actually happens."""
    run = AgentRun(
        pipeline_run_id=pipeline_run_id,
        agent_name=agent_name,
        status=AgentRunStatus.COMPLETED,
        started_at=started_at,
        completed_at=completed_at,
        summary=summary,
    )
    return _upsert(_agent_runs(user_id), run)


def complete_agent_run(user_id: str, run_id: str, summary: str) -> None:
    _agent_runs(user_id).document(run_id).update(
        {
            "status": AgentRunStatus.COMPLETED.value,
            "completedAt": now(),
            "summary": summary,
        }
    )


def fail_agent_run(user_id: str, run_id: str, error_message: str) -> None:
    _agent_runs(user_id).document(run_id).update(
        {
            "status": AgentRunStatus.FAILED.value,
            "completedAt": now(),
            "errorMessage": error_message,
        }
    )


def get_agent_runs(user_id: str, pipeline_run_id: str | None = None) -> list[AgentRun]:
    """Sorted in Python, not via `.order_by()`: combining that with the
    `pipelineRunId` equality filter needs a Firestore composite index, and
    a pipeline's run count is small enough that client-side sort is free."""
    query = _agent_runs(user_id)
    if pipeline_run_id:
        query = query.where(filter=FieldFilter("pipelineRunId", "==", pipeline_run_id))
    return sorted(_read_all(query, AgentRun), key=lambda run: run.started_at)


# --- Pipeline progress (for the Colleges page's progress bar) ----------


def start_pipeline_progress(user_id: str, total_colleges: int) -> None:
    """Called once, right when the Orchestrator knows the full list of
    colleges to research for this run (before any of their rows exist yet
    — see college_intake_agent.py) — this is what lets the frontend show
    "2 of 4 colleges researched" the instant a run starts, not only once
    every college's row has already appeared. Colleges are now researched
    concurrently (see orchestrator_agent.py's PerCollegeResearchAndExtraction),
    so completed_colleges climbs in whatever order they actually finish in,
    not necessarily 1, 2, 3... — the frontend's progress bar is worded as a
    plain count for exactly this reason, not "college N" implying a single
    one currently in progress. Overwrites any previous run's doc; only one
    run is ever in flight per user at a time."""
    progress = PipelineProgress(total_colleges=total_colleges, completed_colleges=0)
    _pipeline_progress_doc(user_id).set(
        progress.model_dump(by_alias=True, exclude={"id"}, exclude_none=True)
    )


def advance_pipeline_progress(user_id: str) -> None:
    """Called once per college, right after its requirements are persisted
    — see orchestrator_agent.py's PerCollegeResearchAndExtraction. Uses an
    atomic Firestore increment specifically because colleges are researched
    concurrently now, so multiple calls can genuinely race each other."""
    _pipeline_progress_doc(user_id).update(
        {"completedColleges": firestore.Increment(1)}
    )


def get_pipeline_progress(user_id: str) -> PipelineProgress | None:
    doc = _pipeline_progress_doc(user_id).get()
    if not doc.exists:
        return None
    return PipelineProgress.model_validate({**doc.to_dict(), "id": doc.id})


# --- Human-in-the-loop pending actions ---------------------------------


def create_pending_action(user_id: str, action: PendingAction) -> str:
    return _upsert(_pending_actions(user_id), action)


def get_pending_actions(
    user_id: str, status: PendingActionStatus | None = None
) -> list[PendingAction]:
    query = _pending_actions(user_id)
    if status:
        query = query.where(filter=FieldFilter("status", "==", status.value))
    return _read_all(query, PendingAction)


def resolve_pending_action(
    user_id: str, action_id: str, approve: bool
) -> PendingAction:
    ref = _pending_actions(user_id).document(action_id)
    status = PendingActionStatus.APPROVED if approve else PendingActionStatus.REJECTED
    ref.update({"status": status.value, "resolvedAt": now()})
    doc = ref.get()
    return PendingAction.model_validate({**doc.to_dict(), "id": doc.id})
