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

import asyncio
import datetime
import functools
import html
import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import AsyncGenerator
from typing import Literal
from urllib.parse import quote, urlencode, urlparse

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


_LOGO_USER_AGENT = "Collegentic/1.0 (college-application-assistant; demo project)"
_LOGO_FETCH_RETRIES = 4
_LOGO_FETCH_RETRY_DELAY_SECONDS = 1.5


def _open_url_with_retries(
    request: urllib.request.Request,
) -> http.client.HTTPResponse | None:
    """Retries a flaky network call with a short linear backoff before
    giving up — Wikimedia's public APIs rate-limit bursts of requests
    (found live: looking up 6 colleges' logos back-to-back started
    intermittently failing partway through the batch), and a transient
    429/timeout shouldn't be treated the same as "this logo doesn't
    exist" — this is the "keeps looking until it finds a working one"
    that the sequential per-college checks below rely on.
    """
    last_exc: Exception | None = None
    for attempt in range(_LOGO_FETCH_RETRIES):
        try:
            return urllib.request.urlopen(request, timeout=5)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < _LOGO_FETCH_RETRIES - 1:
                time.sleep(_LOGO_FETCH_RETRY_DELAY_SECONDS * (attempt + 1))
    logger.debug("Logo lookup retries exhausted for %s: %s", request.full_url, last_exc)
    return None


def _url_is_a_loadable_image(url: str) -> bool:
    """Confirms a candidate logo URL actually resolves to real image bytes
    (not a 404, a redirect to a login page, an HTML error page, or a
    since-deleted file) before it's ever stored and shown to a student.
    Every logo candidate below is required to pass this before being
    accepted."""
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": _LOGO_USER_AGENT}
    )
    response = _open_url_with_retries(request)
    if response is None:
        return False
    with response:
        content_type = response.headers.get("Content-Type", "")
        return response.status == 200 and content_type.startswith("image/")


_INSTITUTION_DESCRIPTION_HINTS = (
    "university",
    "college",
    "institute",
    "academy",
    "polytechnic",
    "conservatory",
)


def _looks_like_a_school(description: str | None) -> bool:
    """Wikipedia's short `description` field (e.g. "Private research
    university in Cambridge, Massachusetts") is a cheap, reliable sanity
    check that a resolved article is actually the school and not some
    unrelated same-named topic."""
    return bool(description) and any(
        hint in description.lower() for hint in _INSTITUTION_DESCRIPTION_HINTS
    )


def _wikipedia_summary(title: str) -> dict | None:
    encoded = quote(title.replace(" ", "_"))
    request = urllib.request.Request(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
        headers={"User-Agent": _LOGO_USER_AGENT},
    )
    response = _open_url_with_retries(request)
    if response is None:
        return None
    try:
        with response:
            return json.load(response)
    except json.JSONDecodeError:
        return None


def _search_wikipedia_school_title(college_name: str) -> str | None:
    """Finds the actual matching institution article for an ambiguous or
    shortened name, rather than trusting it as an exact title — found live:
    a bare "Rice" (a student might type just that, or an upstream agent
    might shorten "Rice University" to it) resolves as a *direct* title
    lookup to the cereal grain, whose infobox photo is literally a bowl of
    rice. Checks each candidate's own short description and returns the
    first that actually reads as a school, rather than just the top hit."""
    query = urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"{college_name} university",
            "srlimit": 5,
            "format": "json",
        }
    )
    request = urllib.request.Request(
        f"https://en.wikipedia.org/w/api.php?{query}",
        headers={"User-Agent": _LOGO_USER_AGENT},
    )
    response = _open_url_with_retries(request)
    if response is None:
        return None
    try:
        with response:
            data = json.load(response)
        results = data.get("query", {}).get("search", [])
    except (json.JSONDecodeError, KeyError):
        return None
    for result in results:
        title = result.get("title")
        if title and _looks_like_a_school((_wikipedia_summary(title) or {}).get("description")):
            return title
    return None


def _resolve_school_wikipedia_page(college_name: str) -> dict | None:
    """Resolves `college_name` to the Wikipedia summary of the actual
    matching school — a direct title lookup first (cheap, usually right for
    a full official name), falling back to search-based disambiguation only
    when that lands on the wrong article or nothing at all."""
    data = _wikipedia_summary(college_name)
    if (
        data
        and data.get("type") == "standard"
        and _looks_like_a_school(data.get("description"))
    ):
        return data
    search_title = _search_wikipedia_school_title(college_name)
    if not search_title:
        return None
    data = _wikipedia_summary(search_title)
    if (
        data
        and data.get("type") == "standard"
        and _looks_like_a_school(data.get("description"))
    ):
        return data
    return None


