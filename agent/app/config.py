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


@dataclass(frozen=True)
class AppConfig:
    worker_model: str = "gemini-3.6-flash"
    critic_model: str = "gemini-3.6-flash"
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
