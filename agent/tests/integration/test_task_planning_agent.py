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

"""Live test of task_planning_pipeline in isolation: seeds Requirement docs
directly (no live web research needed — that's covered by
test_requirements_agent.py) so this stays fast, then runs the real
TaskContextAgent -> task_planning_agent chain against them.
"""

import asyncio
import uuid

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.schemas import College, ConfidenceLevel, Requirement
from app.sub_agents.task_planning_agent import task_planning_pipeline
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for coll_fn in (ft._agent_runs, ft._tasks):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()


def _run_task_planning(user_id: str) -> None:
    async def _go() -> None:
        runner = InMemoryRunner(agent=task_planning_pipeline, app_name="test")
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


def test_generates_one_task_per_actionable_requirement_and_dedupes(
    user_id: str,
) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Personal statement, 250-650 words.",
                confidence=ConfidenceLevel.HIGH,
            ),
            Requirement(
                college_id=college_id,
                type="recommendation",
                description="2 teacher recommendations required.",
                confidence=ConfidenceLevel.HIGH,
            ),
            Requirement(
                college_id=college_id,
                type="deadline",
                description="Regular Decision deadline: January 4.",
                confidence=ConfidenceLevel.HIGH,
            ),
        ],
    )

    _run_task_planning(user_id)

    tasks = ft.get_tasks(user_id, college_id)
    # Exactly 2 tasks: essay + recommendation. Per task_planning_agent.py's
    # instruction, a bare "deadline" requirement gets no task of its own.
    assert len(tasks) == 2
    categories = {task.category for task in tasks}
    assert categories == {"essay", "recommendation"}
    assert all(task.source_requirement_id for task in tasks)
    assert all(task.college_id == college_id for task in tasks)

    # Re-running must not create duplicates (dedup by source_requirement_id,
    # already covered at the firestore_tools layer — this proves the agent
    # actually reuses the same ids on a second pass, not just that the
    # underlying dedupe function works in isolation).
    _run_task_planning(user_id)
    tasks_after_rerun = ft.get_tasks(user_id, college_id)
    assert len(tasks_after_rerun) == 2
    assert {t.id for t in tasks_after_rerun} == {t.id for t in tasks}