def _logo_from_page(page: dict) -> str | None:
    """The Wikipedia article's own infobox image — specifically the FIRST
    one, exactly as rendered on the page. Some university infoboxes carry a
    second, separate `logo=` image alongside the primary `image=` one (e.g.
    Harvard: `image` is its coat of arms, `logo` is a separately-captioned
    "Logotype of Harvard University" wordmark) — confirmed live from the
    rendered page that `thumbnail.source` here always tracks `image=`, the
    true first one, never the secondary `logo=` field, which is what makes
    trusting it directly correct without needing to also check what the
    filename says (a seal, a shield, a coat of arms — whatever a given
    school's first image happens to be captioned, take it)."""
    thumbnail = (page.get("thumbnail") or {}).get("source")
    if not thumbnail:
        return None
    thumbnail = thumbnail.split("?", 1)[0]
    return thumbnail if _url_is_a_loadable_image(thumbnail) else None


_LOGOBRANDS_URL = "https://logobrands.com/pages/college"
_LOGOBRANDS_USER_AGENT = _LOGO_USER_AGENT
# Manual aliases for schools whose common name shares no word with their
# logobrands.com listing (which keys mostly off the short public
# nickname/mascot, e.g. "byu byu cougars" never spells out "Brigham Young")
# — every other school matches by ordinary word overlap, see
# _match_logobrands_entry.
_LOGOBRANDS_NAME_ALIASES: dict[str, str] = {
    "brigham young university": "byu",
    "university of southern california": "usc",
    "university of mississippi": "ole miss",
}
# Schools that must never match logobrands.com at all, regardless of score —
# not aliases (there is no correct entry to alias to; these schools simply
# aren't SEC/ACC/Big Ten/Big 12 members, e.g. WashU is D3). Found live:
# "Washington University in St. Louis" scored a nonzero Jaccard match
# against the "washington washington huskies" (University of Washington)
# entry purely because they coincidentally share the single word
# "washington" — the only entry with ANY overlap wins even at a low score,
# since _match_logobrands_entry has no absolute floor. Raising a global
# score threshold doesn't cleanly fix this either: "George Washington
# University" would tie the exact same (legitimate) score "University of
# Texas at Austin" gets for its real match — both are single-shared-word,
# one-extra-unmatched-word cases, structurally identical by word overlap
# alone. Hard-excluding the specific known collision is the safe fix; a
# correctly-excluded school still gets its real logo from the Wikipedia
# fallback in _fetch_college_logo.
_LOGOBRANDS_NEVER_MATCH = {
    "washington university in st louis",
}


def _known_college_key(college_name: str) -> str:
    return re.sub(r"[.,]", "", college_name.lower()).strip()


# School colors that are pinned rather than trusted to whatever
# college_research_agent's live google_search-grounded pass happens to
# report. Found live: Washington University in St. Louis officially
# recognizes BOTH red and green (its own Wikipedia infobox lists "Red and
# green", and its own logo mark — brand.wustl.edu's CSS — literally fills
# one path #2c5234 green and another #ba0c2f red), so which one a live LLM
# call reports as "primary" isn't a hallucination to prompt-tune away, it's
# genuine source ambiguity that can legitimately go either way run to run.
# Green is the color actually associated with WashU (spirit wear, athletics,
# the wordmark) — pin it rather than leave it to chance. Both hex values are
# taken directly from brand.wustl.edu's own official logo CSS, not guessed.
_KNOWN_SCHOOL_COLORS: dict[str, dict[str, str]] = {
    "washington university in st louis": {
        "primary": "#2C5234",
        "secondary": "#BA0C2F",
    },
}


@functools.lru_cache(maxsize=1)
def _fetch_logobrands_fbs_entries() -> tuple[tuple[str, str], ...]:
    """(data-name, image URL) for every school listed on logobrands.com's
    SEC/ACC/Big 10/Big 12 sections — deliberately excludes its "Partners &
    Independents" section, which includes non-FBS-power-conference schools
    like Notre Dame and UConn. Cached for the process lifetime: this is one
    live scrape of a third-party retail page's current markup, not a stable
    API, so it's fetched once and reused rather than re-fetched per college
    within a batch (see the caller in _fetch_college_logo)."""
    request = urllib.request.Request(
        _LOGOBRANDS_URL, headers={"User-Agent": _LOGOBRANDS_USER_AGENT}
    )
    response = _open_url_with_retries(request)
    if response is None:
        return ()
    try:
        with response:
            page_html = response.read().decode("utf-8", errors="replace")
    except OSError:
        return ()

    section_re = re.compile(
        r'<section[^>]*class="[^"]*lb-ts-conf[^"]*"[^>]*>(.*?)</section>', re.S
    )
    title_re = re.compile(r"<h3[^>]*>([^<]*)</h3>")
    team_re = re.compile(
        r'data-name="([^"]+)"[^>]*>\s*<span class="lb-ts-crest">\s*<img src="([^"]+)"',
        re.S,
    )
    entries: list[tuple[str, str]] = []
    for section_html in section_re.findall(page_html):
        title_match = title_re.search(section_html)
        title = html.unescape(title_match.group(1)).strip() if title_match else ""
        if title == "Partners & Independents":
            continue
        for data_name, src in team_re.findall(section_html):
            src = html.unescape(src).split("?", 1)[0]
            if src.startswith("//"):
                src = f"https:{src}"
            entries.append((html.unescape(data_name).lower(), src))
    return tuple(entries)


