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

"""Live round-trip tests against the real `collegentic-hackathon` Firestore
database (free tier — a handful of docs per run costs nothing). Every test
writes under a throwaway `user_id` and the fixture deletes everything it
created, so repeated runs never accumulate data.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.schemas import (
    AgentRunStatus,
    College,
    ConfidenceLevel,
    PendingAction,
    Recommendation,
    RecommenderType,
    Requirement,
    ResearchSource,
    Task,
)
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    # Teardown: delete every doc this test could have created, including
    # requirements nested under colleges.
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for coll_fn in (
        ft._tasks,
        ft._agent_runs,
        ft._pending_actions,
        ft._recommendations,
        ft._research_sources,
    ):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()
    ft._user_doc(uid).delete()


def test_save_and_get_college_round_trip(user_id: str) -> None:
    college_id = ft.save_college(
        user_id, College(name="MIT", application_type="CommonApp")
    )
    fetched = ft.get_college(user_id, college_id)
    assert fetched is not None
    assert fetched.name == "MIT"
    assert fetched.id == college_id

    tracked = ft.get_tracked_colleges(user_id)
    assert [c.id for c in tracked] == [college_id]


def test_save_and_get_requirements_across_colleges(user_id: str) -> None:
    mit_id = ft.save_college(user_id, College(name="MIT"))
    rice_id = ft.save_college(user_id, College(name="Rice"))

    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=mit_id,
                type="essay",
                description="Why MIT",
                confidence=ConfidenceLevel.HIGH,
            ),
            Requirement(
                college_id=rice_id,
                type="essay",
                description="Why Rice",
                confidence=ConfidenceLevel.LOW,
                needs_verification=True,
            ),
        ],
    )

    combined = ft.get_requirements(user_id, [mit_id, rice_id])
    assert len(combined) == 2
    by_college = {r.college_id: r for r in combined}
    assert by_college[mit_id].confidence == ConfidenceLevel.HIGH
    assert by_college[rice_id].needs_verification is True

    mit_only = ft.get_requirements(user_id, [mit_id])
    assert len(mit_only) == 1


def test_save_tasks_deduplicates_by_source_requirement(user_id: str) -> None:
    college_id = ft.save_college(user_id, College(name="Stanford"))
    [requirement_id] = ft.save_requirements(
        user_id,
        [Requirement(college_id=college_id, type="essay", description="Essay")],
    )

    first_ids = ft.save_tasks(
        user_id,
        [Task(title="Draft essay", source_requirement_id=requirement_id)],
    )
    second_ids = ft.save_tasks(
        user_id,
        [Task(title="Draft essay (again)", source_requirement_id=requirement_id)],
    )

    assert (
        first_ids == second_ids
    )  # second call found the existing task, didn't duplicate it
    assert len(ft.get_tasks(user_id)) == 1


def test_pending_action_create_and_resolve(user_id: str) -> None:
    action_id = ft.create_pending_action(
        user_id,
        PendingAction(
            type="mark_requirement_complete",
            description="Mark MIT essay complete based on inference",
            proposed_change={"requirementId": "abc", "status": "Complete"},
            created_by_agent="task_planning_agent",
            created_at=datetime.now(UTC),
        ),
    )
    pending = ft.get_pending_actions(user_id)
    assert len(pending) == 1
    assert pending[0].id == action_id

    resolved = ft.resolve_pending_action(user_id, action_id, approve=True)
    assert resolved.status.value == "approved"
    assert resolved.resolved_at is not None


def test_agent_run_lifecycle(user_id: str) -> None:
    run_id = ft.start_agent_run(
        user_id, pipeline_run_id="run-1", agent_name="college_research_agent"
    )
    ft.complete_agent_run(user_id, run_id, summary="Researched 1 college.")

    runs = ft.get_agent_runs(user_id, pipeline_run_id="run-1")
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.COMPLETED
    assert runs[0].summary == "Researched 1 college."


def test_save_recommendation_round_trip(user_id: str) -> None:
    rec_id = ft.save_recommendation(
        user_id,
        Recommendation(
            recommender_type=RecommenderType.TEACHER_STEM,
            college_ids=["mit", "rice"],
        ),
    )
    recs = ft.get_recommendations(user_id)
    assert len(recs) == 1
    assert recs[0].id == rec_id
    assert recs[0].status.value == "NotRequested"


def test_delete_recommendation(user_id: str) -> None:
    rec_id = ft.save_recommendation(
        user_id, Recommendation(recommender_type=RecommenderType.OTHER)
    )
    ft.delete_recommendation(user_id, rec_id)
    assert ft.get_recommendations(user_id) == []


def test_test_scores_submitted_defaults_false_then_round_trips(user_id: str) -> None:
    assert ft.get_test_scores_submitted(user_id) is False
    ft.set_test_scores_submitted(user_id, True)
    assert ft.get_test_scores_submitted(user_id) is True


def test_test_score_details_default_then_round_trips(user_id: str) -> None:
    assert ft.get_test_score_details(user_id) == {"kind": "SAT", "score": ""}
    ft.set_test_score_details(user_id, "ACT", "34")
    assert ft.get_test_score_details(user_id) == {"kind": "ACT", "score": "34"}


def test_get_research_sources_by_ids(user_id: str) -> None:
    """Powers the frontend's "View Source" feature (Milestone 6)."""
    college_id = ft.save_college(user_id, College(name="MIT"))
    [source_id] = ft.save_research_sources(
        user_id,
        [
            ResearchSource(
                college_id=college_id,
                url="https://admissions.mit.edu",
                title="mit.edu",
                date_researched=ft.now(),
                official=True,
                confidence=ConfidenceLevel.HIGH,
            )
        ],
    )

    fetched = ft.get_research_sources_by_ids(user_id, [source_id, "does-not-exist"])
    assert len(fetched) == 1  # missing id is silently skipped, not an error
    assert fetched[0].id == source_id
    assert fetched[0].official is True


def test_update_college_deadlines_is_a_partial_merge(user_id: str) -> None:
    """Milestone 6: powers the dashboard's per-college deadline columns.
    Must merge, not overwrite, so a later partial update (e.g. only "rd"
    found this time) doesn't wipe out a previously-found "ea"."""
    college_id = ft.save_college(user_id, College(name="Rice"))

    ft.update_college_deadlines(user_id, college_id, {"ea": "2026-11-01"})
    ft.update_college_deadlines(user_id, college_id, {"rd": "2027-01-04"})

    college = ft.get_college(user_id, college_id)
    assert college is not None
    assert (
        college.deadlines.ea is not None
        and college.deadlines.ea.date().isoformat() == "2026-11-01"
    )
    assert (
        college.deadlines.rd is not None
        and college.deadlines.rd.date().isoformat() == "2027-01-04"
    )
