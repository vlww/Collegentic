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


# --- Colleges ---------------------------------------------------------------


def get_tracked_colleges(user_id: str) -> list[College]:
    return _read_all(_colleges(user_id), College)


def get_college(user_id: str, college_id: str) -> College | None:
    doc = _colleges(user_id).document(college_id).get()
    if not doc.exists:
        return None
    return College.model_validate({**doc.to_dict(), "id": doc.id})


def save_college(user_id: str, college: College) -> str:
    return _upsert(_colleges(user_id), college)


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
) -> None:
    """Partial update of a Requirement's own progress fields — the one place
    a STUDENT directly asserts their own completion (not an agent inference,
    so no human-in-the-loop approval gate applies here; see
    .agents-cli-spec.md § Human-in-the-Loop). Feeds
    app/tools/scoring.py's compute_readiness_score."""
    _requirements(user_id, college_id).document(requirement_id).update(
        {"status": status, "completionPercentage": completion_percentage}
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
    """Upserts explicit ids as-is. For new tasks, skips creating one if a
    task already exists for the same `source_requirement_id` — see
    .agents-cli-spec.md § Task Planning Agent ("avoid generating duplicate
    tasks")."""
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
                ids.append(existing[0].id)
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


# --- Recommendations -------------------------------------------------------


def get_recommendations(user_id: str) -> list[Recommendation]:
    return _read_all(_recommendations(user_id), Recommendation)


def save_recommendation(user_id: str, recommendation: Recommendation) -> str:
    return _upsert(_recommendations(user_id), recommendation)


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
