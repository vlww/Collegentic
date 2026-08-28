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

"""Live Firestore test for college_intake_agent's dedupe/alias logic. No
model calls — CollegeIntakeAgent is a plain BaseAgent, not an LlmAgent."""

import asyncio
import uuid

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.schemas import College, Requirement
from app.sub_agents.college_intake_agent import CollegeIntakeAgent
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        ft._colleges(uid).document(college.id).delete()
    ft._pipeline_progress_doc(uid).delete()


def _run_intake(user_id: str, requested: list[str]) -> dict:
    async def _go() -> dict:
        runner = InMemoryRunner(agent=CollegeIntakeAgent(), app_name="test")
        session = await runner.session_service.create_session(
            app_name="test", user_id=user_id, state={"requested_colleges": requested}
        )
        events = [
            event
            async for event in runner.run_async(
                new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text="go")]
                ),
                user_id=user_id,
                session_id=session.id,
            )
        ]
        return events[-1].actions.state_delta

    return asyncio.run(_go())


def test_creates_new_colleges_up_front_in_request_order(user_id: str) -> None:
    """CollegeIntakeAgent creates a brand-new college's Firestore row right
    away, for every requested college at once — this is fast (pure
    bookkeeping, no LLM/search call; the name itself was already resolved
    by the Orchestrator's own parsing step before this ever runs), so a
    judge sees the full requested list take shape almost immediately
    instead of waiting for each college's (much slower) research to finish
    before the next one's row even appears. Only the actual RESEARCH is
    sequential — see PerCollegeResearchAndExtraction in
    orchestrator_agent.py."""
    delta = _run_intake(user_id, ["MIT", "Rice University"])
    assert delta["new_college_names"] == ["MIT", "Rice University"]
    assert set(delta["college_name_to_id"].keys()) == {"MIT", "Rice University"}
    assert not ft.get_college(user_id, delta["college_name_to_id"]["MIT"]).researching

    tracked = ft.get_tracked_colleges(user_id)
    assert [c.name for c in tracked] == ["MIT", "Rice University"]  # request order

    progress = ft.get_pipeline_progress(user_id)
    assert progress is not None
    assert progress.total_colleges == 2
    assert progress.completed_colleges == 0


def test_reuses_existing_college_by_name_and_excludes_it_once_researched(
    user_id: str,
) -> None:
    mit_id = ft.save_college(user_id, College(name="MIT"))
    ft.save_requirements(
        user_id,
        [Requirement(college_id=mit_id, type="essay", description="Personal statement.")],
    )

    # Re-requesting the same name (any case) must reuse the existing doc,
    # not create a duplicate, and must not re-flag it for research now that
    # it's actually been researched — while "Stanford" (brand new) still
    # gets a fresh row created right away.
    delta = _run_intake(user_id, ["mit", "Stanford"])
    assert delta["new_college_names"] == ["Stanford"]
    assert delta["college_name_to_id"]["mit"] == mit_id
    assert "Stanford" in delta["college_name_to_id"]

    tracked = ft.get_tracked_colleges(user_id)
    assert len(tracked) == 2  # MIT (reused) + Stanford (newly created)


def test_reuses_existing_college_by_alias(user_id: str) -> None:
    existing_id = ft.save_college(
        user_id, College(name="Massachusetts Institute of Technology", aliases=["MIT"])
    )
    ft.save_requirements(
        user_id,
        [Requirement(college_id=existing_id, type="essay", description="Personal statement.")],
    )
    delta = _run_intake(user_id, ["MIT"])
    assert delta["new_college_names"] == []
    assert delta["college_name_to_id"]["MIT"] == existing_id


def test_stub_college_is_re_added_to_new_college_names(user_id: str) -> None:
    """A College doc that exists but has zero Requirement docs is a stub —
    either newly created moments ago by this same intake step, or left
    behind by an earlier run that was interrupted by an error before
    research finished (see api.py's pipeline error handler). Re-requesting
    its name must reuse the same doc AND still flag it as needing research,
    or "resume research after an error" would silently no-op instead of
    actually finishing it."""
    existing_id = ft.save_college(user_id, College(name="Rice University"))
    delta = _run_intake(user_id, ["Rice University"])
    assert delta["new_college_names"] == ["Rice University"]
    assert delta["college_name_to_id"]["Rice University"] == existing_id

    tracked = ft.get_tracked_colleges(user_id)
    assert len(tracked) == 1  # reused, not duplicated
