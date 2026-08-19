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

"""Live end-to-end test of the full Milestone 3-4-7 chain,
college_intake_pipeline (college_intake_agent -> college_research_agent ->
requirements_pipeline -> task_planning_pipeline), researching one real
college and persisting structured, sourced requirements and planned tasks
to Firestore.

Drives college_intake_pipeline directly (pre-seeding `requested_colleges`
in state) rather than through orchestrator_agent/root_agent — since
Milestone 5, root_agent is the LLM-driven Orchestrator, which parses that
list from a natural-language message itself; that parsing behavior has its
own test in test_orchestrator_agent.py. This test's job is narrower and
unaffected by how the list gets populated: does the intake pipeline itself
write correct, linked Firestore records end to end.

Scoped to a single college to keep this reasonably fast/cheap — per-agent
behavior already has its own focused tests (test_college_intake_agent.py,
test_research_agent.py, test_requirements_agent_config.py).
"""

import asyncio
import uuid

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

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
    for coll_fn in (ft._research_sources, ft._agent_runs, ft._tasks):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()


def test_full_pipeline_researches_and_persists_requirements(user_id: str) -> None:
    # Imported inside the test, not at module level, so importing this file
    # doesn't pull in every future pipeline stage for tests that don't need it.
    from app.sub_agents.orchestrator_agent import college_intake_pipeline

    async def _go() -> None:
        runner = InMemoryRunner(agent=college_intake_pipeline, app_name="test")
        session = await runner.session_service.create_session(
            app_name="test",
            user_id=user_id,
            state={"requested_colleges": ["Rice University"]},
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

    colleges = ft.get_tracked_colleges(user_id)
    assert len(colleges) == 1
    college = colleges[0]
    assert college.name == "Rice University"

    requirements = ft.get_requirements(user_id, [college.id])
    assert len(requirements) > 0
    # Per .agents-cli-spec.md § Constraints: a researched requirement must
    # be traceable to a source, or explicitly flagged for verification if
    # the agent genuinely couldn't attribute one (e.g. an UNCERTAIN finding).
    for requirement in requirements:
        assert requirement.source_ids or requirement.needs_verification

    sources = ft.get_research_sources(user_id, college.id)
    assert len(sources) > 0
    assert all(source.url.startswith("http") for source in sources)

    tasks = ft.get_tasks(user_id, college.id)
    assert len(tasks) > 0
    assert all(task.source_requirement_id for task in tasks)
    # One task per requirement, never more — see task_planning_agent.py's
    # instruction ("never split one requirement into multiple tasks").
    assert len({task.source_requirement_id for task in tasks}) == len(tasks)

    runs = ft.get_agent_runs(user_id)
    agent_names = {run.agent_name for run in runs}
    assert "college_research_agent" in agent_names
    assert "findings_evaluator" in agent_names
    assert "requirements_agent" in agent_names
    assert "task_planning_agent" in agent_names
    assert all(run.status.value == "completed" for run in runs)
