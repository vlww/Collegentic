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

"""Deterministic, explainable scoring formulas.

.agents-cli-spec.md § Deadline & Priority Agent: "the exact formula should
be explainable" and "priority must not simply equal 'closest deadline.'"
This is pure Python, not an LLM call — same "business rules in code, LLM
only for judgment/phrasing" split already used for the official-source
heuristic in requirements_agent.py. The Priority Agent (app/sub_agents/
priority_agent.py) computes every task's score here, then an LLM only
rewrites `explanation_facts` into a natural sentence — it never invents or
adjusts the number itself. Callers should resolve a task's effective
deadline via `resolve_effective_deadline` before calling
`compute_priority_score` — see that function's docstring for why most
tasks need the fallback to actually be deadline-driven at all.

Five 0-100 components, weighted (weights sum to 1.0; deadline urgency is
weighted largest per the spec: "Deadline should have the largest
weighting"):
- deadline_urgency (0.40): linear ramp from 0 at 120+ days out to 100 at
  the deadline or past it. 120 days (~4 months), not a shorter window: a
  student researching colleges in August for November/January deadlines is
  70-90 days out on day one — checked live (Milestone 8) and a 60-day
  horizon clamped every task from a freshly-researched college to 0
  urgency regardless of the `resolve_effective_deadline` fallback below,
  which isn't a realistic reading of "deadline proximity" for this domain.
- workload_pressure (0.20): linear ramp from 0 minutes to 100 at 400+
  minutes of estimated work — a long task needs to be started sooner.
- requirement_importance (0.15): 100 if the source requirement was
  required, 40 if optional.
- dependency_pressure (0.15): 100 if the task is Blocked, 40 if it has
  unmet dependencies (not yet set by any agent — Task Planning, Milestone
  7, never populates `dependencies`; this stays 0 for all current tasks
  until a future agent, e.g. Conflict Agent, Milestone 10, starts building
  a real dependency graph), else 0.
- incomplete_progress (0.10): 100 NotStarted, 75 Blocked, 50 InProgress, 0
  Done — callers should exclude Done tasks from ranking entirely rather
  than rely on this alone to zero them out.

Recommendation lead time (test scenario from .agents-cli-spec.md § Testing
And Evaluation, TEST 7 — "a recommendation deadline is distant but teacher
lead time makes it urgent"): a recommender needs real weeks to write a
letter, so a `category="recommendation"` task's deadline is treated, for
urgency purposes only, as `_RECOMMENDATION_LEAD_TIME_DAYS` earlier than its
listed date. This is the one deliberately non-literal reading of "deadline
proximity" in the formula, and it's called out explicitly in
`explanation_facts` when it applies, so it stays explainable rather than a
silent fudge.

`compute_readiness_score` (.agents-cli-spec.md § Application Readiness Agent:
"weighted completion of required components with additional penalties for
unresolved requirements, approaching deadlines... critical requirements
should have higher weight than optional components") reuses the same
linear deadline-decay shape as `compute_priority_score` via
`_deadline_urgency_fraction`, so "how urgent is this deadline" means the
same thing everywhere in the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas import (
    RECOMMENDATION_ALL_COLLEGES,
    CollegeDeadlines,
    Recommendation,
    RecommendationStatus,
    Requirement,
)

_DEADLINE_URGENCY_WEIGHT = 0.40
_WORKLOAD_PRESSURE_WEIGHT = 0.20
_REQUIREMENT_IMPORTANCE_WEIGHT = 0.15
_DEPENDENCY_PRESSURE_WEIGHT = 0.15
_INCOMPLETE_PROGRESS_WEIGHT = 0.10

_DEADLINE_URGENCY_HORIZON_DAYS = 120  # linear decay to 0 by this many days out
_WORKLOAD_PRESSURE_CAP_MINUTES = 400  # linear ramp to 100 by this many minutes
_RECOMMENDATION_LEAD_TIME_DAYS = (
    21  # a recommender needs real lead time to write a letter
)

_INCOMPLETE_PROGRESS_BY_STATUS = {
    "NotStarted": 100.0,
    "Blocked": 75.0,
    "InProgress": 50.0,
    "Done": 0.0,
}


@dataclass(frozen=True)
class PriorityBreakdown:
    score: float
    deadline_urgency: float
    workload_pressure: float
    requirement_importance: float
    dependency_pressure: float
    incomplete_progress: float
    days_until_deadline: int | None
    explanation_facts: str


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _deadline_urgency_fraction(days_until: int | None) -> float:
    """0.0 (120+ days out or no deadline) ramping linearly to 1.0 (at or past
    the deadline) — the same horizon `compute_priority_score` uses, shared so
    "urgent" means the same thing across scoring functions."""
    if days_until is None:
        return 0.0
    return _clamp(1 - days_until / _DEADLINE_URGENCY_HORIZON_DAYS, 0.0, 1.0)


def earliest_college_deadline(
    college_deadlines: CollegeDeadlines | None,
) -> datetime | None:
    if college_deadlines is None:
        return None
    candidates = [
        d
        for d in (
            college_deadlines.ea,
            college_deadlines.ed,
            college_deadlines.rd,
            college_deadlines.financial_aid,
        )
        if d is not None
    ]
    return min(candidates) if candidates else None


def resolve_effective_deadline(
    task_deadline: datetime | None, college_deadlines: CollegeDeadlines | None
) -> datetime | None:
    """Falls back to the college's nearest known deadline (EA/ED/RD/financial
    aid — whichever is earliest) when a task has no deadline of its own.

    Found live (Milestone 8, checking the actual dashboard rather than just
    the formula's unit tests): most tasks — essay drafts, recommendation
    requests, portfolio prep — never get their own `deadline`, because only
    "deadline"-type Requirements carry one (task_planning_agent.py copies a
    requirement's deadline verbatim, and an essay requirement rarely states
    its own separate due date). Left unresolved, deadline_urgency — the
    formula's LARGEST-weighted component — was silently 0 for most tasks,
    exactly backwards from the spec's "deadline should have the largest
    weighting." A task is still implicitly due by the time the application
    itself is due, so this fills that gap for SCORING purposes only —
    `Task.deadline` itself is never overwritten, stays null/honest.
    """
    if task_deadline is not None:
        return task_deadline
    return earliest_college_deadline(college_deadlines)


def compute_priority_score(
    *,
    deadline: datetime | None,
    estimated_minutes: int | None,
    required: bool,
    status: str,
    has_dependencies: bool,
    category: str | None = None,
    now: datetime | None = None,
) -> PriorityBreakdown:
    now = now or datetime.now(UTC)

    days_until_deadline: int | None = None
    lead_time_applied = False
    deadline_urgency = 0.0
    if deadline is not None:
        raw_days = (deadline - now).days
        days_until_deadline = raw_days
        effective_days = raw_days
        if category == "recommendation":
            effective_days -= _RECOMMENDATION_LEAD_TIME_DAYS
            lead_time_applied = True
        deadline_urgency = 100.0 * _deadline_urgency_fraction(effective_days)

    workload_pressure = _clamp(
        100.0 * (estimated_minutes or 0) / _WORKLOAD_PRESSURE_CAP_MINUTES
    )

    requirement_importance = 100.0 if required else 40.0

    if status == "Blocked":
        dependency_pressure = 100.0
    elif has_dependencies:
        dependency_pressure = 40.0
    else:
        dependency_pressure = 0.0

    incomplete_progress = _INCOMPLETE_PROGRESS_BY_STATUS.get(status, 100.0)

    score = (
        _DEADLINE_URGENCY_WEIGHT * deadline_urgency
        + _WORKLOAD_PRESSURE_WEIGHT * workload_pressure
        + _REQUIREMENT_IMPORTANCE_WEIGHT * requirement_importance
        + _DEPENDENCY_PRESSURE_WEIGHT * dependency_pressure
        + _INCOMPLETE_PROGRESS_WEIGHT * incomplete_progress
    )

    facts = _format_facts(
        days_until_deadline=days_until_deadline,
        estimated_minutes=estimated_minutes,
        required=required,
        status=status,
        has_dependencies=has_dependencies,
        lead_time_applied=lead_time_applied,
    )

    return PriorityBreakdown(
        score=round(score, 1),
        deadline_urgency=round(deadline_urgency, 1),
        workload_pressure=round(workload_pressure, 1),
        requirement_importance=round(requirement_importance, 1),
        dependency_pressure=round(dependency_pressure, 1),
        incomplete_progress=round(incomplete_progress, 1),
        days_until_deadline=days_until_deadline,
        explanation_facts=facts,
    )


def _format_facts(
    *,
    days_until_deadline: int | None,
    estimated_minutes: int | None,
    required: bool,
    status: str,
    has_dependencies: bool,
    lead_time_applied: bool,
) -> str:
    parts: list[str] = []
    if days_until_deadline is None:
        parts.append("no known deadline")
    elif days_until_deadline < 0:
        parts.append(f"deadline was {abs(days_until_deadline)} day(s) ago")
    else:
        parts.append(f"deadline is {days_until_deadline} day(s) away")
    if lead_time_applied:
        parts.append(
            f"recommenders typically need ~{_RECOMMENDATION_LEAD_TIME_DAYS} days lead time, "
            "so treat this as more urgent than the raw date suggests"
        )
    if estimated_minutes:
        parts.append(f"estimated {estimated_minutes} minutes of work")
    parts.append("required" if required else "optional")
    parts.append(f"status: {status}")
    if has_dependencies:
        parts.append("has unmet dependencies")
    return "; ".join(parts)


# --- Application Readiness -----------------------------------------------

# Category weights for the four breakdown components (sum to 1.0). Essays
# weighted highest by a wide margin — the one category a student can't
# self-report as "done" in one click (a rec letter or test score is binary;
# an essay is the actual bottleneck most students stall on), so it
# dominates the score the way it dominates real effort. `deadline` is its
# own weighted category (not a multiplicative penalty applied on top of the
# others) — see `_deadline_readiness` — so approaching a deadline always
# costs the same 10 points regardless of how done everything else is. There
# is deliberately no "other requirements" (portfolio/interview/
# major-specific/financial-aid) category — nothing in the UI tracks
# progress on those, so scoring them (at any fixed value) would either
# misrepresent real completion or just be dead weight; better to not claim
# to measure them at all.
_ESSAYS_WEIGHT = 0.50
_RECOMMENDATIONS_WEIGHT = 0.20
_TESTING_WEIGHT = 0.20
_DEADLINE_WEIGHT = 0.10

# Within a category, a required requirement counts this many times an
# optional one — .agents-cli-spec.md: "critical requirements should have
# higher weight than optional components."
_REQUIRED_COMPLETION_WEIGHT = 3.0
_OPTIONAL_COMPLETION_WEIGHT = 1.0

# A requirement whose own research is still `needs_verification` can't read
# as more than this, even if the student marked further progress on it — the
# requirement's DETAILS might still be wrong, so full credit would overstate
# readiness. This is the formula's "penalty for unresolved requirements."
_UNVERIFIED_COMPLETION_CAP = 60.0

_RECOMMENDATION_STATUS_COMPLETION = {
    RecommendationStatus.NOT_REQUESTED: 0.0,
    RecommendationStatus.REQUESTED: 50.0,
    RecommendationStatus.SUBMITTED: 100.0,
}


@dataclass(frozen=True)
class ReadinessResult:
    score: float
    essays: float
    recommendations: float
    testing: float
    deadline: float
    explanation_facts: str


def _category_completion(requirements: list[Requirement]) -> float:
    """Weighted-average `completion_percentage` across `requirements`
    (required requirements count `_REQUIRED_COMPLETION_WEIGHT` times an
    optional one), capping any requirement still flagged
    `needs_verification` at `_UNVERIFIED_COMPLETION_CAP`. Returns 100 — this
    category owes the student nothing — when the college has no requirements
    of this type at all."""
    if not requirements:
        return 100.0
    weighted_sum = 0.0
    total_weight = 0.0
    for req in requirements:
        weight = (
            _REQUIRED_COMPLETION_WEIGHT if req.required else _OPTIONAL_COMPLETION_WEIGHT
        )
        completion = req.completion_percentage
        if req.needs_verification:
            completion = min(completion, _UNVERIFIED_COMPLETION_CAP)
        weighted_sum += weight * completion
        total_weight += weight
    return weighted_sum / total_weight


def recommendations_for_college(
    recommendations: list[Recommendation], college_id: str
) -> list[Recommendation]:
    """Resolves the My Progress "All" option dynamically against `college_id`
    rather than a frozen snapshot — a recommender marked ALL covers a
    college added after the recommender was, not just the ones that existed
    at the time."""
    return [
        r
        for r in recommendations
        if college_id in r.college_ids or RECOMMENDATION_ALL_COLLEGES in r.college_ids
    ]


def required_recommendation_count(requirements: list[Requirement]) -> int:
    """How many individual letters this college actually needs — summed
    from its own required recommendation-type Requirement docs'
    `recommendation_count` (each defaulting to 1 if research didn't state a
    number, e.g. a doc persisted before that field existed). A college
    with no recommendation requirement on file at all (not yet researched,
    or genuinely doesn't need one) needs 0."""
    return sum(
        r.recommendation_count or 1
        for r in requirements
        if r.type == "recommendation" and r.required
    )


def _recommendations_completion(
    recommendations: list[Recommendation], required_count: int
) -> float:
    """Scores the recommenders assigned to this college against how many
    letters it actually needs (`required_count`), not just those
    recommenders' own average status — one Submitted letter at a college
    that needs two is 50% done, not 100%. No needs_verification cap
    (nothing here comes from research). Returns 100 when the college needs
    none — same "owes nothing" convention as `_category_completion`."""
    if required_count <= 0:
        return 100.0
    total = sum(_RECOMMENDATION_STATUS_COMPLETION[r.status] for r in recommendations)
    return _clamp(total / required_count)


def _deadline_readiness(days_until: int | None) -> float:
    """100 when the nearest deadline is 120+ days out (or there is no known
    deadline at all) ramping linearly down to 0 at or past the deadline —
    the inverse of `_deadline_urgency_fraction`, expressed as a 0-100
    readiness score like the other three categories so it can sit
    alongside them at its own fixed weight (`_DEADLINE_WEIGHT`)."""
    return 100.0 * (1 - _deadline_urgency_fraction(days_until))


def compute_readiness_score(
    requirements: list[Requirement],
    college_deadlines: CollegeDeadlines | None,
    recommendations: list[Recommendation],
    test_scores_submitted: bool,
    now: datetime | None = None,
) -> ReadinessResult:
    """.agents-cli-spec.md § Application Readiness Agent: "Readiness =
    weighted completion of required components with additional penalties
    for unresolved requirements, approaching deadlines, missing critical
    dependencies."

    Four weighted categories summing to `score`: essays (`_ESSAYS_WEIGHT`),
    recommendations (`_RECOMMENDATIONS_WEIGHT`), testing
    (`_TESTING_WEIGHT`), and deadline (`_DEADLINE_WEIGHT`).

    Only `essays` still comes from this college's own Requirement docs —
    `recommendations` comes from the student's account-wide recommender
    list (`recommendations`, already resolved to the ones covering THIS
    college via `recommendations_for_college`) scored against how many
    letters THIS college actually needs (`required_recommendation_count`,
    still read from this college's own Requirement docs — one Submitted
    letter at a two-letter school is 50% done, not 100%), and `testing`
    from their single account-wide test-scores answer (My Progress). There
    is no "other requirements" (portfolio/interview/major-specific/
    financial-aid) category — nothing in the UI tracks progress on those,
    so scoring them would either be a fake fixed value or dead weight.
    `deadline` is not a completion percentage either: it's how much room is
    left before the nearest deadline (`_deadline_readiness`), 100 if it's
    120+ days out or unknown, dropping toward 0 as it nears or passes —
    independent of how much work remains, so it costs a college the same
    up to 10 points whether or not everything else is already done.
    """
    now = now or datetime.now(UTC)

    essays = _category_completion([r for r in requirements if r.type == "essay"])
    recommendations_completion = _recommendations_completion(
        recommendations, required_recommendation_count(requirements)
    )
    testing = 100.0 if test_scores_submitted else 0.0

    nearest_deadline = earliest_college_deadline(college_deadlines)
    days_until_deadline: int | None = None
    if nearest_deadline is not None:
        days_until_deadline = (nearest_deadline - now).days
    deadline_readiness = _deadline_readiness(days_until_deadline)

    score = _clamp(
        _ESSAYS_WEIGHT * essays
        + _RECOMMENDATIONS_WEIGHT * recommendations_completion
        + _TESTING_WEIGHT * testing
        + _DEADLINE_WEIGHT * deadline_readiness
    )

    facts = _format_readiness_facts(
        essays=essays,
        recommendations=recommendations_completion,
        testing=testing,
        days_until_deadline=days_until_deadline,
        unresolved_count=sum(1 for r in requirements if r.needs_verification),
    )

    return ReadinessResult(
        score=round(score, 1),
        essays=round(essays, 1),
        recommendations=round(recommendations_completion, 1),
        testing=round(testing, 1),
        deadline=round(deadline_readiness, 1),
        explanation_facts=facts,
    )


def _format_readiness_facts(
    *,
    essays: float,
    recommendations: float,
    testing: float,
    days_until_deadline: int | None,
    unresolved_count: int,
) -> str:
    parts = [
        f"essays {essays:.0f}% complete",
        f"recommendations {recommendations:.0f}% complete",
        f"testing {testing:.0f}% complete",
    ]
    if days_until_deadline is None:
        parts.append("no known deadline")
    elif days_until_deadline < 0:
        parts.append(f"deadline was {abs(days_until_deadline)} day(s) ago")
    else:
        parts.append(f"deadline is {days_until_deadline} day(s) away")
    if unresolved_count:
        parts.append(
            f"{unresolved_count} requirement(s) still need research verification"
        )
    return "; ".join(parts)
