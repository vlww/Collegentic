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

"""Requirement Conflict Agent — .agents-cli-spec.md § Architecture &
Sub-Agents step 3 (cross_college_analysis): "conflict_agent (LlmAgent, no
search; reads all tracked colleges' Requirements + Recommendations) ->
Conflict docs." Only the conflict half of that step — essay_matching_agent
is Milestone 11; this agent never touches EssayPrompts/StudentMaterials/
EssayMatch, so `type: "essay"` conflicts can't fire yet.

Unlike Priority/Readiness, there's no `compute_conflict_*` deterministic
formula module: whether two colleges' recommendation or testing policies
are genuinely INCOMPATIBLE (spec test scenario: "two colleges, similar
requirements, different recommender preferences -> distinguished, not
conflated") is a real reading-comprehension judgment over free-text
Requirement descriptions, not a number to compute. So this is a two-stage
pipeline where the SECOND stage does the actual detection, not just
phrasing:

1. `ConflictContextAgent` (custom BaseAgent, no LLM) — gathers exactly the
   facts a conflict could be grounded in (recommendation/testing/
   financial-aid Requirements per college, Recommendation docs, and one
   genuinely deterministic pre-computed signal: which colleges' nearest
   deadlines cluster within days of each other). This bounds what the LLM
   can possibly hallucinate about — it never sees raw Firestore, only this
   compact payload.
2. `conflict_detection_agent` (LlmAgent, output_schema, no tools) — the
   actual reasoning step. Every `college_id/related_requirement_id` it
   emits is validated against the known-id sets in the persist callback;
   anything not in that payload is dropped rather than trusted (belt and
   suspenders on top of the instruction's own "never invent" rule).

Conflicts persist across runs by a (type, sorted college_ids) fingerprint:
a freshly-detected conflict matching an existing doc's fingerprint updates
that doc in place (preserving whatever `status` the student already set —
acknowledging/resolving is exclusively a student action, never
overwritten by a re-run); a previously open/acknowledged conflict whose
fingerprint isn't detected this run is auto-resolved, since the underlying
condition apparently no longer holds (e.g. a recommender got identified).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Literal

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import BaseModel, Field

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config, llm_timeout_config
from app.schemas import Conflict, ConflictStatus, RecommendationStatus
from app.tools import firestore_tools as ft
from app.tools.scoring import earliest_college_deadline, recommendations_for_college

_DEADLINE_CLUSTER_WINDOW_DAYS = (
    5  # consecutive deadlines this close together form one cluster
)
_CROSS_REFERENCE_TYPES = ("recommendation", "testing", "financial_aid")


class ConflictContextAgent(BaseAgent):
    def __init__(self, name: str = "conflict_context_agent"):
        super().__init__(
            name=name,
            before_agent_callback=log_agent_run_start,
            after_agent_callback=log_agent_run_complete,
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        user_id = ctx.session.user_id
        colleges = ft.get_tracked_colleges(user_id)
        college_ids = [college.id for college in colleges]
        requirements = ft.get_requirements(user_id, college_ids)
        recommendations = ft.get_recommendations(user_id)

        requirements_by_college: dict[str, list] = {}
        for req in requirements:
            if req.type in _CROSS_REFERENCE_TYPES:
                requirements_by_college.setdefault(req.college_id, []).append(req)

        known_requirement_ids: list[str] = []
        colleges_payload = []
        dated_deadlines: list[tuple[str, str, datetime]] = []
        for college in colleges:
            college_reqs = requirements_by_college.get(college.id, [])
            known_requirement_ids.extend(req.id for req in college_reqs)
            matched_recommenders = sum(
                1
                for rec in recommendations_for_college(recommendations, college.id)
                if rec.status != RecommendationStatus.NOT_REQUESTED
            )
            recommendation_reqs = [
                r for r in college_reqs if r.type == "recommendation"
            ]
            deadline = earliest_college_deadline(college.deadlines)
            if deadline is not None:
                dated_deadlines.append((college.id, college.name, deadline))
            colleges_payload.append(
                {
                    "id": college.id,
                    "name": college.name,
                    "earliest_deadline": deadline.date().isoformat()
                    if deadline
                    else None,
                    "recommendation_requirements": [
                        {"id": r.id, "description": r.description}
                        for r in recommendation_reqs
                    ],
                    "recommendation_gap": len(recommendation_reqs)
                    - matched_recommenders,
                    "testing_requirements": [
                        {"id": r.id, "description": r.description}
                        for r in college_reqs
                        if r.type == "testing"
                    ],
                    "financial_aid_requirements": [
                        {"id": r.id, "description": r.description}
                        for r in college_reqs
                        if r.type == "financial_aid"
                    ],
                }
            )

        dated_deadlines.sort(key=lambda t: t[2])
        clusters: list[list[tuple[str, str, datetime]]] = []
        current: list[tuple[str, str, datetime]] = []
        for entry in dated_deadlines:
            if (
                current
                and (entry[2] - current[-1][2]).days <= _DEADLINE_CLUSTER_WINDOW_DAYS
            ):
                current.append(entry)
            else:
                if len(current) >= 2:
                    clusters.append(current)
                current = [entry]
        if len(current) >= 2:
            clusters.append(current)

        deadline_clusters_payload = [
            {
                "college_ids": [c[0] for c in cluster],
                "college_names": [c[1] for c in cluster],
                "dates": [c[2].date().isoformat() for c in cluster],
            }
            for cluster in clusters
        ]

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "conflict_context": {
                        "colleges": colleges_payload,
                        "deadline_clusters": deadline_clusters_payload,
                    },
                    "conflict_known_college_ids": college_ids,
                    "conflict_known_requirement_ids": known_requirement_ids,
                }
            ),
        )


class DetectedConflict(BaseModel):
    type: Literal["recommendation", "deadline", "testing", "financialAid"]
    college_ids: list[str] = Field(
        description="At least 2 college ids, copied verbatim from the given data — "
        "every college genuinely involved in this specific conflict."
    )
    description: str = Field(
        description="Plain-language description of the conflict, grounded only in "
        "the given facts — cite what's actually different, not a generic sentence."
    )
    recommendation: str = Field(
        description="What the student should concretely do about it."
    )
    severity: Literal["low", "medium", "high"]
    related_requirement_ids: list[str] = Field(
        default_factory=list,
        description="Requirement ids from the given data this conflict references, if any.",
    )


class DetectedConflictList(BaseModel):
    conflicts: list[DetectedConflict]


_CONFLICT_DETECTION_INSTRUCTION = """You are the Requirement Conflict Agent
for Collegentic. You compare a student's tracked colleges' requirements to
find CROSS-COLLEGE conflicts — problems that only exist because the student
is applying to multiple schools at once. A single college's own requirement
is never itself a conflict.