_LOGOBRANDS_STOPWORDS = {"university", "college", "of", "the", "at"}


def _logobrands_words(text: str) -> set[str]:
    """Significant words for matching — keeps "&" glued onto its neighbors
    (so "A&M" survives as one token, not the near-meaningless "a" and "m")
    and deliberately does NOT drop "state": several of these conferences
    have both a plain school and its "State" counterpart (Iowa/Iowa State,
    Kansas/Kansas State, Michigan/Michigan State, Oklahoma/Oklahoma State,
    Washington/Washington State all appear here) — treating "state" as
    noise would make those indistinguishable."""
    return {w for w in re.findall(r"[a-z&']+", text.lower()) if w not in _LOGOBRANDS_STOPWORDS}


def _match_logobrands_entry(college_name: str, entries: tuple[tuple[str, str], ...]) -> str | None:
    """Matches `college_name` against logobrands.com's (data-name, url)
    entries by word overlap, ranked by Jaccard similarity (overlap size
    over union size) rather than "first entry with any shared word" —
    needed because data-name is itself two names smashed together (a short
    slug plus a fuller name, e.g. "texas university of texas longhorns"),
    and several schools share a word with a DIFFERENT school's entry (e.g.
    "Texas" alone, "Texas A&M", and "Texas Tech" all share "texas") without
    being the same school. Jaccard correctly prefers the entry with the
    fewest *extra*, unmatched words too — "University of Texas at Austin"
    scores higher against the bare "texas" entry than against "texas a&m"
    or "texas tech", each of which has an extra word the query doesn't.
    Applies `_LOGOBRANDS_NAME_ALIASES` first for the handful of schools
    where word overlap alone can't work at all (BYU, USC, Ole Miss), and
    refuses to match at all for `_LOGOBRANDS_NEVER_MATCH` (see its
    docstring)."""
    if _known_college_key(college_name) in _LOGOBRANDS_NEVER_MATCH:
        return None
    normalized = college_name.lower()
    for full, alias in _LOGOBRANDS_NAME_ALIASES.items():
        if full in normalized:
            normalized = alias
            break
    words = _logobrands_words(normalized)
    if not words:
        return None

    best_score = 0.0
    best_url: str | None = None
    for data_name, url in entries:
        entry_words = _logobrands_words(data_name)
        overlap = words & entry_words
        if not overlap:
            continue
        score = len(overlap) / len(words | entry_words)
        if score > best_score:
            best_score = score
            best_url = url
    return best_url


def _fetch_college_logo(college_name: str) -> str | None:
    """Primary logo source, tried before anything the LLM reports — fully
    deterministic and keyed off just the college's name, no search-and-
    construct step for an LLM to get wrong. Two tiers: (1) for an FBS
    school in the SEC, ACC, Big Ten, or Big 12, the clean graphic mark
    logobrands.com lists for it (see _fetch_logobrands_fbs_entries) — this
    is what a student actually pictures for a major athletics program, and
    matches what that site itself shows on its own college merchandise
    pages; (2) otherwise (or if no match), the academic institution's own
    Wikipedia page — its first infobox image, the image actually shown at
    the top of that page (see _logo_from_page). Nothing, rather than a
    wrong or broken image, if neither pans out. Wikipedia is also often the
    ONLY place a non-power-conference school's real logo is reachable at
    all: several of these are copyrighted, so Wikipedia hosts them under a
    fair-use rationale rather than on the fully-open Wikimedia Commons — a
    demo project display, not redistribution, is squarely inside typical
    fair-use educational rationale for a low-res logo like this.
    """
    try:
        entries = _fetch_logobrands_fbs_entries()
        logobrands_url = _match_logobrands_entry(college_name, entries) if entries else None
        if logobrands_url and _url_is_a_loadable_image(logobrands_url):
            return logobrands_url
    except Exception:
        logger.warning(
            "logobrands.com lookup failed for %r, falling back to Wikipedia",
            college_name, exc_info=True,
        )

    page = _resolve_school_wikipedia_page(college_name)
    return _logo_from_page(page) if page else None


