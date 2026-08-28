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

"""College Intake Agent — deterministic (non-LLM) pipeline step.

Ensures a Firestore College doc exists for every name in
`state["requested_colleges"]`, reusing an existing one by case-insensitive
name/alias match rather than creating a duplicate. Creates a brand-new
college's row RIGHT AWAY, for every requested college at once (staggered by
a short pace so rows still visibly appear one by one, not in one jump) —
this step is pure Firestore bookkeeping with no LLM/search call (the actual
name was already resolved by the Orchestrator's own parsing step before
this ever runs), so doing it for the whole list up front is fast, and lets
a judge see the full requested list take shape almost immediately instead
of waiting for each college's (much slower) research to finish before the
next one's row even appears. The actual per-college RESEARCH still happens
one college at a time, sequentially, in PerCollegeResearchAndExtraction
(orchestrator_agent.py) — that's what the loading-spinner cells key off,
not row existence. Sets:
- `college_name_to_id`: every requested name -> its Firestore college id
- `new_college_names`: names that didn't already exist, OR did but have zero
  Requirement docs (a stub from a prior run interrupted by an error before
  research finished) — these are the ones that actually need research (see
  .agents-cli-spec.md § Cost Control: "only perform new research when a
  school is newly added", extended to also cover "or was never actually
  researched") — IN THE ORDER the student listed them, since that's the
  order they'll be researched and shown in.

Also starts this run's PipelineProgress doc (total = len(new_college_names))
the moment that count is known.

Built now (Milestone 4) because the Requirements Agent needs a real
Firestore college_id to write Requirement docs into. This is exactly the
"identify new schools" bookkeeping .agents-cli-spec.md attributes to the
Orchestrator (Milestone 5) — that agent will drive `requested_colleges`
from parsed natural-language input and reuse this step as-is, following
EscalationChecker's precedent (deep-search/app/agent.py) of a custom
`BaseAgent` for deterministic graph steps that need no LLM reasoning.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.tools import firestore_tools as ft

logger = logging.getLogger(__name__)


class CollegeIntakeAgent(BaseAgent):
    def __init__(self, name: str = "college_intake_agent"):
        super().__init__(
            name=name,
            before_agent_callback=log_agent_run_start,
            after_agent_callback=log_agent_run_complete,
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        requested: list[str] = ctx.session.state.get("requested_colleges", [])
        user_id = ctx.session.user_id

        existing = ft.get_tracked_colleges(user_id)
        by_name = {c.name.strip().lower(): c for c in existing}
        # A college with zero Requirement docs is a stub: either brand new,
        # or an "already tracked" college whose research was interrupted
        # partway through by an earlier error (see api.py's pipeline error
        # handler) — Requirements Agent had already saved its requirements
        # before the callback that does college branding/logo lookup could
        # fail, or it crashed even before that. Either way, a name matching
        # one of these should still count as needing research, not get
        # silently skipped as "already tracked" — that's what makes "resume
        # after an error" work by just re-submitting the same names.
        try:
            researched_ids = {
                r.college_id for r in ft.get_requirements(user_id, [c.id for c in existing])
            }
        except Exception:
            # Fail safe, not fail closed: if we can't tell which tracked
            # colleges are already researched, treat all of them as still
            # needing it — worst case that's some wasted re-research, not a
            # silently-skipped college and not a failed pipeline run over a
            # transient Firestore read.
            logger.warning(
                "Failed to check research status for tracked colleges; treating "
                "all matched colleges as needing research to be safe.",
                exc_info=True,
            )
            researched_ids = set()

        name_to_id: dict[str, str] = {}
        new_names: list[str] = []
        placeholder_rows_created = 0
        for name in requested:
            key = name.strip().lower()
            match = by_name.get(key)
            if match is None:
                match = next(
                    (c for c in existing if key in (a.lower() for a in c.aliases)),
                    None,
                )
            if match:
                name_to_id[name] = match.id  # type: ignore[assignment]
                if match.id not in researched_ids:
                    new_names.append(name)
            else:
                if placeholder_rows_created > 0:
                    # A brand-new college's row is the very first thing a
                    # student sees appear on the Colleges table. Paced
                    # (rather than all created within the same instant) so
                    # requesting several colleges at once still reveals one
                    # placeholder row at a time — cheap to do since this is
                    # just a Firestore write, no LLM/search call.
                    time.sleep(0.3)
                new_id = ft.create_college_placeholder(user_id, name)
                name_to_id[name] = new_id
                new_names.append(name)
                placeholder_rows_created += 1

        logger.info(
            "[%s] %d requested, %d new: %s",
            self.name,
            len(requested),
            len(new_names),
            new_names,
        )
        if new_names:
            try:
                ft.start_pipeline_progress(user_id, total_colleges=len(new_names))
            except Exception:
                logger.warning("Failed to start pipeline progress doc", exc_info=True)
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "college_name_to_id": name_to_id,
                    "new_college_names": new_names,
                }
            ),
        )


college_intake_agent = CollegeIntakeAgent()