Look for:
- RECOMMENDATION gaps: a college's `recommendation_gap` > 0 means it needs
  more recommendation-type items than currently have an identified
  recommender — flag this, especially when several colleges share the gap
  and the student needs one concrete plan for who writes what.
- RECOMMENDATION preference conflicts: two or more colleges whose
  recommendation_requirements descriptions specify genuinely different or
  incompatible recommender types (e.g. one wants a STEM teacher, another
  wants two teachers from different departments) — report these as their
  OWN conflict, distinct from a plain gap. Do not conflate two colleges
  with merely similar-sounding requirements into one conflict if their
  actual preferences differ.
- DEADLINE clustering: `deadline_clusters` below already lists colleges
  whose earliest deadlines fall within days of each other — describe the
  real workload risk this creates for the student.
- TESTING conflicts: colleges whose testing_requirements show a genuine,
  citable difference (e.g. conflicting score-choice/superscore policies, or
  a testing deadline that leaves no time to retake for another school).
- FINANCIAL AID conflicts: colleges whose financial_aid_requirements show a
  real tension (e.g. a financial aid deadline earlier than the application
  deadline, or differing form requirements like CSS Profile vs. FAFSA-only
  worth planning around together).

STRICT RULES:
- Every college_id and related_requirement_id you output MUST be copied
  from the data below — never invent one, never reference a college or
  requirement not listed there.
