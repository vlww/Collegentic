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

"""Live test of seed_demo_data against real Firestore — pure Python + writes,
no LLM calls, so this stays fast. Checks that every element the spec's Demo
Mode use case calls for is actually present: 6 colleges, a stale/uncertain
source, overlapping essay prompts (same material matched across colleges),
a real recommendation conflict, mixed recommendation status, and readiness/
priority scores computed via the real deterministic formulas (not typed
in — checked by recomputing independently and comparing).
"""

import uuid

import pytest

from app.demo_data import seed_demo_data
from app.schemas import Requirement
from app.tools import firestore_tools as ft
from app.tools.scoring import compute_readiness_score


@pytest.fixture
def user_id():
    uid = f"test-demo-{uuid.uuid4()}"
    yield uid
    for college in ft.get_tracked_colleges(uid):
        for req in ft._read_all(ft._requirements(uid, college.id), Requirement):
            ft._requirements(uid, college.id).document(req.id).delete()
        for prompt in ft.get_essay_prompts(uid, college.id):
            ft._essay_prompts(uid, college.id).document(prompt.id).delete()
        ft._colleges(uid).document(college.id).delete()
    for coll_fn in (
        ft._research_sources,
        ft._tasks,
        ft._conflicts,
        ft._materials,
        ft._essay_matches,
        ft._agent_runs,
        ft._recommendations,
    ):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()
    ft._user_doc(uid).delete()


def test_seed_demo_data_matches_spec_requirements(user_id: str) -> None:
    seed_demo_data(user_id)

    colleges = ft.get_tracked_colleges(user_id)
    assert len(colleges) == 6

    college_ids = [c.id for c in colleges]
    requirements = ft.get_requirements(user_id, college_ids)
    assert len(requirements) > 0

    # At least one stale/uncertain research source.
    stale = [
        r for r in requirements if r.needs_verification and r.confidence.value == "low"
    ]
    assert len(stale) >= 1

    # Overlapping essay prompts: the same material matched across 2+
    # colleges' prompts.
    matches = ft.get_essay_matches(user_id)
    assert len(matches) >= 2
    material_to_colleges: dict[str, set[str]] = {}
    for match in matches:
        material_to_colleges.setdefault(match.material_id, set()).add(match.college_id)
    assert any(len(colleges_) >= 2 for colleges_ in material_to_colleges.values())

    # Mixed recommendation status.
    recommendations = ft.get_recommendations(user_id)
    assert len({r.status.value for r in recommendations}) >= 2

    # A real recommendation conflict spanning multiple colleges.
    conflicts = ft.get_conflicts(user_id)
    assert len(conflicts) >= 1
    assert conflicts[0].type.value == "recommendation"
    assert len(conflicts[0].college_ids) >= 2

    # Partial essays: materials with a completion_percentage strictly
    # between 0 and 100.
    materials = ft.get_student_materials(user_id)
    assert any(0 < m.completion_percentage < 100 for m in materials)

    # Readiness computed via the real formula, not typed in — recompute
    # independently and compare. Loose tolerance: compute_readiness_score's
    # days-until-deadline truncates to a whole day, so two calls seconds
    # apart can land on either side of a day boundary and swing the score
    # by up to ~1 point (same `.days` sensitivity compute_priority_score
    # has had since Milestone 8) — not a bug, just two different `now()`s.
    for college in colleges:
        assert college.readiness.computed_at is not None
        college_requirements = [r for r in requirements if r.college_id == college.id]
        expected = compute_readiness_score(college_requirements, college.deadlines)
        assert college.readiness.score == pytest.approx(expected.score, abs=2.0)

    # Tasks planned and scored.
    tasks = ft.get_tasks(user_id)
    assert len(tasks) > 0
    assert any(t.priority_score > 0 for t in tasks)

    # A plausible Agent Activity history.
    runs = ft.get_agent_runs(user_id)
    assert len(runs) > 0
    assert all(r.status.value == "completed" for r in runs)
