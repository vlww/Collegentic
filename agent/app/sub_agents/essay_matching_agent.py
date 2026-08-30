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
step 3 (cross_college_analysis): reads EssayPrompts + StudentMaterials,
produces EssayMatch docs.

Used to be a two-stage LlmAgent pipeline (structure each essay
Requirement's free text into a prompt, then judge thematic reuse-fit
against the student's materials). Replaced with a deterministic,
keyword-bucket categorizer (app/tools/essay_matching.py) — same
"business rules in code" split as app/tools/scoring.py's priority/
readiness formulas: a prompt and a material either land in the same
broad category (personal statement, why-this-major, greatest challenge,
...) or they don't, and that's the actual signal the Essay Map graph
needs to draw a connection. The old LLM version's only trigger was a
college-research run, via cross_college_analysis below — a student who
added a material through POST /api/materials directly saw zero
connections until their next research run, indistinguishable from
"broken." The new version is pure Python (no network call), so it's cheap
enough to also run synchronously and immediately from
create_material/update_material in app/api.py, not just here.

.agents-cli-spec.md § Constraints: "Only the Essay Matching Agent reasons
about essay content, and only to score reuse-fit — it never rewrites,
edits, or coaches." Still true here: this only ever produces EssayPrompt/
EssayMatch docs, never touches a StudentMaterial's own text.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.tools.essay_matching import recompute_essay_matches


def _log_essay_matching_complete(callback_context: CallbackContext) -> None:
    """after_agent_callback — same "read the state _run_async_impl wrote,
    log a concrete summary" shape as every other sub-agent's own _persist_x
    (see e.g. conflict_agent.py's _persist_conflicts), even though the
    actual Firestore write already happened synchronously in
    _run_async_impl below, not here."""
    summary = callback_context.state.get("essay_matching_summary")
    log_agent_run_complete(callback_context, summary)


class EssayMatchingAgent(BaseAgent):
    def __init__(self, name: str = "essay_matching_pipeline"):
        super().__init__(
            name=name,
            before_agent_callback=log_agent_run_start,
            after_agent_callback=_log_essay_matching_complete,
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        user_id = ctx.session.user_id
        prompt_count, match_count = recompute_essay_matches(user_id)
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "essay_matching_summary": (
                        f"Structured {prompt_count} essay prompt(s), "
                        f"found {match_count} reuse match(es)."
                    )
                }
            ),
        )


essay_matching_pipeline = EssayMatchingAgent()
