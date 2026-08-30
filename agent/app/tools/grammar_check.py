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

"""Essay Editor's grammar-only check — a plain function, not an ADK
LlmAgent/pipeline: this is a single on-demand call triggered from a REST
route (app/api.py's /grammar-check), not a step in the college-research
pipeline, so there's no session/state-bus reason to wrap it in one. Same
"direct google.genai.Client() call, no ADK Runner" shape as
tests/eval/collegentic_behavior_quality.py's LLM-judge.

Two models:
1. `config.grammar_model` (Gemma) does a first grammar/spelling/punctuation
   detection pass over the essay text.
2. `config.worker_model` (Gemini Flash) does its OWN independent detection
   pass over the same text — not just a validator of Gemma's list. Found
   live: the original version only ever asked Gemini to narrow down
   whatever Gemma found, and returned early with zero issues the instant
   Gemma's own output was empty or unparseable (a real, frequent outcome —
   Gemma here is a small, MoE, "4B active params" model, genuinely weaker
   at this than Gemini) — Gemini, the actually-reliable model, never got a
   chance to look at the essay AT ALL in that case. Now Gemini always runs
   and always does its own real scan, with Gemma's candidates folded in as
   a second opinion rather than a gate: Gemma catches a few
   Gemini also would have; the value it adds is running before it, not
   being trusted alone.

Gemma specifically needs `GEMINI_API_KEY` (Google AI Studio) — confirmed
live against this project's real Vertex AI credentials: `genai.Client()`'s
own base-model catalog (`client.models.list(config={"query_base": True})`)
lists 24 Gemini models and zero Gemma ones, and every Gemma model id/region
combination tried 404s ("not found or your project does not have access to
it"). That's Vertex AI Model Garden access for Gemma specifically not being
enabled for this project — a separate, per-project opt-in Gemini doesn't
need — not a wrong model name. AI Studio serves Gemma directly with no
such enablement, so `_gemma_client` below routes ONLY the Gemma call
through it when `GEMINI_API_KEY` is set, leaving every other agent's
Vertex/ADC configuration in this app untouched; the Gemini validation call
right after still uses the app's normal ambient client.

Grammar-only, not a coach: only flags mechanical mistakes (spelling,
grammar, punctuation, subject-verb agreement) — never tone, content, or
structural feedback. Mirrors .agents-cli-spec.md's essay-content-reasoning
constraint ("only to score reuse-fit... never rewrites, edits, or coaches")
in spirit: this doesn't touch StudentMaterial.partial_text itself either —
it only ever returns suggestions for the student to accept or ignore
one at a time in the frontend; the actual edit happens client-side.

Every returned issue is re-verified in Python against the literal essay
text before being trusted (`_grounded_issues` below) — same "don't fully
trust the LLM for a hard invariant" discipline as requirements_agent.py's
needs_verification enforcement and essay_matching_agent.py's id validation.
An issue whose `original` text isn't found verbatim in the essay can't be
highlighted correctly client-side, so it's dropped rather than shown
broken.
"""

from __future__ import annotations

import json
import logging
import os
import re

from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.config import config

logger = logging.getLogger(__name__)


