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

"""Application Readiness Agent — .agents-cli-spec.md § Application Readiness
Agent.

Same two-stage shape as every other pipeline stage (app/sub_agents/
priority_agent.py is the direct template): `CollegeReadinessContextAgent`
(custom BaseAgent, no LLM) computes every tracked college's readiness score
and breakdown deterministically via app/tools/scoring.py, then
`readiness_explanation_agent` (LlmAgent, output_schema, no tools) rewrites
each college's pre-computed facts into ONE natural sentence — it never sees
or invents the numbers, only explains them.

Batches every college's explanation into ONE Gemini call regardless of
college count (cost control), same as the priority explanation step.

Re-scores every tracked college on every pipeline run — cheap (one
deterministic pass over already-fetched Requirements + one batched LLM
call, no web search, no re-persisting Requirements themselves), and
deadlines/manually-updated requirement progress both need to be reflected
without waiting for a full re-research pass.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import BaseModel, Field

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config
from app.schemas import Readiness, ReadinessBreakdown
from app.tools import firestore_tools as ft
from app.tools.scoring import compute_readiness_score, recommendations_for_college


class CollegeReadinessContextAgent(BaseAgent):
    def __init__(self, name: str = "college_readiness_context_agent"):
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
        all_recommendations = ft.get_recommendations(user_id)
        test_scores_submitted = ft.get_test_scores_submitted(user_id)

        context_payload = {}
        for college in colleges:
            requirements = ft.get_requirements(user_id, [college.id])
            college_recommendations = recommendations_for_college(
                all_recommendations, college.id
            )
            result = compute_readiness_score(
                requirements, college.deadlines, college_recommendations, test_scores_submitted
            )
            context_payload[college.id] = {
                "name": college.name,
                "score": result.score,
                "breakdown": {
                    "essays": result.essays,
                    "recommendations": result.recommendations,
                    "testing": result.testing,
                    "deadline": result.deadline,
                },
                "facts": result.explanation_facts,
            }

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"college_readiness_context": context_payload}
            ),
        )


class ReadinessExplanation(BaseModel):
    college_id: str = Field(description="Must exactly match a key from COLLEGES.")
    explanation: str = Field(
        description="ONE natural, concise sentence explaining why this college has "
        "this readiness score — style: 'MIT is 82% ready because recommendations "
        "and testing are complete, but one essay is only 50% complete and the "
        "deadline is approaching.' Use ONLY the given facts; never invent a "
        "percentage or detail not present in them."
    )


class ReadinessExplanationList(BaseModel):
    explanations: list[ReadinessExplanation]


_READINESS_EXPLANATION_INSTRUCTION = """You write one-sentence application
readiness explanations for a college applicant. For EACH college below,
write a natural, plain-language sentence explaining why it has the
readiness score it has, echoing its given facts, don't add anything they
didn't say. No markdown formatting and no em dashes, write it like an
ordinary sentence.

COLLEGES (college_id -> name, score 0-100, breakdown, facts):
{college_readiness_context}

Respond with a single raw JSON object matching the ReadinessExplanationList
schema, with one entry per college_id above."""


def _persist_readiness(callback_context) -> None:
    """Runs as an after_agent_callback for the same reason as every other
    output_schema agent's persist step in this codebase.

    Writes one college at a time with a pacing pause between them, same
    technique as requirements_agent.py's Stage 1/3/4 — the LLM explanation
    call above is still one batched request (cost control), this only
    staggers the already-computed results landing in Firestore, so the
    Colleges table's Readiness column reveals per college instead of every
    row jumping to a score in the same poll tick.
    """
    user_id = callback_context.user_id
    context_payload = callback_context.state.get("college_readiness_context") or {}
    explanation_list = callback_context.state.get("readiness_explanations") or {}
    explanations_by_id = {
        item["college_id"]: item["explanation"]
        for item in explanation_list.get("explanations", [])
    }

    for i, (college_id, info) in enumerate(context_payload.items()):
        if i > 0:
            time.sleep(0.4)
        # Falls back to the raw deterministic facts if the LLM ever drops a
        # college_id — every college still gets a truthful explanation,
        # never a blank one, even if the LLM's phrasing pass is incomplete.
        explanation = explanations_by_id.get(college_id) or info["facts"]
        readiness = Readiness(
            score=info["score"],
            breakdown=ReadinessBreakdown(**info["breakdown"]),
            explanation=explanation,
            computed_at=ft.now(),
        )
        ft.save_readiness(user_id, college_id, readiness)

    log_agent_run_complete(
        callback_context, f"Scored readiness for {len(context_payload)} college(s)."
    )


readiness_explanation_agent = LlmAgent(
    model=config.worker_model,
    name="readiness_explanation_agent",
    description="Writes natural-language explanations for pre-computed college readiness scores.",
    instruction=_READINESS_EXPLANATION_INSTRUCTION,
    output_schema=ReadinessExplanationList,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="readiness_explanations",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_persist_readiness,
)

readiness_pipeline = SequentialAgent(
    name="readiness_pipeline",
    description="Scores every tracked college's application readiness deterministically, then explains each in plain language.",
    sub_agents=[CollegeReadinessContextAgent(), readiness_explanation_agent],
)
