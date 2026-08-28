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

Note: school brand colors and logo are NOT your job — branding_research_
agent (below) covers those on its own, much faster, narrower pass so the
Colleges table doesn't have to wait on everything else here first. Don't
spend any effort on them. (Deadlines above ARE still your job too, even
though deadlines_research_agent also researches them separately and faster
for the table's own summary field — your slower, broader pass is what
turns each deadline into its own trackable Requirement/Task, which needs
the fuller context only this pass gathers.)

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
    source_count = len(callback_context.state.get("sources") or {})
    log_agent_run_complete(
        callback_context, f"Found {source_count} source(s) via web search."
    )


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


_BRANDING_RESEARCH_INSTRUCTION = f"""You are doing a VERY FAST, single-purpose
research pass for Collegentic — find ONLY a college's official brand color(s)
and logo, nothing else. This is deliberately the very first thing found for
a newly requested college (a student sees its row tinted with the real
school color before anything else lands), so speed matters more here than
anywhere else in the pipeline: one or two sharp, targeted queries, not a
sweep.

WHICH COLLEGES TO RESEARCH:
NEW_COLLEGES (from pipeline state, may be empty): {{new_college_names?}}
If NEW_COLLEGES lists one or more names, research exactly those and only
those. If it is empty, parse the list of college names directly from the
user's message instead. If there is nothing to research either way, say so
and stop — do not invent colleges to research.

FOR EACH COLLEGE, research and report ONLY:
- School brand colors: the official primary (and secondary, if stated) color
  as a hex code — search e.g. "site:brand.<college>.edu color" or "<college>
  official brand color hex".
- Official logo: a downstream deterministic step (not you) already looks up
  each school's logo, so don't spend effort on this unless you happen to
  notice one while searching for the above — as an absolute last resort,
  search "site:commons.wikimedia.org <college> seal" and report ONLY the
  exact Wikimedia Commons file name of the school's official seal (the part
  after "File:" in the page title), never a constructed URL.

Do NOT research deadlines, essays, recommendations, testing policy,
portfolio, interview, or major-specific requirements here — separate passes
cover those.

CRITICAL — never invent information: if a color is not clearly stated, or
you cannot find it after searching, do NOT guess — just omit it.

OUTPUT FORMAT — one level-2 markdown header per college (`## <College Name>`,
spelled exactly as given) followed by a bulleted list of whatever branding
you found under that header. This exact structure is required — a
downstream agent splits your output by these headers.
"""


branding_research_agent = LlmAgent(
    model=config.worker_model,
    name="branding_research_agent",
    description=(
        "The FIRST thing researched for a newly requested college — its brand "
        "color(s) and logo hint, and nothing else, so the Colleges table shows "
        "real color/logo before anything else lands."
    ),
    instruction=_BRANDING_RESEARCH_INSTRUCTION,
    tools=[google_search],
    output_key="branding_research_findings",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=log_agent_run_complete,
)


_DEADLINES_RESEARCH_INSTRUCTION = f"""You are doing a FAST, single-purpose
research pass for Collegentic — find ONLY a college's application deadlines,
nothing else. A small number of sharp, targeted queries, not a sweep.

WHICH COLLEGES TO RESEARCH:
NEW_COLLEGES (from pipeline state, may be empty): {{new_college_names?}}
If NEW_COLLEGES lists one or more names, research exactly those and only
those. If it is empty, parse the list of college names directly from the
user's message instead. If there is nothing to research either way, say so
and stop — do not invent colleges to research.

FOR EACH COLLEGE, research and report ONLY:
- Application deadlines: Early Action, Early Decision, Regular Decision, and
  the financial aid priority date (CSS Profile/FAFSA), with exact dates.
  Prefer queries that target the college's own domain, e.g.
  "site:admissions.<college>.edu application deadlines".

Do NOT research brand colors, logo, essays, recommendations, testing
policy, portfolio, interview, or major-specific requirements here —
separate passes cover those.

CRITICAL — never invent information: if a deadline is not clearly stated,
or you cannot find it after searching, do NOT guess. Write
"UNCERTAIN: <what's missing>" for that item instead.

OUTPUT FORMAT — one level-2 markdown header per college (`## <College Name>`,
spelled exactly as given) followed by a bulleted list of deadlines under
that header. This exact structure is required — a downstream agent splits
your output by these headers.

Today's date is {datetime.date.today().isoformat()} — use it to judge
whether a deadline you find is for the current application cycle or a past
one, and prefer the most recent cycle's information.
"""


deadlines_research_agent = LlmAgent(
    model=config.worker_model,
    name="deadlines_research_agent",
    description=(
        "Researches a college's application deadlines only, right after "
        "branding_research_agent — its own fast, single-purpose pass."
    ),
    instruction=_DEADLINES_RESEARCH_INSTRUCTION,
    tools=[google_search],
    output_key="deadlines_research_findings",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=log_agent_run_complete,
)
