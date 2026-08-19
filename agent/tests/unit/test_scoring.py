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

"""Unit tests for app/tools/scoring.py — pure functions, no Firestore, no
model calls. These directly encode TEST 5/6/7 from .agents-cli-spec.md
§ Testing And Evaluation.
"""

from datetime import UTC, datetime, timedelta

from app.schemas import CollegeDeadlines
from app.tools.scoring import compute_priority_score, resolve_effective_deadline

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _days(n: int) -> datetime:
    return NOW + timedelta(days=n)


def test_resolve_effective_deadline_prefers_the_tasks_own_deadline() -> None:
    own = _days(5)
    deadlines = CollegeDeadlines(ea=_days(1), rd=_days(30))
    assert resolve_effective_deadline(own, deadlines) == own


def test_resolve_effective_deadline_falls_back_to_earliest_college_deadline() -> None:
    """Milestone 8 finding: most tasks (essays, recommendations, portfolio
    prep) never get their own deadline — only "deadline"-type requirements
    do — so without this fallback, deadline_urgency (the LARGEST-weighted
    component) would silently be 0 for most of a student's task list."""
    deadlines = CollegeDeadlines(
        ea=_days(10), rd=_days(40), ed=None, financial_aid=_days(5)
    )
    assert resolve_effective_deadline(None, deadlines) == _days(
        5
    )  # earliest of the set


def test_resolve_effective_deadline_returns_none_when_nothing_is_known() -> None:
    assert resolve_effective_deadline(None, CollegeDeadlines()) is None
    assert resolve_effective_deadline(None, None) is None


def test_weights_sum_to_one_and_deadline_is_largest() -> None:
    """The spec's own invariant: "Deadline should have the largest weighting.\""""
    from app.tools import scoring

    weights = {
        "deadline": scoring._DEADLINE_URGENCY_WEIGHT,
        "workload": scoring._WORKLOAD_PRESSURE_WEIGHT,
        "importance": scoring._REQUIREMENT_IMPORTANCE_WEIGHT,
        "dependency": scoring._DEPENDENCY_PRESSURE_WEIGHT,
        "progress": scoring._INCOMPLETE_PROGRESS_WEIGHT,
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights["deadline"] == max(weights.values())


def test_no_deadline_contributes_zero_urgency() -> None:
    result = compute_priority_score(
        deadline=None,
        estimated_minutes=60,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        now=NOW,
    )
    assert result.deadline_urgency == 0.0
    assert result.days_until_deadline is None
    assert "no known deadline" in result.explanation_facts


def test_overdue_deadline_maxes_out_urgency() -> None:
    result = compute_priority_score(
        deadline=_days(-3),
        estimated_minutes=30,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        now=NOW,
    )
    assert result.deadline_urgency == 100.0
    assert result.days_until_deadline == -3
    assert "3 day(s) ago" in result.explanation_facts


def test_close_deadline_dominates_even_when_nearly_complete() -> None:
    """TEST 5: "A deadline is very close but the application is nearly
    complete. Expected: High priority." Comparative, not an absolute score
    threshold (that belongs to the frontend's display bands, not this
    formula test — it should stay valid even if weights get adjusted): a
    close deadline must swing the score by a wide margin versus the exact
    same nearly-complete task with a distant deadline."""
    close_deadline = compute_priority_score(
        deadline=_days(2),
        estimated_minutes=15,  # small remaining task
        required=True,
        status="InProgress",  # "nearly complete" -> in progress, not blocked/not-started
        has_dependencies=False,
        now=NOW,
    )
    far_deadline = compute_priority_score(
        deadline=_days(110),  # near the 120-day horizon, genuinely distant
        estimated_minutes=15,
        required=True,
        status="InProgress",
        has_dependencies=False,
        now=NOW,
    )
    assert close_deadline.deadline_urgency > 95
    assert close_deadline.score > far_deadline.score + 25


def test_far_deadline_but_long_task_increases_priority() -> None:
    """TEST 6: "A deadline is farther away but a major task has a long
    estimated completion time. Expected: Priority increases appropriately."
    Holding the (far) deadline constant, a longer task must score higher."""
    short_task = compute_priority_score(
        deadline=_days(45),
        estimated_minutes=15,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        now=NOW,
    )
    long_task = compute_priority_score(
        deadline=_days(45),
        estimated_minutes=400,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        now=NOW,
    )
    assert long_task.workload_pressure > short_task.workload_pressure
    assert long_task.score > short_task.score


def test_recommendation_lead_time_makes_distant_deadline_urgent() -> None:
    """TEST 7: "A recommendation deadline is distant but teacher lead time
    makes it urgent. Expected: Priority Agent recognizes the dependency."
    A 25-day-out recommendation deadline should read as MORE urgent than a
    25-day-out essay deadline, because of the lead-time adjustment."""
    recommendation = compute_priority_score(
        deadline=_days(25),
        estimated_minutes=15,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        category="recommendation",
        now=NOW,
    )
    essay = compute_priority_score(
        deadline=_days(25),
        estimated_minutes=15,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        category="essay",
        now=NOW,
    )
    assert recommendation.deadline_urgency > essay.deadline_urgency
    assert recommendation.score > essay.score
    assert "lead time" in recommendation.explanation_facts
    assert "lead time" not in essay.explanation_facts


def test_optional_requirement_scores_lower_than_required() -> None:
    required = compute_priority_score(
        deadline=_days(10),
        estimated_minutes=60,
        required=True,
        status="NotStarted",
        has_dependencies=False,
        now=NOW,
    )
    optional = compute_priority_score(
        deadline=_days(10),
        estimated_minutes=60,
        required=False,
        status="NotStarted",
        has_dependencies=False,
        now=NOW,
    )
    assert required.requirement_importance > optional.requirement_importance
    assert required.score > optional.score


def test_blocked_status_maxes_dependency_pressure() -> None:
    result = compute_priority_score(
        deadline=_days(10),
        estimated_minutes=60,
        required=True,
        status="Blocked",
        has_dependencies=False,
        now=NOW,
    )
    assert result.dependency_pressure == 100.0


def test_done_status_has_zero_incomplete_progress() -> None:
    result = compute_priority_score(
        deadline=_days(10),
        estimated_minutes=60,
        required=True,
        status="Done",
        has_dependencies=False,
        now=NOW,
    )
    assert result.incomplete_progress == 0.0


def test_score_is_deterministic_and_bounded() -> None:
    for _ in range(3):
        result = compute_priority_score(
            deadline=_days(5),
            estimated_minutes=500,
            required=True,
            status="NotStarted",
            has_dependencies=True,
            category="recommendation",
            now=NOW,
        )
        assert 0.0 <= result.score <= 100.0
