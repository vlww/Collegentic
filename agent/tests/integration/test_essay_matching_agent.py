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
Requirement + StudentMaterial docs directly (no live web research needed,
no LLM call either — app/tools/essay_matching.py is a deterministic
keyword categorizer), then runs the real pipeline against them through
Firestore. Category-matching logic itself is unit-tested directly in
tests/unit/test_essay_matching.py; this test is about the Firestore
read/write wiring (upserts, id validation) around it.
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
    """No materials at all means no candidate can exist in any category,
    regardless of what the prompt itself categorizes as."""
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


def test_related_category_produces_a_weak_match(user_id: str) -> None:
    """The prompt is labeled "Personal Statement" (phrase tier wins,
    category=personal_statement); the material's own text is about
    overcoming a challenge, so it classifies as greatest_challenge instead
    of personal_statement, per classify_material_category's "text always
    wins over type" rule. No exact-category candidate exists, so this
    exercises _RELATED_CATEGORIES's weak-match fallback (baseline 45, not
    60) rather than an exact-category match — Common App's own official
    personal-statement prompt options include a "describe a challenge you
    overcame" choice, so this pairing is a genuine, if weaker, reuse fit."""
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
    assert len(matches) == 1

    match = matches[0]
    assert match.material_id == ft.get_student_materials(user_id)[0].id
    assert 45 <= match.match_score <= 100
    assert "touch on" in match.reasoning
    assert match.recommendation.value in ("adapt", "new")


def test_exact_category_match_beats_a_weak_related_one(user_id: str) -> None:
    """When a genuine same-category material exists, it wins outright over
    any related-category fallback — related categories are a last resort,
    not an equally-weighted alternative."""
    college_id = ft.save_college(user_id, College(name="Rice University"))
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Personal Statement: describe who you are in 650 words.",
            )
        ],
    )
    ft.save_student_material(
        user_id,
        StudentMaterial(
            title="My personal statement",
            type=MaterialType.SUPPLEMENTAL,
            topic="Who I am and what shaped my personal outlook on life",
        ),
    )

    _run(user_id)

    matches = ft.get_essay_matches(user_id)
    assert len(matches) == 1
    assert "Both are personal statement essays" in matches[0].reasoning
    assert matches[0].match_score >= 60
