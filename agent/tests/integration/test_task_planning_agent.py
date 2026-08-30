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
from app.sub_agents.orchestrator_agent import _with_retry
from app.sub_agents.task_planning_agent import TaskContextAgent, task_planning_pipeline
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


def test_task_context_agent_skips_already_planned_requirements_unless_full_replan(
    user_id: str,
) -> None:
    """Regression test: task_planning_agent used to re-send EVERY tracked
    college's requirements to the LLM on every single run, even ones that
    already had a task — costing a bigger, slower call as more colleges
    piled up for no benefit (a planned task's title/description never needs
    to change on its own). TaskContextAgent must now skip requirements that
    already have a task, UNLESS force_full_replan is set (POST
    /tasks/replan's own escape hatch for deliberately regenerating
    everything)."""
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
        ],
    )
    _run_task_planning(user_id)
    assert len(ft.get_tasks(user_id, college_id)) == 1

    async def _run_context_only(*, force_full_replan: bool) -> dict:
        runner = InMemoryRunner(agent=TaskContextAgent(), app_name="test")
        state = {"force_full_replan": True} if force_full_replan else {}
        session = await runner.session_service.create_session(
            app_name="test", user_id=user_id, state=state
        )
        async for _ in runner.run_async(
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text="go")]
            ),
            user_id=user_id,
            session_id=session.id,
        ):
            pass
        updated_session = runner.session_service.get_session_sync(
            app_name="test", user_id=user_id, session_id=session.id
        )
        return updated_session.state

    default_state = asyncio.run(_run_context_only(force_full_replan=False))
    assert default_state["requirements_for_planning"] == []

    full_replan_state = asyncio.run(_run_context_only(force_full_replan=True))
    assert len(full_replan_state["requirements_for_planning"]) == 1


def test_retry_wrapped_pipeline_produces_the_same_result(user_id: str) -> None:
    """orchestrator_agent.py's _with_retry wraps task_planning_pipeline (and
    priority_pipeline/readiness_pipeline) so a transient failure retries the
    whole stage in place, invoking the wrapped agent via `agent.run_async(ctx)`
    rather than ADK's normal declarative `sub_agents=[...]` wiring (needed
    because task_planning_pipeline must stay unparented for
    POST /tasks/replan to keep using it directly). On the happy path (no
    failure at all) this must behave identically to running
    task_planning_pipeline directly — same tasks created, nothing lost or
    duplicated by the wrapping itself."""
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
        ],
    )

    async def _go() -> None:
        wrapped = _with_retry(task_planning_pipeline, "task_planning_pipeline")
        runner = InMemoryRunner(agent=wrapped, app_name="test")
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

    tasks = ft.get_tasks(user_id, college_id)
    assert len(tasks) == 1
    assert tasks[0].category == "essay"
