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

"""Requirements Agent — .agents-cli-spec.md § Requirements Agent.

Two-stage pipeline, mirroring deep-search's research_pipeline shape
(section_researcher -> [evaluator -> escalation -> follow-up] loop ->
report_composer):

1. `requirements_confidence_loop` (LoopAgent, bounded) — grades the RAW
   research findings (not yet structured) for completeness/clarity and, on
   a "fail" grade, runs a targeted follow-up search that merges new
   findings back into `raw_research_findings`. Stops early on "pass" via
   the same EscalationChecker trick as deep-search, or after
   config.max_research_confidence_iterations.
2. `requirements_agent` — runs once, after the loop, and is the only step
   that writes to Firestore: structures the (now-refined) findings into
   Requirement docs AND persists the ResearchSource docs those requirements
   cite, now that each source can be attributed to a real college_id (see
   .agents-cli-spec.md's Milestone 3 revision note for why this moved here
   rather than living in the Research Agent).

`requirements_pipeline` is the exported composable unit — Milestone 5's
Orchestrator will use it as-is, immediately after college_research_agent.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Literal
from urllib.parse import urlparse

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import google_search
from pydantic import BaseModel, Field

from app.callbacks import (
    collect_research_sources_callback,
    log_agent_run_complete,
    log_agent_run_start,
)
from app.config import config
from app.schemas import ConfidenceLevel, Requirement, ResearchSource
from app.tools import firestore_tools as ft

logger = logging.getLogger(__name__)

_OFFICIAL_DOMAIN_ALLOWLIST = {
    "commonapp.org",
    "studentaid.gov",
    "cssprofile.collegeboard.org",
}


def _is_official_source(url: str, title: str = "") -> bool:
    """Heuristic, not a lookup against each college's real domain: a source
    is treated as official if it's a .edu page or a known quasi-official
    application/aid portal.

    Found live (Milestone 4): Gemini's `google_search` grounding chunks
    return an opaque `vertexaisearch.cloud.google.com/grounding-api-redirect/...`
    link as `url` — never the real page URL — so domain can't be parsed from
    it. `chunk.web.domain` is also frequently unset (Milestone 3 finding).
    But `title` reliably holds the bare domain string when Gemini has no
    better page title (confirmed live: title="rice.edu" for an official
    Rice admissions page) — so title is checked first, url only as a
    fallback in case a future/different grounding response ever returns a
    direct link.
    """
    candidates = [title.lower().removeprefix("www.")]
    url_domain = urlparse(url).netloc.lower().removeprefix("www.")
    if url_domain and "vertexaisearch" not in url_domain:
        candidates.append(url_domain)
    return any(
        domain.endswith(".edu")
        or any(
            domain == allowed or domain.endswith(f".{allowed}")
            for allowed in _OFFICIAL_DOMAIN_ALLOWLIST
        )
        for domain in candidates
        if domain
    )


# --- Stage 1: confidence-refinement loop over RAW findings ------------------


class SearchQuery(BaseModel):
    search_query: str = Field(
        description="A specific, targeted follow-up search query."
    )


class Feedback(BaseModel):
    grade: Literal["pass", "fail"] = Field(
        description="'pass' if findings are complete/clear enough to extract structured "
        "requirements from, 'fail' if there are gaps a follow-up search could fill."
    )
    comment: str = Field(description="What's missing or unclear, if grade is 'fail'.")
    follow_up_queries: list[SearchQuery] | None = Field(
        default=None,
        description="Targeted queries to fill the gaps. Null/empty if grade is 'pass'.",
    )


findings_evaluator = LlmAgent(
    model=config.critic_model,
    name="findings_evaluator",
    description="Grades whether research findings are complete enough for structured extraction.",
    instruction="""You are a meticulous QA analyst reviewing college application research
findings in `raw_research_findings` (state below).

RAW RESEARCH FINDINGS:
{raw_research_findings}

Grade "fail" if: a college is missing one of the required categories entirely
(deadlines, testing, recommendations, essay prompts, portfolio, interview,
financial aid); or there are multiple "UNCERTAIN:" markers that a more
targeted search could likely resolve. Otherwise grade "pass" — a few
genuinely UNCERTAIN items is expected and fine; your job is to catch gaps a
follow-up search could plausibly fix, not to demand perfection.

