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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas import CollegeDeadlines

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
        deadline_urgency = _clamp(
            100.0 * (1 - effective_days / _DEADLINE_URGENCY_HORIZON_DAYS)
        )

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
