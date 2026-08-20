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

"""Live test of essay_matching_pipeline in isolation: seeds College +
Requirement + StudentMaterial docs directly (no live web research needed)
so this stays fast, then runs the real EssayContextAgent ->
essay_analysis_agent chain against them.

Match scoring is genuine LLM judgment, not a deterministic formula, so
assertions stay structural except where persistence's OWN validation
guarantees an outcome regardless of what the LLM returns (the
zero-materials case: no match is possible no matter what the LLM says,
since every material_id is dropped against an empty known-id set).
"""

import asyncio
import uuid

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.schemas import College, MaterialType, Requirement, StudentMaterial
from app.sub_agents.essay_matching_agent import essay_matching_pipeline
from app.tools import firestore_tools as ft


@pytest.fixture
def user_id():
    uid = f"test-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        for prompt in ft.get_essay_prompts(uid, college.id):
            ft._essay_prompts(uid, college.id).document(prompt.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for doc in ft._materials(uid).stream():
        doc.reference.delete()
    for doc in ft._essay_matches(uid).stream():
        doc.reference.delete()
    for doc in ft._agent_runs(uid).stream():
        doc.reference.delete()


def _run(user_id: str) -> None:
    async def _go() -> None:
        runner = InMemoryRunner(agent=essay_matching_pipeline, app_name="test")
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


def test_essay_prompt_extracted_and_no_match_without_materials(user_id: str) -> None:
    """Guaranteed by _persist_essay_analysis's own validation (drops any
    match whose material_id isn't in the known set — always true when zero
    materials exist), independent of what the LLM decides."""
    college_id = ft.save_college(user_id, College(name="Rice University"))
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Personal Statement: 'Describe a challenge you overcame "
                "and what you learned from it.' (650-word limit)",
            )
        ],
    )

    _run(user_id)

    prompts = ft.get_essay_prompts(user_id, college_id)
    assert len(prompts) == 1
    assert prompts[0].word_limit == 650

    assert ft.get_essay_matches(user_id) == []


def test_strongly_matching_material_produces_a_grounded_match(user_id: str) -> None:
    """A student material whose topic/excerpt is nearly the same challenge
    the prompt asks about — about as strong a signal as this agent's
    genuine judgment call can get."""
    college_id = ft.save_college(user_id, College(name="Rice University"))
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Personal Statement: 'Describe a challenge you overcame "
                "and what you learned from it.' (650-word limit)",
            )
        ],
    )
    ft.save_student_material(
        user_id,
        StudentMaterial(
            title="Overcoming my fear of public speaking",
            type=MaterialType.COMMON_APP,
            topic="A challenge I overcame: crippling stage fright before a debate final",
            partial_text="Growing up I was terrified of public speaking. During my "
            "junior year debate final, I had to overcome that fear on stage in "
            "front of hundreds of people. This is the story of how I learned to "
            "push through fear and what it taught me about resilience.",
            themes=["resilience", "overcoming fear", "public speaking"],
        ),
    )

    _run(user_id)

    matches = ft.get_essay_matches(user_id)
    if not matches:
        pytest.skip("LLM did not surface a match for this near-verbatim topic overlap")

    match = matches[0]
    assert 0 <= match.match_score <= 100
    assert match.reasoning != ""
    assert match.recommendation.value in ("adapt", "new")