If "fail", write 5-7 specific follow-up search queries targeting exactly the
missing/unclear items (e.g. "Rice University supplemental essay prompts
2026-2027" rather than a generic re-search).

Respond with a single raw JSON object matching the Feedback schema.""",
    output_schema=Feedback,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="findings_evaluation",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=log_agent_run_complete,
)


class EscalationChecker(BaseAgent):
    """Stops the loop once findings_evaluator grades 'pass'. Same trick as
    deep-search's EscalationChecker: yield escalate=True to end a LoopAgent
    on a data-driven condition rather than only on max_iterations."""

    def __init__(self, name: str = "requirements_escalation_checker"):
        super().__init__(name=name)

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        evaluation = ctx.session.state.get("findings_evaluation")
        if evaluation and evaluation.get("grade") == "pass":
            yield Event(author=self.name, actions=EventActions(escalate=True))
        else:
            yield Event(author=self.name)


def _after_followup_search(callback_context) -> None:
    collect_research_sources_callback(callback_context)
    log_agent_run_complete(callback_context)


findings_followup_search = LlmAgent(
    model=config.worker_model,
    name="findings_followup_search",
    description="Runs targeted follow-up searches and merges new findings into raw_research_findings.",
    instruction="""You are running a targeted refinement pass on college research.
The previous findings were graded incomplete.

CURRENT FINDINGS:
{raw_research_findings}

EVALUATOR FEEDBACK:
{findings_evaluation}

Execute EVERY query listed in the evaluator's follow-up_queries using
`google_search`. Merge what you learn into the existing findings and output
the COMPLETE, updated findings — same `## <College Name>` header structure
as the input, all colleges present, not just the ones you re-researched.
Keep the same "UNCERTAIN: ..." convention for anything still unclear —
never invent to fill a gap you couldn't actually resolve.""",
    tools=[google_search],
    output_key="raw_research_findings",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_after_followup_search,
)

requirements_confidence_loop = LoopAgent(
    name="requirements_confidence_loop",
    max_iterations=config.max_research_confidence_iterations,
    sub_agents=[
        findings_evaluator,
        EscalationChecker(),
        findings_followup_search,
    ],
)


# --- Stage 2: structure findings into Requirement + ResearchSource docs -----


class ExtractedRequirement(BaseModel):
    college_name: str = Field(
        description="Must exactly match a college name/header from the findings."
    )
    type: str = Field(
        description="Short category: essay, recommendation, testing, deadline, "
        "financial_aid, portfolio, interview, or major_specific."
    )
    description: str = Field(
        description="A specific, concrete description — e.g. the exact essay prompt "
        "text, or 'Regular Decision deadline: January 5'."
    )
    required: bool = True
    deadline_iso: str | None = Field(
        default=None, description="ISO 8601 date (YYYY-MM-DD) if found, else null."
    )
    category: str | None = None
    confidence: Literal["high", "medium", "low"]
    needs_verification: bool = Field(
        description="True if the findings marked this UNCERTAIN or it seems outdated/contradictory."
    )
    source_short_ids: list[str] = Field(
        default_factory=list,
        description="src-N ids from AVAILABLE SOURCES that support this specific requirement.",
    )


class RequirementsExtraction(BaseModel):
    requirements: list[ExtractedRequirement]