def _resolve_commons_logo_url(filename: str) -> str | None:
    """Fallback logo source, for when `_fetch_college_logo` finds
    nothing: resolves a Wikimedia Commons file name (as reported by
    college_research_agent) to a real, directly-hotlinkable 250px thumbnail
    PNG URL via Commons' own imageinfo API — deterministic and correct
    whenever the file exists, unlike asking the LLM to construct the URL's
    hash-path itself: that asked a single google_search-grounded turn to
    search, open the file's description page, read off its hash-path
    folders, and assemble a specific templated URL — found live, it got
    this right approximately never (0/4 real colleges researched in
    testing). Shrinking the LLM's job to "report the filename you found"
    made that part reliable; this function does the part that wasn't.
    """
    title = filename if filename.startswith("File:") else f"File:{filename}"
    query = urlencode(
        {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 250,
            "format": "json",
        }
    )
    request = urllib.request.Request(
        f"https://commons.wikimedia.org/w/api.php?{query}",
        headers={"User-Agent": _LOGO_USER_AGENT},
    )
    response = _open_url_with_retries(request)
    if response is not None:
        try:
            with response:
                data = json.load(response)
            for page in data.get("query", {}).get("pages", {}).values():
                imageinfo = page.get("imageinfo")
                if imageinfo and imageinfo[0].get("thumburl"):
                    # Drop Wikimedia's utm_* tracking query params —
                    # irrelevant noise on a URL we're storing and
                    # hotlinking, not visiting.
                    thumb_url = imageinfo[0]["thumburl"].split("?", 1)[0]
                    if _url_is_a_loadable_image(thumb_url):
                        return thumb_url
        except (json.JSONDecodeError, KeyError):
            pass
    logger.warning("Could not resolve a working logo for Commons file %r", filename)
    return None


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
{raw_research_findings?}

If RAW RESEARCH FINDINGS is empty, grade "fail" with a comment saying
research hasn't produced findings yet, rather than guessing at what's
missing — do NOT invent follow-up queries against nonexistent findings.

Grade "fail" ONLY if: a college is missing deadlines, testing policy, OR
essay prompts entirely (the categories that actually drive the table and
planned tasks) with nothing at all reported for them, not even
"UNCERTAIN:"; or there are 3 or more "UNCERTAIN:" markers that a more
targeted search could likely resolve. Otherwise grade "pass" — bias toward
"pass": a few genuinely UNCERTAIN items, or a gap in a less-critical
category (portfolio, interview, financial aid) is expected and fine. This
is being watched live, so only ask for a follow-up round when it would fix
something that actually matters, not to chase completeness for its own
sake.

If "fail", write 3-4 specific follow-up search queries targeting exactly the
missing/unclear items (e.g. "Rice University supplemental essay prompts
2026-2027" rather than a generic re-search) — few and sharp, not exhaustive.

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
    on a data-driven condition rather than only on max_iterations.

    Also escalates if `raw_research_findings` isn't visible in state at all
    — found live: a LoopAgent iteration occasionally can't see a value the
    step just before it (or the previous iteration's own
    findings_followup_search) wrote, which used to hard-crash the whole
    pipeline on the required `{raw_research_findings}` template variable in
    findings_evaluator's instruction (now `{raw_research_findings?}`, so it
    renders empty and grades "fail" instead of raising). Running
    findings_followup_search against nothing would just overwrite whatever
    good findings DO exist in the outer session with an empty/garbage
    merge — stopping the loop here instead means the pipeline moves on with
    the last known-good findings rather than corrupting them.
    """

    def __init__(self, name: str = "requirements_escalation_checker"):
        super().__init__(name=name)

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        evaluation = ctx.session.state.get("findings_evaluation")
        findings = ctx.session.state.get("raw_research_findings")
        if not findings or (evaluation and evaluation.get("grade") == "pass"):
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
{raw_research_findings?}

EVALUATOR FEEDBACK:
{findings_evaluation?}

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
        "text, or 'Regular Decision deadline: January 5'. If a word count is "
        "involved, state ONLY the actual limit (e.g. '650 words maximum') — drop "
        "any 'X-Y words recommended' range some schools also publish, that's "
        "noise on top of the real limit, not part of it."
    )
    required: bool = True
    deadline_iso: str | None = Field(
        default=None, description="ISO 8601 date (YYYY-MM-DD) if found, else null."
    )
    deadline_kind: Literal["EA", "ED", "RD", "financial_aid"] | None = Field(
        default=None,
        description="Set ONLY when type='deadline': which deadline this is — Early "
        "Action, Early Decision, Regular Decision, or a financial aid deadline "
        "(CSS Profile/FAFSA priority date). Null for every other requirement type, "
        "and null for a deadline type you can't confidently classify into one of these.",
    )
    recommendation_count: int | None = Field(
        default=None,
        description="Set ONLY when type='recommendation': the TOTAL number of "
        "individual letters this requirement covers, resolved to one whole number — "
        "e.g. '2 teacher recommendations' is 2; '1 counselor + 2 teacher letters' "
        "is 3 (sum across recommender types). Don't just count how many times a "
        "numeral appears — a school restating the same total in different words "
        "('2 teacher recommendations, one from a STEM class, one from humanities') "
        "is still 2, not 2+1+1. Default to 1 if the findings don't state a number. "
        "Null for every other requirement type.",
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


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ExtractedBranding(BaseModel):
    college_name: str = Field(
        description="Must exactly match a college name/header from the findings."
    )
    primary_color_hex: str | None = Field(
        default=None,
        description="School's official primary brand color as #RRGGBB, only if "
        "the findings state one confidently; else null.",
    )
    secondary_color_hex: str | None = Field(
        default=None, description="Same as primary_color_hex, for a secondary color."
    )
    logo_commons_filename: str | None = Field(
        default=None,
        description="Wikimedia Commons file name for a logo/seal image (e.g. "
        "'Harvard_University_shield.svg'), exactly as reported in the "
        "findings — NOT a URL, just the filename. Only if the findings "
        "name a real file they found; else null.",
    )


class RequirementsExtraction(BaseModel):
    requirements: list[ExtractedRequirement]
    branding: list[ExtractedBranding] = Field(
        default_factory=list,
        description="One entry per college whose findings mentioned a brand "
        "color or logo filename. Omit a college entirely rather than guessing.",
    )


_REQUIREMENTS_INSTRUCTION = f"""You are the Requirements Agent. Convert the research
findings below into a structured list of application requirements — one
entry per DISCRETE requirement per college. Do not summarize: each essay
prompt is its own requirement, each deadline is its own requirement,
testing policy is its own requirement, each recommendation-letter rule is
its own requirement, and so on.

