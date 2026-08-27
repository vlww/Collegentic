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


def test_creates_new_colleges_and_reuses_existing_by_name(user_id: str) -> None:
    delta = _run_intake(user_id, ["MIT", "Rice University"])
    assert set(delta["new_college_names"]) == {"MIT", "Rice University"}
    assert set(delta["college_name_to_id"].keys()) == {"MIT", "Rice University"}

    # Give MIT an actual Requirement doc, as a real research pass would —
    # only a college that's actually been researched should be excluded
    # from new_college_names on a later request (see .agents-cli-spec.md §
    # Cost Control, and test_stub_college_is_re_added_to_new_college_names
    # below for the "created but never researched" case this doesn't cover).
    mit_id = delta["college_name_to_id"]["MIT"]
    ft.save_requirements(
        user_id,
        [Requirement(college_id=mit_id, type="essay", description="Personal statement.")],
    )

    # Re-requesting the same name (any case) must reuse the existing doc,
    # not create a duplicate, and must not re-flag it for research now that
    # it's actually been researched.
    delta2 = _run_intake(user_id, ["mit", "Stanford"])
    assert delta2["new_college_names"] == ["Stanford"]
    assert delta2["college_name_to_id"]["mit"] == mit_id

    tracked = ft.get_tracked_colleges(user_id)
    assert len(tracked) == 3  # MIT, Rice, Stanford — not 4


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
