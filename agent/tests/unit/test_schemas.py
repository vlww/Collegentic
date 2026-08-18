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

"""Pure Pydantic validation for app.schemas — no network, no Firestore.
Live read/write correctness is covered by
tests/integration/test_firestore_tools.py.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    College,
    CollegeStatus,
    ConfidenceLevel,
    EssayMatch,
    MatchRecommendation,
    Requirement,
    RequirementStatus,
    Task,
)


def test_college_serializes_to_camel_case() -> None:
    college = College(name="MIT", application_type="CommonApp")
    payload = college.model_dump(by_alias=True, exclude={"id"})
    assert "applicationType" in payload
    assert "application_type" not in payload


def test_college_round_trips_from_camel_case_firestore_dict() -> None:
    firestore_dict = {
        "name": "Princeton",
        "applicationType": "CommonApp",
        "status": "InProgress",
    }
    college = College.model_validate({**firestore_dict, "id": "abc123"})
    assert college.application_type == "CommonApp"
    assert college.status == CollegeStatus.IN_PROGRESS
    assert college.id == "abc123"


def test_college_requires_name() -> None:
    with pytest.raises(ValidationError):
        College()  # ty: ignore[missing-argument]


def test_college_defaults_are_safe_not_invented() -> None:
    college = College(name="Rice")
    assert college.status == CollegeStatus.PLANNING
    assert college.readiness.score == 0
    assert college.deadlines.ea is None
    assert college.school_colors.primary is None


def test_requirement_rejects_out_of_range_completion_percentage() -> None:
    with pytest.raises(ValidationError):
        Requirement(
            college_id="mit",
            type="essay",
            description="Personal statement",
            completion_percentage=150,
        )


def test_requirement_defaults_to_low_confidence_not_high() -> None:
    """A requirement with no research behind it yet must not default to a
    confident state — see .agents-cli-spec.md § Constraints."""
    requirement = Requirement(college_id="mit", type="essay", description="x")
    assert requirement.confidence == ConfidenceLevel.LOW
    assert requirement.status == RequirementStatus.NOT_STARTED
    assert requirement.source_ids == []


def test_essay_match_rejects_score_above_100() -> None:
    with pytest.raises(ValidationError):
        EssayMatch(
            prompt_id="p1",
            college_id="mit",
            material_id="m1",
            match_score=101,
            recommendation=MatchRecommendation.ADAPT,
            reasoning="test",
        )


def test_task_defaults_created_by_agent() -> None:
    task = Task(title="Draft essay", created_at=datetime.now(UTC))
    assert task.created_by.value == "agent"
    assert task.dependencies == []