RAW RESEARCH FINDINGS:
{{raw_research_findings}}

AVAILABLE SOURCES (short_id -> title/url/domain/claims):
{{sources}}

Today's date is {datetime.date.today().isoformat()}.

For every requirement:
- college_name: must exactly match a college name/header from the findings.
- confidence: "high" only if a source directly and unambiguously stated
  this; "medium" if inferred/implied; "low" if the findings marked it
  UNCERTAIN or you are extrapolating.
- needs_verification: true ONLY if the findings explicitly marked this
  UNCERTAIN, or two sources directly and specifically contradict each other
  on this exact fact. Do not set it just because a fact feels ordinary,
  slightly dated, or unremarkable — an unremarkable fact stated plainly by
  a source is NOT uncertain. Most requirements should be false here.
- source_short_ids: every src-N id from AVAILABLE SOURCES that's plausibly
  about the same college and topic as this requirement, even if its
  supported_claims text doesn't quote this exact detail word-for-word — a
  source about "MIT admissions deadlines" backs a specific MIT deadline
  requirement even if the claims text paraphrased it. Use [] only when
  truly nothing in AVAILABLE SOURCES relates to this requirement at all,
  not merely because the wording doesn't match closely.
- deadline_kind: for type="deadline" items only, classify which deadline it
  is (EA/ED/RD/financial_aid) whenever you can tell — this is what powers
  the dashboard's per-college deadline columns. Leave null if ambiguous
  rather than guessing.
- recommendation_count: for type="recommendation" items only, resolve the
  TOTAL number of individual letters this requirement covers to one whole
  number — this is what powers the Readiness score's recommendations
  category, so guessing high or low here directly misstates it. Default
  to 1 if the findings don't state a count.
- deadline_iso: college deadline pages very often state a deadline as a
  bare month/day ("November 1") with no year, implicitly meaning the
  current or upcoming application cycle. When that's the only reason a
  year is missing, INFER the correct year from today's date (use this
  cycle's year if that month/day hasn't passed yet, otherwise next year's)
  and fill in the full ISO date — this is resolving an obvious implicit
  detail, not inventing a fact, and leaving deadline_iso null in this case
  makes the requirement useless for the dashboard. Only leave it null if
  the month/day itself is missing, unclear, or genuinely contradictory.

Never invent a requirement, deadline, or number that wasn't in the
findings. If the findings marked something UNCERTAIN, still extract it as a
requirement — confidence="low", needs_verification=true, description taken
from what the findings actually said (including the uncertainty itself).

