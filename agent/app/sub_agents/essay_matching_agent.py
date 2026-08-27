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

"""Essay Matching Agent — .agents-cli-spec.md § Architecture & Sub-Agents
step 3 (cross_college_analysis): "essay_matching_agent (LlmAgent, no
search; reads EssayPrompts + StudentMaterials) -> EssayMatch docs." Also
completes step 3 as originally spec'd, since Conflict (Milestone 10)
already built the other half.

.agents-cli-spec.md § Constraints: "Only the Essay Matching Agent reasons
about essay content, and only to score reuse-fit — it never rewrites,
edits, or coaches." This agent has no write tool that could touch a
StudentMaterial's own text; it only ever produces EssayPrompt/EssayMatch
docs, never modifies a material.

Two-stage pipeline, same "deterministic context -> bounded LLM reasoning"
shape as conflict_agent.py (there's no compute_essay_match_score formula
either — thematic reuse-fit is real reading-comprehension judgment):

1. `EssayContextAgent` (custom BaseAgent, no LLM) — gathers every
   essay-type Requirement (whose free-text description is the ONLY
   existing source of prompt text — nothing populates the separate
   EssayPrompt collection yet) and every StudentMaterial. Also fetches
   already-persisted EssayPrompt/EssayMatch docs so the persist step can
   update existing docs in place by (requirement_id) / (prompt_id) rather
   than duplicating them every run.
2. `essay_analysis_agent` (LlmAgent, output_schema, no tools) — does BOTH
   halves of the job in one call: (a) structures each essay Requirement's
   free text into a clean EssayPrompt (word_limit/category), and (b) for
   each prompt, finds the single best-fitting existing material, if any,
   and scores the reuse-fit honestly — a superficial overlap must score
   low with an explained gap (spec test scenario), not get inflated to
   look like a real match. Never emits a match when nothing plausibly
   fits (a student having zero materials yet is not an error).

Every `requirement_id`/`material_id` the LLM emits is validated against
the known-id sets gathered in step 1 before anything is written —
mirrors conflict_agent.py's "never invent an id" discipline.

`StudentMaterial` docs themselves are created by the student directly
(`POST /api/materials`, app/api.py) — there is no agent-driven material
creation. Without this, essay matching would have nothing to match
against; found necessary while building this milestone, same as
Milestone 9's manual requirement-progress endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Literal

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import BaseModel, Field

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config
from app.schemas import EssayMatch, EssayPrompt
from app.tools import firestore_tools as ft

_EXCERPT_CHARS = 500  # enough for real thematic comparison, cheap enough to batch


class EssayContextAgent(BaseAgent):
    def __init__(self, name: str = "essay_context_agent"):
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
        college_name_by_id = {college.id: college.name for college in colleges}
        requirements = ft.get_requirements(user_id, college_ids)
        essay_requirements = [r for r in requirements if r.type == "essay"]
        materials = ft.get_student_materials(user_id)

        existing_prompts = []
        for college_id in college_ids:
            existing_prompts.extend(ft.get_essay_prompts(user_id, college_id))
        existing_prompt_by_requirement = {
            prompt.requirement_id: prompt.id
            for prompt in existing_prompts
            if prompt.requirement_id
        }
        existing_match_by_prompt = {
            match.prompt_id: match.id for match in ft.get_essay_matches(user_id)
        }

        requirements_payload = [
            {
                "requirement_id": req.id,
                "college_name": college_name_by_id.get(req.college_id, req.college_id),
                "description": req.description,
                "required": req.required,
            }
            for req in essay_requirements
        ]
        materials_payload = [
            {
                "id": material.id,
                "title": material.title,
                "type": material.type.value,
                "topic": material.topic,
                "description": material.description,
                "excerpt": (material.partial_text or "")[:_EXCERPT_CHARS],
                "word_count": material.word_count,
                "themes": material.themes,
            }
            for material in materials
        ]

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "essay_context": {
                        "essay_requirements": requirements_payload,
                        "materials": materials_payload,
                    },
                    "essay_known_requirement_ids": [r.id for r in essay_requirements],
                    "essay_known_material_ids": [m.id for m in materials],
                    "essay_college_by_requirement": {
                        r.id: r.college_id for r in essay_requirements
                    },
                    "essay_existing_prompt_by_requirement": existing_prompt_by_requirement,
                    "essay_existing_match_by_prompt": existing_match_by_prompt,
                }
            ),
        )


class ExtractedEssayPrompt(BaseModel):
    requirement_id: str = Field(
        description="Must exactly match a requirement_id from ESSAY REQUIREMENTS."
    )
    text: str = Field(
        description="The clean prompt text/question itself — strip labels like "
        "'Supplemental Prompt 1 (Academic Interest):' down to just what's being asked."
    )
    word_limit: int | None = Field(
        default=None,
        description="An integer ONLY if a specific word limit is literally stated "
        "in the description — null otherwise, never guessed.",
    )
    category: Literal[
        "personal_statement",
        "supplemental",
        "why_us",
        "activity",
        "community",
        "identity",
        "other",
    ]
    required: bool = True


class MaterialMatch(BaseModel):
    requirement_id: str = Field(
        description="Must exactly match a requirement_id from ESSAY REQUIREMENTS — "
        "links this match back to that same prompt."
    )
    material_id: str = Field(
        description="The single best-fitting material's id, copied from MATERIALS."
    )
    match_score: float = Field(
        ge=0,
        le=100,
        description="Honest reuse-fit 0-100 — a superficial overlap scores low, not inflated.",
    )
    shared_themes: list[str] = Field(default_factory=list)
    recommendation: Literal["adapt", "new"] = Field(
        description="'adapt' only when reuse is genuinely reasonable; 'new' when even "
        "the best available material doesn't really fit."
    )
    reasoning: str = Field(
        description="Plain sentence grounded in the actual prompt and material text — "
        "if scoring low, say exactly what's missing."
    )


class EssayAnalysisResult(BaseModel):
    prompts: list[ExtractedEssayPrompt]
    matches: list[MaterialMatch] = Field(
        default_factory=list,
        description="Omit a requirement_id entirely if no material is even plausibly "
        "related, or the student has no materials yet — never force a low-confidence "
        "match just to have an answer.",
    )


_ESSAY_ANALYSIS_INSTRUCTION = """You are the Essay Matching Agent for
Collegentic. You do TWO things, grounded only in the data given below. You
NEVER write, rewrite, edit, or coach an essay — you only extract and
compare, scoring reuse-fit.