- A conflict must involve at least 2 colleges.
- If you find no genuine conflict, return an empty conflicts list — do not
  manufacture one just to have something to report.
- Ground every description in the specific facts given.
- Write `description` and `recommendation` as short, plain sentences: no
  markdown formatting, no em dashes.

DATA (colleges with their recommendation/testing/financial-aid requirements
and recommendation_gap, plus any deadline_clusters already computed):
{conflict_context}

Respond with a single raw JSON object matching DetectedConflictList."""


def _persist_conflicts(callback_context) -> None:
    """Runs as an after_agent_callback. See module docstring for the
    fingerprint-based merge: preserves student-set `status`, never re-opens
    a resolved conflict, and auto-resolves ones no longer detected."""
    user_id = callback_context.user_id
    detected = callback_context.state.get("detected_conflicts") or {}
    known_college_ids = set(
        callback_context.state.get("conflict_known_college_ids") or []
    )
    known_requirement_ids = set(
        callback_context.state.get("conflict_known_requirement_ids") or []
    )

    existing = ft.get_conflicts(user_id)
    existing_by_fingerprint: dict[tuple[str, tuple[str, ...]], list[Conflict]] = {}
    for conflict in existing:
        fingerprint = (conflict.type.value, tuple(sorted(conflict.college_ids)))
        existing_by_fingerprint.setdefault(fingerprint, []).append(conflict)

    fresh_fingerprints: set[tuple[str, tuple[str, ...]]] = set()
    to_upsert: list[Conflict] = []
    for item in detected.get("conflicts", []):
        college_ids = [cid for cid in item["college_ids"] if cid in known_college_ids]
        if len(college_ids) < 2:
            continue  # malformed/hallucinated — a conflict must span 2+ known colleges
        related_ids = [
            rid
            for rid in item.get("related_requirement_ids", [])
            if rid in known_requirement_ids
        ]
        fingerprint = (item["type"], tuple(sorted(college_ids)))
        fresh_fingerprints.add(fingerprint)
        match = existing_by_fingerprint.get(fingerprint)
        to_upsert.append(
            Conflict(
                id=match[0].id if match else None,
                type=item["type"],
                college_ids=college_ids,
                description=item["description"],
                recommendation=item["recommendation"],
                severity=item.get("severity", "medium"),
                related_requirement_ids=related_ids,
                status=match[0].status if match else ConflictStatus.OPEN,
            )
        )

    if to_upsert:
        ft.save_conflicts(user_id, to_upsert)

    auto_resolved = 0
    for fingerprint, matches in existing_by_fingerprint.items():
        if fingerprint in fresh_fingerprints:
            continue
        for conflict in matches:
            if conflict.status != ConflictStatus.RESOLVED:
                ft.update_conflict_status(user_id, conflict.id, ConflictStatus.RESOLVED)
                auto_resolved += 1

    summary = f"Detected {len(to_upsert)} conflict(s)"
    if auto_resolved:
        summary += f", auto-resolved {auto_resolved} no longer present"
    summary += "."
    log_agent_run_complete(callback_context, summary)


conflict_detection_agent = LlmAgent(
    model=config.worker_model,
    generate_content_config=llm_timeout_config(batched=True),
    name="conflict_detection_agent",
    description="Detects cross-college requirement conflicts (recommendations, deadlines, testing, financial aid) grounded only in given facts.",
    instruction=_CONFLICT_DETECTION_INSTRUCTION,
    output_schema=DetectedConflictList,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="detected_conflicts",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_persist_conflicts,
)

conflict_pipeline = SequentialAgent(
    name="conflict_pipeline",
    description="Gathers cross-college requirement facts deterministically, then detects and explains genuine conflicts among them.",
    sub_agents=[ConflictContextAgent(), conflict_detection_agent],
)
