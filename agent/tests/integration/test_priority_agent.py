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

"""Live test of priority_pipeline in isolation: seeds Task docs directly
(no live web research or task planning needed — those are covered by
test_task_planning_agent.py) so this stays fast, then runs the real
TaskPriorityContextAgent -> priority_explanation_agent chain against them.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.schemas import College, Task, TaskStatus
from app.sub_agents.priority_agent import priority_pipeline
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        ft._colleges(uid).document(college.id).delete()
    for coll_fn in (ft._agent_runs, ft._tasks):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()


def test_scores_and_explains_tasks_deterministically_and_skips_done(
    user_id: str,
) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    urgent_id, distant_id, done_id = ft.save_tasks(
        user_id,
        [
            Task(
                title="Draft essay",
                college_id=college_id,
                deadline=datetime.now(UTC) + timedelta(days=2),
                estimated_minutes=90,
                required=True,
                status=TaskStatus.NOT_STARTED,
                source_requirement_id="r1",
            ),
            Task(
                title="Prepare portfolio",
                college_id=college_id,
                deadline=datetime.now(UTC) + timedelta(days=55),
                estimated_minutes=30,
                required=False,
                status=TaskStatus.NOT_STARTED,
                source_requirement_id="r2",
            ),
            Task(
                title="Already submitted item",
                college_id=college_id,
                required=True,
                status=TaskStatus.DONE,
                source_requirement_id="r3",
            ),
        ],
    )

    async def _go() -> None:
        runner = InMemoryRunner(agent=priority_pipeline, app_name="test")
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

    tasks_by_id = {task.id: task for task in ft.get_tasks(user_id, college_id)}

    urgent = tasks_by_id[urgent_id]
    distant = tasks_by_id[distant_id]
    done = tasks_by_id[done_id]

    # Close deadline + required + real workload must outscore a distant,
    # optional, lighter task — same ranking direction as test_scoring.py,
    # now proven through the real agent pipeline, not just the pure function.
    assert urgent.priority_score > distant.priority_score
    assert urgent.priority_explanation
    assert distant.priority_explanation

    # Done tasks are never touched — no score, no explanation.
    assert done.priority_score == 0
    assert done.priority_explanation == ""