1. STRUCTURE each essay requirement's free-text description into a clean
   prompt (see ExtractedEssayPrompt fields) — one entry per
   requirement_id given.

2. For each prompt, decide whether ANY of the student's EXISTING materials
   is a plausible candidate to adapt/reuse for it. If one is a genuine
   thematic fit (even partial), emit ONE MaterialMatch naming that single
   best material — score honestly: a strong, close thematic overlap
   scores high; a superficial or shallow overlap scores low, with your
   reasoning explaining exactly what's missing, not glossed over.
   Recommend "adapt" only when reuse is genuinely reasonable; recommend
   "new" when the best available material still doesn't really fit. If NO
   material is even plausibly related to a prompt — or the student has no
   materials at all — do not emit a match for that requirement_id.

STRICT RULES:
- Every requirement_id you output MUST come from ESSAY REQUIREMENTS below.
- Every material_id you output MUST come from MATERIALS below.
- Never invent a word_limit, theme, or score not grounded in the given text.
- Write `reasoning` as a short, plain sentence: no markdown formatting, no
  em dashes.

DATA (essay requirements needing a clean prompt, and the student's
existing materials to compare them against):
{essay_context}

Respond with a single raw JSON object matching EssayAnalysisResult."""


def _persist_essay_analysis(callback_context) -> None:
    """Runs as an after_agent_callback. Prompts are upserted by
    (requirement_id) — one prompt per essay requirement, in place across
    runs. Matches are upserted by (prompt_id) — one match per prompt,
    freshest analysis wins, same "recompute is safe, nothing to preserve"
    reasoning as priority/readiness (EssayMatch, unlike Conflict, has no
    student-set status to protect from being overwritten)."""
    user_id = callback_context.user_id
    result = callback_context.state.get("essay_analysis") or {}
    known_requirement_ids = set(
        callback_context.state.get("essay_known_requirement_ids") or []
    )
    known_material_ids = set(
        callback_context.state.get("essay_known_material_ids") or []
    )
    college_by_requirement = (
        callback_context.state.get("essay_college_by_requirement") or {}
    )
    existing_prompt_by_requirement = (
        callback_context.state.get("essay_existing_prompt_by_requirement") or {}
    )
    existing_match_by_prompt = (
        callback_context.state.get("essay_existing_match_by_prompt") or {}
    )

    prompts_to_upsert: list[EssayPrompt] = []
    for item in result.get("prompts", []):
        req_id = item["requirement_id"]
        if req_id not in known_requirement_ids:
            continue
        prompts_to_upsert.append(
            EssayPrompt(
                id=existing_prompt_by_requirement.get(req_id),
                college_id=college_by_requirement[req_id],
                text=item["text"],
                word_limit=item.get("word_limit"),
                required=item.get("required", True),
                category=item.get("category"),
                requirement_id=req_id,
            )
        )

    requirement_to_prompt_id: dict[str, str] = {}
    if prompts_to_upsert:
        prompt_ids = ft.save_essay_prompts(user_id, prompts_to_upsert)
        requirement_to_prompt_id = {
            prompt.requirement_id: prompt_id
            for prompt, prompt_id in zip(prompts_to_upsert, prompt_ids, strict=True)
        }

    matches_to_upsert: list[EssayMatch] = []
    for item in result.get("matches", []):
        req_id = item["requirement_id"]
        material_id = item["material_id"]
        prompt_id = requirement_to_prompt_id.get(req_id)
        if prompt_id is None or material_id not in known_material_ids:
            continue
        matches_to_upsert.append(
            EssayMatch(
                id=existing_match_by_prompt.get(prompt_id),
                prompt_id=prompt_id,
                college_id=college_by_requirement[req_id],
                material_id=material_id,
                match_score=item["match_score"],
                shared_themes=item.get("shared_themes", []),
                recommendation=item["recommendation"],
                reasoning=item["reasoning"],
                computed_at=ft.now(),
            )
        )

    if matches_to_upsert:
        ft.save_essay_matches(user_id, matches_to_upsert)

    log_agent_run_complete(
        callback_context,
        f"Structured {len(prompts_to_upsert)} essay prompt(s), "
        f"found {len(matches_to_upsert)} reuse match(es).",
    )


essay_analysis_agent = LlmAgent(
    model=config.worker_model,
    name="essay_analysis_agent",
    description="Structures essay prompts from requirement text and scores reuse-fit against the student's existing materials.",
    instruction=_ESSAY_ANALYSIS_INSTRUCTION,
    output_schema=EssayAnalysisResult,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="essay_analysis",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_persist_essay_analysis,
)

essay_matching_pipeline = SequentialAgent(
    name="essay_matching_pipeline",
    description="Gathers essay requirements and student materials deterministically, then structures prompts and scores reuse-fit.",
    sub_agents=[EssayContextAgent(), essay_analysis_agent],
)
