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
name/alias match rather than creating a duplicate. Sets:
- `college_name_to_id`: every requested name -> its Firestore college id
- `new_college_names`: only the names that didn't already exist — these are
  the ones that actually need research (see .agents-cli-spec.md § Cost
  Control: "only perform new research when a school is newly added").

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
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from app.schemas import College
from app.tools import firestore_tools as ft

logger = logging.getLogger(__name__)


class CollegeIntakeAgent(BaseAgent):
    def __init__(self, name: str = "college_intake_agent"):
        super().__init__(name=name)

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        requested: list[str] = ctx.session.state.get("requested_colleges", [])
        user_id = ctx.session.user_id

        existing = ft.get_tracked_colleges(user_id)
        by_name = {c.name.strip().lower(): c for c in existing}

        name_to_id: dict[str, str] = {}
        new_names: list[str] = []
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
            else:
                new_id = ft.save_college(user_id, College(name=name))
                name_to_id[name] = new_id
                new_names.append(name)

        logger.info(
            "[%s] %d requested, %d new: %s",
            self.name,
            len(requested),
            len(new_names),
            new_names,
        )
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
