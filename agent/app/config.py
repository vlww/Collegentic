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

"""Single source of truth for model choice and pipeline knobs.

Hardcoded rather than env-driven (unlike the `deep-search` recipe's
MODEL_NAME env var): app/agent.py's scaffolded root_agent already hardcodes
`gemini-3.6-flash` directly, and .agents-cli-spec.md's cost-control rule is
"never a pricier/older model without explicit ask" — a literal default is
harder to accidentally override into an expensive model than an env var is.
"""

from dataclasses import dataclass

from google.genai import types


@dataclass(frozen=True)
class AppConfig:
    worker_model: str = "gemini-3.6-flash"
    critic_model: str = "gemini-3.6-flash"
    # Essay Editor's grammar-only check (app/tools/grammar_check.py) — Gemma
    # takes a first, cheap pass, and worker_model (Gemini) always follows
    # with its OWN independent detection pass over the same text (Gemma's
    # candidates are folded in as a hint, never a gate — see that module's
    # docstring for why: this used to return "no issues" outright whenever
    # Gemma's own output was empty, without Gemini ever getting a look).
    # Confirmed live via the Google AI Studio (Gemini Developer API)
    # ListModels endpoint — this project's Vertex AI has no Gemma access at
    # all (see grammar_check.py's module docstring), and guessing a name
    # from training data was wrong here too: Gemma has moved to a 4th
    # generation in this environment, same as Gemini's 3.6/3.7 (§
    # .agents-cli-spec.md's "don't guess model names from training data"
    # rule). The mixture-of-experts variant (26B total, only 4B active) over
    # the dense 31b one — cheaper/faster per token, and a quick grammar-only
    # pass doesn't need the bigger model's full capacity.
    grammar_model: str = "gemma-4-26b-a4b-it"
    # Gemma's own timeout for the grammar check specifically — much shorter
    # than llm_call_timeout_seconds below on purpose. Found live: since
    # Gemma's role there is now a supplementary hint (not required — see
    # above), waiting the FULL 45s default on a slow/hanging Gemma call
    # before ever starting the real (Gemini) detection pass was adding
    # nearly a minute of pure dead time to what's supposed to be a quick
    # check, for a call whose result barely matters if it's this slow
    # anyway. Short enough that a hung Gemma call costs a few seconds, not
    # most of the request.
    grammar_gemma_timeout_seconds: int = 10
    # Every LlmAgent call site passes `generate_content_config=llm_timeout_config()`
    # (below) so a single hung generateContent call fails in bounded time
    # instead of relying solely on orchestrator_agent.py's outer, much
    # coarser 240s-per-college `asyncio.wait_for`. Found live: concurrent
    # Gemini calls occasionally produce what looks like a hung gRPC channel
    # — no response, no error, no timeout — and without a real per-call
    # timeout at the HTTP layer, that hang is unbounded, not just slow.
    # Generous enough for a real google_search-grounded call (which can run
    # several search rounds inside one model turn) not to trip on
    # legitimately-slow-but-working responses.
    llm_call_timeout_seconds: int = 45
    # A handful of agents batch EVERY tracked college's data into one call
    # by design (task_planning_agent, requirements_agent, conflict_detection_
    # agent) — a real, growing payload as more colleges get tracked, not a
    # hung/broken call, so the default above is too tight
    # for them specifically: found live, task_planning_agent failed outright
    # once its batched call needed more than 45s for enough colleges' worth
    # of requirements. Longer, not unbounded — still fails fast enough for
    # per-college/per-pipeline retries (see orchestrator_agent.py) to
    # recover well within a student's patience.
    llm_call_timeout_seconds_for_batched_agents: int = 120
    # Requirements confidence-refinement loop (Milestone 4) — bounded lower
    # than deep-search's default of 5, since our per-college research scope
    # is narrower. See .agents-cli-spec.md § Constraints. Lowered from 2 to
    # 1 (each iteration is a full extra evaluate + real google_search
    # follow-up round, per college): with the per-college research loop
    # (orchestrator_agent.py's PerCollegeResearchAndExtraction) now running
    # college_research_agent sequentially per college rather than once for
    # every college together, every extra confidence-loop iteration is
    # multiplied by the college count instead of paid once — this was the
    # single biggest lever on total wall-clock time for a demo a judge is
    # watching live. requirements_agent.py's findings_evaluator "fail" bar
    # was also loosened so the one remaining iteration triggers less often.
    max_research_confidence_iterations: int = 1
    # How many times a full agent pipeline run (Orchestrator, task replan)
    # is attempted, end to end, before giving up — 2 means "try once, and
    # if any agent in the chain raises, automatically restart the whole
    # pipeline from scratch exactly once more" before surfacing an error.
    # See api.py's _run_pipeline_with_auto_restart.
    max_pipeline_attempts: int = 2


config = AppConfig()


def llm_timeout_config(*, batched: bool = False) -> types.GenerateContentConfig:
    """A fresh `GenerateContentConfig` carrying just a per-call HTTP
    timeout — pass as `generate_content_config=llm_timeout_config()` on
    every `LlmAgent(...)` (`batched=True` for the few agents that
    deliberately process every tracked college in one call — see
    `llm_call_timeout_seconds_for_batched_agents`'s docstring). Returns a
    fresh instance each call rather than one shared object: `LlmAgent` may
    attach more onto its own `generate_content_config` (e.g. `response_schema`
    for an `output_schema` agent), and instances are already module-level
    singletons reused across every concurrent call to that agent, so sharing
    one mutable object ACROSS DIFFERENT agents (each with different schemas)
    risks one agent's settings leaking into another's."""
    seconds = (
        config.llm_call_timeout_seconds_for_batched_agents
        if batched
        else config.llm_call_timeout_seconds
    )
    return types.GenerateContentConfig(
        http_options=types.HttpOptions(timeout=seconds * 1000)
    )
