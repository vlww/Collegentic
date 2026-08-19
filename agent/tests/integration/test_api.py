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
from app.schemas import College, ConfidenceLevel, Requirement, ResearchSource
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
        ft._colleges(uid).document(college.id).delete()
    for doc in ft._research_sources(uid).stream():
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
