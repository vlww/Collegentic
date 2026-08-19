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

"""Live end-to-end test of root_agent (orchestrator_agent): a real
natural-language message in, verifying it parses the college name, delegates
to college_intake_pipeline via AgentTool, and reports back in plain
language rather than raw JSON. Also verifies the pipeline_run_id fix in
app/callbacks.py — every stage's AgentRun doc should share one id, proving
state written by the Orchestrator's before_agent_callback actually
propagates into the AgentTool-spawned child session.

Scoped to a single college — see test_requirements_agent.py's docstring for
why this suite keeps live pipeline runs to one college each.
"""

import asyncio
import uuid

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agent import root_agent
from app.schemas import Requirement
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for coll_fn in (ft._research_sources, ft._agent_runs, ft._tasks, ft._conflicts):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()


def test_orchestrator_parses_delegates_and_summarizes_in_plain_language(
    user_id: str,
) -> None:
    async def _go() -> str:
        runner = InMemoryRunner(agent=root_agent, app_name="test")
        session = await runner.session_service.create_session(
            app_name="test", user_id=user_id
        )
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text="I'm applying to Rice University.")],
        )
        final_text = ""
        async for event in runner.run_async(
            new_message=message, user_id=user_id, session_id=session.id
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        final_text += part.text
        return final_text

    final_text = asyncio.run(_go())

    # Plain-language report, not the pipeline's raw structured output.
    assert len(final_text) > 20
    assert "extracted_requirements" not in final_text
    assert "college_name_to_id" not in final_text
    assert "planned_tasks" not in final_text
    assert not final_text.strip().startswith("{")

    colleges = ft.get_tracked_colleges(user_id)
    assert len(colleges) == 1
    assert colleges[0].name == "Rice University"

    requirements = ft.get_requirements(user_id, [colleges[0].id])
    assert len(requirements) > 0

    tasks = ft.get_tasks(user_id, colleges[0].id)
    assert len(tasks) > 0
    assert all(task.priority_score > 0 for task in tasks)

    refreshed_college = ft.get_college(user_id, colleges[0].id)
    assert refreshed_college.readiness.explanation != ""
    assert refreshed_college.readiness.computed_at is not None

    # A single tracked college can never produce a real cross-college
    # conflict — guaranteed by _persist_conflicts's own id validation,
    # independent of what the LLM decides (see conflict_agent.py).
    assert ft.get_conflicts(user_id) == []

    runs = ft.get_agent_runs(user_id)
    agent_names = {run.agent_name for run in runs}
    assert {
        "orchestrator_agent",
        "college_research_agent",
        "requirements_agent",
        "conflict_detection_agent",
        "task_planning_agent",
        "priority_explanation_agent",
        "readiness_explanation_agent",
    } <= agent_names

    pipeline_run_ids = {run.pipeline_run_id for run in runs}
    assert len(pipeline_run_ids) == 1, (
        "Every stage should share one pipeline_run_id — "
        f"got {pipeline_run_ids} across {sorted(agent_names)}"
    )
