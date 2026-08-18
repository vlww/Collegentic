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

from app.schemas import College
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

    # Re-requesting the same name (any case) must reuse the existing doc,
    # not create a duplicate — see .agents-cli-spec.md § Cost Control.
    delta2 = _run_intake(user_id, ["mit", "Stanford"])
    assert delta2["new_college_names"] == ["Stanford"]
    assert delta2["college_name_to_id"]["mit"] == delta["college_name_to_id"]["MIT"]

    tracked = ft.get_tracked_colleges(user_id)
    assert len(tracked) == 3  # MIT, Rice, Stanford — not 4


def test_reuses_existing_college_by_alias(user_id: str) -> None:
    existing_id = ft.save_college(
        user_id, College(name="Massachusetts Institute of Technology", aliases=["MIT"])
    )
    delta = _run_intake(user_id, ["MIT"])
    assert delta["new_college_names"] == []
    assert delta["college_name_to_id"]["MIT"] == existing_id