_REQUIREMENTS_INSTRUCTION = """You are the Requirements Agent. Convert the research
findings below into a structured list of application requirements — one
entry per DISCRETE requirement per college. Do not summarize: each essay
prompt is its own requirement, each deadline is its own requirement,
testing policy is its own requirement, each recommendation-letter rule is
its own requirement, and so on.

RAW RESEARCH FINDINGS:
{raw_research_findings}

AVAILABLE SOURCES (short_id -> title/url/domain/claims):
{sources}

For every requirement:
- college_name: must exactly match a college name/header from the findings.
- confidence: "high" only if a source directly and unambiguously stated
  this; "medium" if inferred/implied; "low" if the findings marked it
  UNCERTAIN or you are extrapolating.
- needs_verification: true if the findings marked this UNCERTAIN or the
  information seems outdated or contradicted elsewhere in the findings.
- source_short_ids: the src-N ids whose supported_claims text overlaps with
  this specific requirement. Use [] rather than guessing a source.

Never invent a requirement, deadline, or number that wasn't in the
findings. If the findings marked something UNCERTAIN, still extract it as a
requirement — confidence="low", needs_verification=true, description taken
from what the findings actually said (including the uncertainty itself).

Respond with a single raw JSON object matching the RequirementsExtraction schema."""


def _persist_requirements_and_sources(callback_context) -> None:
    """Writes Requirement + (deduped, per-college) ResearchSource docs.
    Runs as an after_agent_callback since output_schema agents can't also
    call tools mid-turn — this is where the structured output actually
    lands in Firestore, same division of labor as citation_replacement_callback
    in deep-search."""
    user_id = callback_context.user_id
    extraction = callback_context.state.get("extracted_requirements") or {}
    extracted = extraction.get("requirements", [])
    name_to_id: dict[str, str] = callback_context.state.get("college_name_to_id", {})
    sources_pool: dict[str, dict] = callback_context.state.get("sources", {})

    if not extracted:
        log_agent_run_complete(callback_context)
        return

    source_doc_id_cache: dict[
        tuple[str, str], str
    ] = {}  # (short_id, college_id) -> doc id
    requirements: list[Requirement] = []
    skipped_colleges: set[str] = set()

    for item in extracted:
        college_id = name_to_id.get(item["college_name"])
        if not college_id:
            skipped_colleges.add(item["college_name"])
            continue

        resolved_source_ids: list[str] = []
        for short_id in item.get("source_short_ids", []):
            source_info = sources_pool.get(short_id)
            if not source_info:
                continue
            cache_key = (short_id, college_id)
            if cache_key not in source_doc_id_cache:
                claims = source_info.get("supported_claims", [])
                avg_confidence = (
                    sum(c["confidence"] for c in claims) / len(claims)
                    if claims
                    else 0.5
                )
                source_title = source_info.get("title") or source_info["url"]
                source = ResearchSource(
                    college_id=college_id,
                    url=source_info["url"],
                    title=source_title,
                    date_researched=ft.now(),
                    official=_is_official_source(source_info["url"], source_title),
                    confidence=(
                        ConfidenceLevel.HIGH
                        if avg_confidence >= 0.66
                        else ConfidenceLevel.MEDIUM
                        if avg_confidence >= 0.33
                        else ConfidenceLevel.LOW
                    ),
                )
                [doc_id] = ft.save_research_sources(user_id, [source])
                source_doc_id_cache[cache_key] = doc_id
            resolved_source_ids.append(source_doc_id_cache[cache_key])

        requirements.append(
            Requirement(
                college_id=college_id,
                type=item["type"],
                description=item["description"],
                required=item.get("required", True),
                deadline=item.get("deadline_iso") or None,
                category=item.get("category"),
                confidence=item["confidence"],
                needs_verification=item.get("needs_verification", False),
                source_ids=resolved_source_ids,
            )
        )

    if requirements:
        ft.save_requirements(user_id, requirements)
    if skipped_colleges:
        logger.warning(
            "requirements_agent: no Firestore college_id for %s — extracted "
            "requirements for these were dropped, not written unattributed.",
            skipped_colleges,
        )

    log_agent_run_complete(callback_context)


requirements_agent = LlmAgent(
    model=config.critic_model,
    name="requirements_agent",
    description="Structures research findings into Requirement + ResearchSource records.",
    instruction=_REQUIREMENTS_INSTRUCTION,
    output_schema=RequirementsExtraction,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="extracted_requirements",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_persist_requirements_and_sources,
)

requirements_pipeline = SequentialAgent(
    name="requirements_pipeline",
    description="Refines research findings to a quality bar, then structures them into "
    "Requirement + ResearchSource records.",
    sub_agents=[requirements_confidence_loop, requirements_agent],
)
