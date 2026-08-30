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

"""Live test of readiness_pipeline in isolation: seeds College + Requirement
docs directly (no live web research needed — that's covered by
test_research_agent.py / test_requirements_agent.py) so this stays fast,
then runs the real CollegeReadinessContextAgent -> readiness_explanation_agent
chain against them.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.schemas import College, CollegeDeadlines, Requirement
from app.sub_agents.readiness_agent import readiness_pipeline
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for doc in ft._agent_runs(uid).stream():
        doc.reference.delete()


def test_scores_and_explains_college_readiness_deterministically(
    user_id: str,
) -> None:
    ready_college_id = ft.save_college(
        user_id,
        College(
            name="Rice University",
            deadlines=CollegeDeadlines(rd=datetime.now(UTC) + timedelta(days=150)),
        ),
    )
    behind_college_id = ft.save_college(
        user_id,
        College(
            name="Baylor University",
            deadlines=CollegeDeadlines(rd=datetime.now(UTC) + timedelta(days=3)),
        ),
    )
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=ready_college_id,
                type="essay",
                description="Why Rice",
                completion_percentage=100,
            ),
            Requirement(
                college_id=behind_college_id,
                type="essay",
                description="Why Baylor",
                completion_percentage=10,
            ),
        ],
    )

    async def _go() -> None:
        runner = InMemoryRunner(agent=readiness_pipeline, app_name="test")
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

    ready_college = ft.get_college(user_id, ready_college_id)
    behind_college = ft.get_college(user_id, behind_college_id)

    # A fully-done college with a distant deadline must outscore one that's
    # barely started with an imminent deadline — same ranking direction as
    # test_scoring.py, now proven through the real agent pipeline.
    assert ready_college.readiness.score > behind_college.readiness.score
    assert ready_college.readiness.explanation
    assert behind_college.readiness.explanation
    assert ready_college.readiness.computed_at is not None


def test_skips_scoring_a_college_with_no_requirements_yet(user_id: str) -> None:
    """Regression test: found live that a newly-added college — not yet
    researched, zero Requirement docs — scored a flat 80% (every category's
    "owes nothing" vacuous default landing at once: essays 100, recs 100,
    testing 0, deadline 100), which read as real progress when there was
    none. CollegeReadinessContextAgent must skip a college with zero
    requirements entirely (leaving computed_at null) rather than persist
    that placeholder, while still scoring its siblings that DO have real
    data normally."""
    unresearched_id = ft.save_college(user_id, College(name="Unresearched University"))
    researched_id = ft.save_college(
        user_id,
        College(name="Rice University"),
    )
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=researched_id,
                type="essay",
                description="Why Rice",
                completion_percentage=100,
            ),
        ],
    )

    async def _go() -> None:
        runner = InMemoryRunner(agent=readiness_pipeline, app_name="test")
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

    unresearched = ft.get_college(user_id, unresearched_id)
    researched = ft.get_college(user_id, researched_id)
    assert unresearched.readiness.computed_at is None
    assert researched.readiness.computed_at is not None
