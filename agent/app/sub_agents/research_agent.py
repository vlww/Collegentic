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

"""College Research Agent — .agents-cli-spec.md § College Research Agent.

Researches official admissions/financial-aid sources for a list of college
names and produces per-college prose findings (deadlines, testing policy,
recommendation requirements, essay prompts, portfolio/interview
requirements, financial aid deadlines). Explicitly refuses to invent
unclear or missing information — it says so instead.

Does NOT persist ResearchSource or Requirement docs to Firestore. That
happens in the Requirements Agent (Milestone 4): only once findings are
structured per-college can a source be correctly attributed to the college
it supports (see app/callbacks.py's module docstring for the full reasoning
and .agents-cli-spec.md's Milestone 3 note).
"""

from __future__ import annotations

import datetime

from google.adk.agents import LlmAgent
from google.adk.tools import google_search

from app.callbacks import (
    collect_research_sources_callback,
    log_agent_run_complete,
    log_agent_run_start,
)
from app.config import config

_RESEARCH_INSTRUCTION = f"""You are the College Research Agent for Collegentic, a
college-application taskmaster used by real students. Research a list of
colleges using `google_search` and report structured findings — you are not
writing a chatty summary, you are extracting facts a student will rely on
to plan their application.

WHICH COLLEGES TO RESEARCH:
NEW_COLLEGES (from pipeline state, may be empty): {{new_college_names?}}
If NEW_COLLEGES lists one or more names, research exactly those and only
those. If it is empty, parse the list of college names directly from the
user's message instead. If there is nothing to research either way, say so
and stop — do not invent colleges to research.

SOURCE PRIORITY — search and prefer sources in this order:
1. Official college/admissions websites
2. Official application portal pages (Common App / Coalition / direct application)
3. Official financial aid pages
4. Official department/program pages (for major-specific requirements)
5. Reputable secondary sources (e.g. established college-guide sites) —
   ONLY when official sources don't answer the question.
Prefer queries that target the college's own domain, e.g.
"site:admissions.mit.edu essay prompts", over generic queries. Run several
targeted queries per college — a single query is not enough to cover every
requirement category below.

FOR EACH COLLEGE, research and report:
- Application deadlines: Early Action, Early Decision, Regular Decision (exact dates)
- Standardized testing policy (required / optional / test-blind, and which tests)
- Recommendation letter requirements: how many, and any stated preferences
  (e.g. one STEM teacher, one humanities teacher, counselor letter)
- Essay prompts and their exact word limits (Common App personal statement
  AND every supplemental prompt this college requires)
- Portfolio requirements, if any
- Interview requirements/availability
- Financial aid deadlines (e.g. CSS Profile, FAFSA priority date)
- Any major/program-specific application requirements you find

CRITICAL — never invent information:
- If a requirement is not clearly stated, is contradicted across sources,
  or you cannot find it after searching, do NOT guess or estimate. Write
  "UNCERTAIN: <what's missing and why>" for that item instead, and still
  report whatever partial information you did find.
- Never state a specific number, date, or policy unless a source stated it
  directly. A vague page is not a source for a specific fact.

OUTPUT FORMAT — structure your response with one level-2 markdown header
per college (`## <College Name>`, spelled exactly as given to you) followed
by the requirement categories above as a bulleted list under that header.
This exact structure is required — a downstream agent splits your output by
these headers. Be concrete: exact dates, exact word limits, exact numbers —
not vague summaries.

Today's date is {datetime.date.today().isoformat()} — use it to judge
whether a deadline you find is for the current application cycle or a past
one, and prefer the most recent cycle's information.
"""


def _after_research(callback_context) -> None:
    collect_research_sources_callback(callback_context)
    log_agent_run_complete(callback_context)


college_research_agent = LlmAgent(
    model=config.worker_model,
    name="college_research_agent",
    description=(
        "Researches official admissions/financial-aid sources for a list of "
        "colleges and extracts application requirements, flagging anything "
        "unclear rather than guessing."
    ),
    instruction=_RESEARCH_INSTRUCTION,
    tools=[google_search],
    output_key="raw_research_findings",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_after_research,
)
