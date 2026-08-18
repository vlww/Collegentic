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
    # is narrower. See .agents-cli-spec.md § Constraints.
    max_research_confidence_iterations: int = 2


config = AppConfig()
