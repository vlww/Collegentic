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

"""Structural checks on the Essay Matching Agent's wiring — no model calls,
no Firestore. Live behavior is covered by
tests/integration/test_essay_matching_agent.py; the categorizer itself by
tests/unit/test_essay_matching.py.
"""

from app.sub_agents.essay_matching_agent import essay_matching_pipeline


def test_pipeline_logs_activity() -> None:
    """Deterministic now (app/tools/essay_matching.py), not an LlmAgent —
    just checks the Agent Activity logging hooks are still wired."""
    assert essay_matching_pipeline.before_agent_callback is not None
    assert essay_matching_pipeline.after_agent_callback is not None


def test_pipeline_name() -> None:
    assert essay_matching_pipeline.name == "essay_matching_pipeline"
