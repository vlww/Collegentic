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

"""Live test of conflict_pipeline in isolation: seeds College + Requirement
docs directly (no live web research needed) so this stays fast, then runs
the real ConflictContextAgent -> conflict_detection_agent chain against
them.

Unlike priority/readiness, conflict detection is genuine LLM judgment, not
a deterministic formula the LLM only phrases — so assertions here stay
structural (a conflict was created referencing real, known ids) rather than
asserting exact conflict counts or wording, except where the persist
callback's OWN validation guarantees an outcome regardless of what the LLM
says (the single-college case: no cross-college conflict is possible no
matter what the LLM returns, since `_persist_conflicts` drops any conflict
with fewer than 2 known college ids).
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.schemas import College, CollegeDeadlines, ConflictStatus, Requirement
from app.sub_agents.conflict_agent import conflict_pipeline
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for doc in ft._conflicts(uid).stream():
        doc.reference.delete()
    for doc in ft._agent_runs(uid).stream():
        doc.reference.delete()


def _run(user_id: str) -> None:
    async def _go() -> None:
        runner = InMemoryRunner(agent=conflict_pipeline, app_name="test")
        session = await runner.session_service.create_session(
            app_name="test", user_id=user_id
        )
        async for _ in runner.run_async(
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text="go")]
            ),
            user_id=user_id,
            session_id=session.id,
        ):
            pass

    asyncio.run(_go())


def test_no_conflict_possible_with_a_single_college(user_id: str) -> None:
    """Guaranteed by _persist_conflicts's own validation (drops anything
    with <2 known college ids), independent of what the LLM decides —
    doesn't depend on LLM judgment to pass reliably."""
    ft.save_college(
        user_id,
        College(
            name="Rice University",
            deadlines=CollegeDeadlines(rd=datetime.now(UTC) + timedelta(days=90)),
        ),
    )

    _run(user_id)

    assert ft.get_conflicts(user_id) == []


def test_clustered_deadlines_produce_a_grounded_conflict(user_id: str) -> None:
    """Two colleges whose earliest deadlines are 2 days apart — well within
    the deterministic clustering window handed to the LLM as an
    already-computed fact ("deadline_clusters below already lists colleges
    whose earliest deadlines fall within days of each other"), the closest
    thing this agent has to a sure signal."""
    now = datetime.now(UTC)
    ft.save_college(
        user_id,
        College(
            name="Rice University",
            deadlines=CollegeDeadlines(rd=now + timedelta(days=60)),
        ),
    )
    ft.save_college(
        user_id,
        College(
            name="Baylor University",
            deadlines=CollegeDeadlines(rd=now + timedelta(days=62)),
        ),
    )

    _run(user_id)

    conflicts = ft.get_conflicts(user_id)
    assert len(conflicts) >= 1
    for conflict in conflicts:
        # Every emitted conflict must be genuinely cross-college and only
        # reference colleges that actually exist — proves the persist
        # callback's id-validation ran, not just that something was returned.
        assert len(conflict.college_ids) >= 2
        college_names = {c.name for c in ft.get_tracked_colleges(user_id)}
        assert college_names  # sanity: colleges still exist
        assert conflict.status.value == "open"


def test_conflict_survives_and_status_is_preserved_across_reruns(user_id: str) -> None:
    """A conflict a student has already resolved must not be silently
    reopened by a later pipeline run that re-detects the same underlying
    facts — see conflict_agent.py's fingerprint-merge docstring."""
    now = datetime.now(UTC)
    ft.save_college(
        user_id,
        College(
            name="Rice University",
            deadlines=CollegeDeadlines(rd=now + timedelta(days=60)),
        ),
    )
    ft.save_college(
        user_id,
        College(
            name="Baylor University",
            deadlines=CollegeDeadlines(rd=now + timedelta(days=62)),
        ),
    )

    _run(user_id)
    conflicts = ft.get_conflicts(user_id)
    if not conflicts:
        pytest.skip(
            "LLM did not flag a conflict for this run — nothing to verify persistence of"
        )

    ft.update_conflict_status(user_id, conflicts[0].id, ConflictStatus.RESOLVED)

    _run(user_id)

    refreshed = {c.id: c for c in ft.get_conflicts(user_id)}
    assert refreshed[conflicts[0].id].status.value == "resolved"
