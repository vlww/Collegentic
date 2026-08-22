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

"""Integration tests for the frontend REST API (app/api.py) against real
Firestore. Mounts api_router on a throwaway FastAPI app rather than
importing app.fast_api_app — that module's google.auth.default() / Cloud
Logging client construction at import time has nothing to do with what's
under test here.

Does not cover POST /orchestrator/messages: that route's only real logic is
`request.app.state.runner`, which only exists on the ADK-generated app —
faking it would test the fake, not the route. It's already exercised
end-to-end via a real HTTP call in Milestone 6's manual verification and
covered at the agent level by test_orchestrator_agent.py.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import router as api_router
from app.schemas import (
    College,
    ConfidenceLevel,
    Conflict,
    EssayMatch,
    EssayPrompt,
    MaterialType,
    Requirement,
    ResearchSource,
    StudentMaterial,
    Task,
)
from app.tools import firestore_tools as ft


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    return TestClient(app)


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
    for coll_fn in (
        ft._research_sources,
        ft._tasks,
        ft._conflicts,
        ft._materials,
        ft._essay_matches,
        ft._agent_runs,
    ):
        for doc in coll_fn(uid).stream():
            doc.reference.delete()


def test_missing_user_id_header_returns_400(client: TestClient) -> None:
    res = client.get("/colleges")
    assert res.status_code == 400


def test_list_colleges_empty(client: TestClient, user_id: str) -> None:
    res = client.get("/colleges", headers={"X-User-Id": user_id})
    assert res.status_code == 200
    assert res.json() == []


def test_college_not_found_returns_404(client: TestClient, user_id: str) -> None:
    res = client.get("/colleges/does-not-exist", headers={"X-User-Id": user_id})
    assert res.status_code == 404


def test_full_read_flow(client: TestClient, user_id: str) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    [source_id] = ft.save_research_sources(
        user_id,
        [
            ResearchSource(
                college_id=college_id,
                url="https://rice.edu",
                title="rice.edu",
                date_researched=ft.now(),
                official=True,
                confidence=ConfidenceLevel.HIGH,
            )
        ],
    )
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Why Rice",
                confidence=ConfidenceLevel.HIGH,
                source_ids=[source_id],
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    colleges = client.get("/colleges", headers=headers).json()
    assert len(colleges) == 1
    assert colleges[0]["name"] == "Rice University"

    college = client.get(f"/colleges/{college_id}", headers=headers).json()
    assert college["id"] == college_id

    requirements = client.get("/requirements", headers=headers).json()
    assert len(requirements) == 1
    assert requirements[0]["sourceIds"] == [source_id]

    scoped = client.get(
        f"/requirements?college_ids={college_id}", headers=headers
    ).json()
    assert len(scoped) == 1

    sources = client.get(f"/research-sources?ids={source_id}", headers=headers).json()
    assert len(sources) == 1
    assert sources[0]["official"] is True


def test_list_tasks(client: TestClient, user_id: str) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    other_college_id = ft.save_college(user_id, College(name="Baylor University"))
    ft.save_tasks(
        user_id,
        [
            Task(
                title="Draft essay", college_id=college_id, source_requirement_id="r1"
            ),
            Task(
                title="Submit FAFSA",
                college_id=other_college_id,
                source_requirement_id="r2",
            ),
        ],
    )
    headers = {"X-User-Id": user_id}

    all_tasks = client.get("/tasks", headers=headers).json()
    assert len(all_tasks) == 2

    scoped = client.get(f"/tasks?college_id={college_id}", headers=headers).json()
    assert len(scoped) == 1
    assert scoped[0]["title"] == "Draft essay"


def test_update_requirement_progress_defaults_completion_from_status(
    client: TestClient, user_id: str
) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    [requirement_id] = ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Why Rice",
                confidence=ConfidenceLevel.HIGH,
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    res = client.patch(
        f"/colleges/{college_id}/requirements/{requirement_id}",
        json={"status": "NearlyComplete"},
        headers=headers,
    )
    assert res.status_code == 200

    updated = ft.get_requirements(user_id, [college_id])[0]
    assert updated.status.value == "NearlyComplete"
    assert updated.completion_percentage == 75.0  # status default, not given explicitly


def test_update_requirement_progress_accepts_explicit_percentage(
    client: TestClient, user_id: str
) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    [requirement_id] = ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Why Rice",
                confidence=ConfidenceLevel.HIGH,
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    res = client.patch(
        f"/colleges/{college_id}/requirements/{requirement_id}",
        json={"status": "InProgress", "completionPercentage": 33},
        headers=headers,
    )
    assert res.status_code == 200

    updated = ft.get_requirements(user_id, [college_id])[0]
    assert updated.completion_percentage == 33.0


def test_recompute_readiness_refreshes_score_and_explanation_together(
    client: TestClient, user_id: str
) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    ft.save_requirements(
        user_id,
        [
            Requirement(
                college_id=college_id,
                type="essay",
                description="Why Rice",
                completion_percentage=100,
                confidence=ConfidenceLevel.HIGH,
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    result = client.post("/readiness/recompute", headers=headers).json()
    assert len(result) == 1
    assert result[0]["id"] == college_id
    assert result[0]["readiness"]["score"] > 0
    assert result[0]["readiness"]["explanation"] != ""
    assert result[0]["readiness"]["computedAt"] is not None


def test_list_conflicts(client: TestClient, user_id: str) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    other_college_id = ft.save_college(user_id, College(name="Baylor University"))
    ft.save_conflicts(
        user_id,
        [
            Conflict(
                type="recommendation",
                college_ids=[college_id, other_college_id],
                description="Both colleges need a recommender but none is identified.",
                recommendation="Ask a teacher soon.",
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    result = client.get("/conflicts", headers=headers).json()
    assert len(result) == 1
    assert result[0]["status"] == "open"


def test_acknowledge_and_resolve_conflict(client: TestClient, user_id: str) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    other_college_id = ft.save_college(user_id, College(name="Baylor University"))
    [conflict_id] = ft.save_conflicts(
        user_id,
        [
            Conflict(
                type="deadline",
                college_ids=[college_id, other_college_id],
                description="Deadlines cluster within days of each other.",
                recommendation="Start early.",
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    res = client.post(f"/conflicts/{conflict_id}/acknowledge", headers=headers)
    assert res.status_code == 200
    assert ft.get_conflicts(user_id)[0].status.value == "acknowledged"

    res = client.post(f"/conflicts/{conflict_id}/resolve", headers=headers)
    assert res.status_code == 200
    assert ft.get_conflicts(user_id)[0].status.value == "resolved"


def test_create_and_list_materials(client: TestClient, user_id: str) -> None:
    headers = {"X-User-Id": user_id}

    created = client.post(
        "/materials",
        json={
            "title": "Why I love robotics",
            "type": "CommonApp",
            "topic": "My robotics team",
            "partialText": "Some draft text about robotics.",
            "wordCount": 300,
        },
        headers=headers,
    ).json()
    assert created["title"] == "Why I love robotics"
    assert created["status"] == "NotStarted"

    listed = client.get("/materials", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


def test_list_essay_prompts_and_matches(client: TestClient, user_id: str) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    [prompt_id] = ft.save_essay_prompts(
        user_id,
        [EssayPrompt(college_id=college_id, text="Why Rice?", word_limit=150)],
    )
    material_id = ft.save_student_material(
        user_id,
        StudentMaterial(title="Why Rice draft", type=MaterialType.SUPPLEMENTAL),
    )
    ft.save_essay_matches(
        user_id,
        [
            EssayMatch(
                prompt_id=prompt_id,
                college_id=college_id,
                material_id=material_id,
                match_score=80,
                recommendation="adapt",
                reasoning="Strong topical overlap.",
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    prompts = client.get("/essay-prompts", headers=headers).json()
    assert len(prompts) == 1
    assert prompts[0]["text"] == "Why Rice?"

    matches = client.get("/essay-matches", headers=headers).json()
    assert len(matches) == 1
    assert matches[0]["recommendation"] == "adapt"


def test_list_agent_runs(client: TestClient, user_id: str) -> None:
    run_id = ft.start_agent_run(
        user_id, pipeline_run_id="run-1", agent_name="conflict_detection_agent"
    )
    ft.complete_agent_run(user_id, run_id, summary="Detected 1 conflict(s).")
    headers = {"X-User-Id": user_id}

    runs = client.get("/agent-runs", headers=headers).json()
    assert len(runs) == 1
    assert runs[0]["agentName"] == "conflict_detection_agent"
    assert runs[0]["pipelineRunId"] == "run-1"
    assert runs[0]["status"] == "completed"
    assert runs[0]["summary"] == "Detected 1 conflict(s)."


def test_recompute_priorities_refreshes_score_and_explanation_together(
    client: TestClient, user_id: str
) -> None:
    college_id = ft.save_college(user_id, College(name="Rice University"))
    [task_id] = ft.save_tasks(
        user_id,
        [
            Task(
                title="Draft essay",
                college_id=college_id,
                deadline=ft.now(),
                estimated_minutes=60,
                source_requirement_id="r1",
                priority_score=999,  # deliberately wrong, must be overwritten
                priority_explanation="stale sentence citing an old score",
            )
        ],
    )
    headers = {"X-User-Id": user_id}

    result = client.post("/priorities/recompute", headers=headers).json()
    assert len(result) == 1
    assert result[0]["id"] == task_id
    assert result[0]["priorityScore"] > 0
    assert result[0]["priorityScore"] != 999
    # No LLM call in this route, but the explanation must still be replaced
    # with fresh deterministic facts — see app/api.py's recompute_priorities
    # docstring for the Milestone 8 bug this fixes (a stale sentence baking
    # in a number that no longer matches the refreshed score).
    assert "stale sentence" not in result[0]["priorityExplanation"]
    assert result[0]["priorityExplanation"] != ""