class GrammarIssue(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # The exact, verbatim substring of the essay this issue flags — the
    # frontend locates and highlights it by literal string match, so this
    # must be copied character-for-character from the essay, never
    # paraphrased.
    original: str
    suggestion: str
    explanation: str


class _GrammarIssueList(BaseModel):
    issues: list[GrammarIssue]


_GEMMA_PROMPT = """You are a strict grammar checker. Find ONLY grammar, \
spelling, and punctuation mistakes in the essay below — never comment on \
tone, content, structure, or word choice unless it is a grammatical error. \
If there are no mistakes, return an empty list.

For each mistake, report:
- "original": the exact mistaken text, copied verbatim from the essay \
(same capitalization, same punctuation, no added/removed whitespace)
- "suggestion": the corrected replacement text
- "explanation": one short sentence on why it's a mistake

Respond with ONLY a JSON array (no markdown fences, no other text), like:
[{{"original": "...", "suggestion": "...", "explanation": "..."}}]

ESSAY:
{text}"""

_GEMINI_DETECT_PROMPT = """You are a careful, thorough grammar checker. \
Read the essay below CAREFULLY, sentence by sentence, and find EVERY \
grammar, spelling, and punctuation mistake — including simple typos, \
wrong verb tense, subject-verb agreement, wrong word forms, and missing \
or wrong punctuation. Do not skip anything just because the essay is \
mostly clean; a single obvious typo still counts and must be reported. \
Never comment on tone, content, structure, or word choice unless it is a \
genuine grammatical error.

A smaller, less reliable model already took a first pass and flagged some \
possible mistakes below — treat these ONLY as a hint of where to look \
first, not as the full list:
- Keep a candidate only if it is a genuine grammar/spelling/punctuation \
mistake AND its "original" text is a real, verbatim substring of the \
essay (fix minor whitespace differences so it matches exactly; drop it \
outright if you can't find matching text at all — it's a hallucination).
- Then do your OWN independent read of the essay and add any mistake the \
candidate list missed. Most of the value here comes from YOUR OWN \
reading, not from the candidate list.

For every mistake you report:
- "original": the exact mistaken text, copied verbatim from the essay
- "suggestion": the corrected replacement text
- "explanation": one short sentence on why it's a mistake

If the essay genuinely has no mistakes after a careful read, return an \
empty list — but do not default to an empty list without actually \
checking every sentence yourself.

ESSAY:
{text}

FIRST-PASS CANDIDATES (from the smaller model — may be incomplete, wrong, \
or empty; do not let an empty list here stop you from checking yourself):
{candidates}"""

# json.loads on the raw Gemma response usually works outright, but Gemma
# doesn't have Gemini's response_schema/JSON-mode guarantee — this pulls the
# first top-level [...] array out of a response that wraps it in prose or a
# markdown fence, so a merely-untidy (not garbage) response still parses.
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_raw_candidates(raw_text: str) -> list[dict]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(raw_text)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _grounded_issues(issues: list[GrammarIssue], text: str) -> list[GrammarIssue]:
    """Keeps only issues whose flagged text is a real, literal substring of
    the essay — the final backstop before anything reaches the frontend,
    regardless of what either model claimed."""
    return [issue for issue in issues if issue.original and issue.original in text]


def _gemma_client() -> genai.Client:
    """`GEMINI_API_KEY`, when set, routes the Gemma call through Google AI
    Studio (`vertexai=False` forces this explicitly — otherwise the SDK
    still defers to the ambient `GOOGLE_GENAI_USE_VERTEXAI` env var this
    app's `.env` sets, ignoring the key). Falls back to the app's normal
    ambient client (Vertex/ADC) when unset — the prior behavior, which
    works for every other agent's Gemini calls but not Gemma in this
    project (see module docstring)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return genai.Client(api_key=api_key, vertexai=False)
    return genai.Client()


def check_grammar(text: str) -> list[GrammarIssue]:
    stripped = text.strip()
    if not stripped:
        return []

    gemini_timeout_config = types.GenerateContentConfig(
        http_options=types.HttpOptions(
            timeout=config.llm_call_timeout_seconds * 1000
        ),
    )
    # Deliberately much shorter than Gemini's above — see
    # config.grammar_gemma_timeout_seconds' docstring: Gemma's result here
    # is a hint, not a requirement, so a slow/hanging call shouldn't cost
    # the student most of a minute before the real (Gemini) pass even
    # starts.
    gemma_timeout_config = types.GenerateContentConfig(
        http_options=types.HttpOptions(
            timeout=config.grammar_gemma_timeout_seconds * 1000
        ),
    )

    # Held in a local variable across the whole call, deliberately — the
    # google-genai SDK's underlying httpx client can be torn down before
    # the request finishes ("Cannot send a request, as the client has been
    # closed") if the Client object itself has no live reference beyond the
    # single chained expression that constructs and calls it; found live
    # specifically on the AI-Studio-backed (`api_key=`) client.
    #
    # A Gemma failure (network error, empty response, unparseable output —
    # all real, observed outcomes for this small a model) is swallowed to
    # an empty candidate list rather than aborting the whole check: Gemini's
    # own detection pass below runs regardless, exactly the fix for the
    # "Gemma found nothing so nothing was ever reported" bug described in
    # this module's docstring.
    candidates: list[dict] = []
    try:
        gemma_client = _gemma_client()
        gemma_response = gemma_client.models.generate_content(
            model=config.grammar_model,
            contents=_GEMMA_PROMPT.format(text=stripped),
            config=gemma_timeout_config,
        )
        candidates = _parse_raw_candidates(gemma_response.text or "")
    except Exception:
        logger.exception("Gemma grammar-detection call failed; continuing with Gemini alone")

    gemini_client = genai.Client()
    try:
        gemini_response = gemini_client.models.generate_content(
            model=config.worker_model,
            contents=_GEMINI_DETECT_PROMPT.format(
                text=stripped, candidates=json.dumps(candidates)
            ),
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=_GrammarIssueList,
                http_options=gemini_timeout_config.http_options,
            ),
        )
    except Exception:
        logger.exception("Gemini grammar-detection call failed")
        return []

    parsed = gemini_response.parsed
    if not isinstance(parsed, _GrammarIssueList):
        return []
    return _grounded_issues(parsed.issues, stripped)