BRANDING: separately, if a college's findings state a brand color (hex) or a
Wikimedia Commons logo filename, add one entry to `branding` for it. Copy
the hex code and filename exactly as given — never normalize, guess, or
invent one that wasn't explicitly in the findings. Skip a college entirely
(don't add an all-null entry) if the findings say nothing about its colors
or logo.

Respond with a single raw JSON object matching the RequirementsExtraction schema."""


async def _persist_requirements_and_sources(callback_context) -> None:
    """Writes Requirement + (deduped, per-college) ResearchSource docs, plus
    College.schoolColors/logoUrl/deadlines. Runs as an after_agent_callback
    since output_schema agents can't also call tools mid-turn — this is
    where the structured output actually lands in Firestore, same division
    of labor as citation_replacement_callback in deep-search.

    async, not a plain def, and every pacing pause below is `await
    asyncio.sleep(...)` rather than `time.sleep(...)` — found live: ADK's
    BaseAgent calls an after_agent_callback directly on the server's single
    asyncio event loop (only awaiting it afterward if it returns an
    awaitable), and this whole backend runs as one uvicorn process with no
    worker threads. A plain `time.sleep()` here doesn't just pause THIS
    request — it freezes that one shared event loop for every other
    in-flight request, including the Colleges page's concurrent polling GET
    (Colleges.tsx). Every "paced" write below WAS landing in Firestore one
    at a time as designed, but the frontend's poll couldn't get through to
    observe any of the intermediate states until this entire callback
    (several colleges' worth of writes and sleeps) finally finished, so the
    whole row appeared to jump at once. `await asyncio.sleep(...)` actually
    yields the event loop, letting a queued poll request run during the
    pause; `_fetch_college_logo`'s real (and sometimes multi-second)
    network call is similarly wrapped in `asyncio.to_thread` below so it
    can't cause the same freeze.

    Deliberately staged, not one flat pass, for two reasons: (1) each stage
    below is wrapped so one college's bad data or a transient Firestore/
    network error can't take the others down with it — found live, an
    unhandled exception anywhere in here used to fail the entire Requirements
    Agent run, discarding every college's already-extracted data in the same
    batch and aborting every pipeline stage after it (conflict detection,
    task planning, readiness); (2) school color (Stage 1), logo (Stage 2),
    and deadlines (Stage 4) are each their own pass, written per-college with
    a deliberate pause between colleges, so a student watching the Colleges
    table (which polls Firestore while research is running — see
    Colleges.tsx) sees each college's row color, logo, and dates land
    individually as they're found — genuinely as separate discoveries, not
    bundled into one write, since color is already known the instant this
    callback runs (extracted right alongside the requirements themselves)
    while the logo needs its own slower deterministic lookup (network calls
    to logobrands.com/Wikipedia, see _fetch_college_logo) — rather than the
    whole batch jumping from placeholder to fully populated in one silent
    poll tick. Detailed Requirement docs (essay prompts, recommendation
    counts, etc.) are the least visually interesting of these and are saved
    last, in one batch, with no pacing.
    """
    user_id = callback_context.user_id
    extraction = callback_context.state.get("extracted_requirements") or {}
    extracted = extraction.get("requirements", [])
    name_to_id: dict[str, str] = callback_context.state.get("college_name_to_id", {})
    new_college_names: list[str] = callback_context.state.get("new_college_names", [])
    sources_pool: dict[str, dict] = callback_context.state.get("sources", {})

    if not extracted:
        log_agent_run_complete(callback_context, "No requirements extracted.")
        return

    branding_by_name: dict[str, dict] = {}
    for entry in extraction.get("branding", []):
        name = entry.get("college_name")
        if name:
            branding_by_name[name] = entry

    # This callback always covers exactly one college (see
    # PerCollegeResearchAndExtraction in orchestrator_agent.py, which scopes
    # new_college_names down to a single name before invoking
    # requirements_pipeline) — college_id is the one loading-spinner target
    # every stage below advances through, in order: "logo" (already set by
    # start_college_research before this run even started) -> "ea" -> "ed"
    # -> "rd" -> "financialAid" -> "requirements".
    college_name = new_college_names[0] if new_college_names else None
    college_id = name_to_id.get(college_name) if college_name else None

    # --- Stage 1: school color — already fully known the moment we're
    # here (it came back in the same structured extraction as the
    # requirements, no lookup needed), so it's applied silently while the
    # loading spinner on the logo cell (Stage 2, the actually slow part) is
    # still showing, rather than getting a spinner cell of its own. -------
    if college_id:
        entry = branding_by_name.get(college_name, {})
        fields: dict[str, str] = {}
        primary = entry.get("primary_color_hex")
        if primary and _HEX_COLOR_RE.match(primary):
            fields["primary"] = primary
        secondary = entry.get("secondary_color_hex")
        if secondary and _HEX_COLOR_RE.match(secondary):
            fields["secondary"] = secondary
        # Pinned override wins over whatever this run's research found —
        # see _KNOWN_SCHOOL_COLORS's docstring. Applied even if the LLM
        # reported no color at all for this college.
        fields.update(_KNOWN_SCHOOL_COLORS.get(_known_college_key(college_name), {}))
        if fields:
            try:
                ft.update_college_branding(user_id, college_id, fields)
            except Exception:
                logger.warning(
                    "Failed to save school colors for %r, continuing", college_name,
                    exc_info=True,
                )

        # --- Stage 2: logo — the genuinely slow part (a real network
        # lookup, logobrands.com and/or Wikipedia, with its own retry/
        # backoff), which is exactly why its loading spinner (research_
        # stage == "logo", set before this whole college's research began)
        # has been showing this whole time rather than only appearing now. -
        entry = branding_by_name.get(college_name, {})
        try:
            # asyncio.to_thread: _fetch_college_logo does real, sometimes
            # multi-second, synchronous network I/O (urllib) — run off the
            # event loop so it can't freeze other requests either, same
            # reasoning as this callback's own async'ified pacing pauses.
            logo_url = await asyncio.to_thread(_fetch_college_logo, college_name)
            if not logo_url:
                # Absolute last resort, for a college whose Wikipedia
                # article itself couldn't be resolved: college_research_
                # agent's own google_search-grounded Commons lookup for a
                # seal filename.
                logo_filename = entry.get("logo_commons_filename")
                if logo_filename:
                    logo_url = await asyncio.to_thread(
                        _resolve_commons_logo_url, logo_filename
                    )
        except Exception:
            logger.warning(
                "Logo lookup failed for %r, continuing without one", college_name,
                exc_info=True,
            )
            logo_url = None
        if logo_url:
            try:
                ft.update_college_branding(user_id, college_id, {"logoUrl": logo_url})
            except Exception:
                logger.warning(
                    "Failed to save logo for %r, continuing", college_name,
                    exc_info=True,
                )
        # Advance the spinner to the first deadline field regardless of
        # whether a logo was actually found — "found, or determined there
        # isn't one" is still a resolved state for that cell, not a reason
        # to keep spinning.
        try:
            ft.advance_research_stage(user_id, college_id, "ea")
        except Exception:
            logger.warning(
                "Failed to advance research stage past logo for %r", college_name,
                exc_info=True,
            )

    # --- Stage 3: structure every requirement, collecting deadlines and
    # ResearchSource docs along the way — nothing written to College or
    # Requirement docs yet, just building the lists Stages 4-5 write. ------
    source_doc_id_cache: dict[
        tuple[str, str], str
    ] = {}  # (short_id, college_id) -> doc id
    requirements: list[Requirement] = []
    skipped_colleges: set[str] = set()
    # college_id -> {"ea"/"ed"/"rd"/"financialAid": ISO date string} — merged
    # into College.deadlines below so the dashboard has real dates to show,
    # not just the underlying Requirement docs.
    deadlines_by_college: dict[str, dict[str, str]] = {}
    _DEADLINE_FIELD = {
        "EA": "ea",
        "ED": "ed",
        "RD": "rd",
        "financial_aid": "financialAid",
    }

    for item in extracted:
        try:
            college_id = name_to_id.get(item["college_name"])
            if not college_id:
                skipped_colleges.add(item["college_name"])
                continue

            deadline_kind = item.get("deadline_kind")
            deadline_iso = item.get("deadline_iso")
            field = _DEADLINE_FIELD.get(deadline_kind) if deadline_kind else None
            if field and deadline_iso:
                college_deadlines = deadlines_by_college.setdefault(college_id, {})
                existing = college_deadlines.get(field)
                # A college can have e.g. both ED I and ED II, which both map
                # to "ed" — keep the earliest (ISO strings sort
                # lexicographically), the more urgent one, rather than
                # whichever came later in the list.
                if existing is None or deadline_iso < existing:
                    college_deadlines[field] = deadline_iso

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

            # .agents-cli-spec.md § Constraints: "Every stored Requirement
            # must carry at least one sourceId once research has run on it;
            # requirements with zero sources are allowed only in the
            # not_researched state." Enforced in code, not just by
            # instruction — found live (Milestone 11's full test-suite run):
            # the LLM occasionally emits an item with an empty
            # source_short_ids AND needs_verification=False in the same
            # breath (self-inconsistent), which the instruction alone
            # doesn't prevent.
            #
            # Only forced for medium/low confidence, though — a missing
            # citation is genuinely the risky combination when the LLM
            # itself is also unsure, but a HIGH-confidence claim (a source
            # directly and unambiguously stated it, per the confidence
            # field's own definition below) shouldn't get flagged just
            # because short_id text-overlap matching happened to miss it.
            # Found live: over-eager here was flooding the table with
            # "needs verification" badges on requirements the research
            # genuinely nailed, which trained a judge to ignore the badge
            # rather than trust it on the requirements that actually
            # warrant a second look.
            needs_verification = item.get("needs_verification", False) or (
                not resolved_source_ids and item.get("confidence") != "high"
            )

            requirements.append(
                Requirement(
                    college_id=college_id,
                    type=item["type"],
                    description=item["description"],
                    required=item.get("required", True),
                    deadline=item.get("deadline_iso") or None,
                    category=item.get("category"),
                    confidence=item["confidence"],
                    needs_verification=needs_verification,
                    source_ids=resolved_source_ids,
                    recommendation_count=item.get("recommendation_count"),
                )
            )
        except Exception:
            # One malformed item (an unexpected shape the LLM's structured
            # output slipped through with) must not cost every other
            # college's already-built requirements in the same batch.
            logger.warning(
                "Skipping a malformed requirement item for %r",
                item.get("college_name") if isinstance(item, dict) else item,
                exc_info=True,
            )

    # --- Stage 4: deadlines, ONE FIELD AT A TIME — EA, then ED, then RD,
    # then financial aid. The loading spinner (research_stage) sits on
    # exactly one of these at a time, advancing to the next only once the
    # current one is written (found) or confirmed there's nothing to write
    # (not found) — either way that cell is resolved and the spinner moves
    # on, rather than every still-empty deadline cell spinning together. --
    _DEADLINE_FIELD_ORDER = ("ea", "ed", "rd", "financialAid")
    _NEXT_STAGE_AFTER_DEADLINE = {
        "ea": "ed",
        "ed": "rd",
        "rd": "financialAid",
        "financialAid": "requirements",
    }
    college_deadlines = deadlines_by_college.get(college_id, {}) if college_id else {}
    for field in _DEADLINE_FIELD_ORDER:
        if not college_id:
            break
        if field in college_deadlines:
            try:
                ft.update_college_deadlines(
                    user_id, college_id, {field: college_deadlines[field]}
                )
            except Exception:
                logger.warning(
                    "Failed to save %s deadline for college %r, continuing",
                    field, college_id, exc_info=True,
                )
        # Short, deliberate pause before revealing this field resolved —
        # long enough for the frontend's poll to actually catch this cell's
        # spinner before it moves to the next one, short enough that four
        # of these barely register against a multi-minute research run.
        await asyncio.sleep(0.6)
        try:
            ft.advance_research_stage(user_id, college_id, _NEXT_STAGE_AFTER_DEADLINE[field])
        except Exception:
            logger.warning(
                "Failed to advance research stage past %s for %r",
                field, college_name, exc_info=True,
            )

    # --- Stage 5: the full requirement docs — essay prompts, recommendation
    # counts, etc., behind the table's "N tracked" count and (via
    # readiness_agent.py, which runs after this pipeline) its Readiness
    # column. Saved in small paced chunks, not one flat write, with
    # `requirements_total` set first — this is what lets the frontend show
    # a requirements-saved-so-far progress bar (see College.
    # requirements_total) instead of the count silently jumping from 0 to
    # its final value. -------------------------------------------------
    requirements_by_college: dict[str, list[Requirement]] = {}
    for req in requirements:
        requirements_by_college.setdefault(req.college_id, []).append(req)
    for college_id, college_requirements in requirements_by_college.items():
        try:
            ft.set_requirements_total(user_id, college_id, len(college_requirements))
        except Exception:
            logger.warning(
                "Failed to set requirements_total for college %r, continuing",
                college_id, exc_info=True,
            )
        # A fixed ~6 visible steps regardless of how many requirements this
        # college has, rather than one write per requirement (which could
        # be dozens of extra Firestore round trips) or one flat write (no
        # progress bar to show at all).
        chunk_size = max(1, -(-len(college_requirements) // 6))  # ceil division
        for i in range(0, len(college_requirements), chunk_size):
            if i > 0:
                await asyncio.sleep(0.3)
            try:
                ft.save_requirements(
                    user_id, college_requirements[i : i + chunk_size]
                )
            except Exception:
                logger.warning(
                    "Failed to save requirements for college %r, continuing",
                    college_id, exc_info=True,
                )

    if skipped_colleges:
        logger.warning(
            "requirements_agent: no Firestore college_id for %s — extracted "
            "requirements for these were dropped, not written unattributed.",
            skipped_colleges,
        )

    needing_verification = sum(1 for r in requirements if r.needs_verification)
    summary = f"Extracted {len(requirements)} requirement(s)"
    if needing_verification:
        summary += f", {needing_verification} flagged for verification"
    summary += "."
    log_agent_run_complete(callback_context, summary)


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
