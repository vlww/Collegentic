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

"""Structural checks on the Conflict Agent's wiring — no model calls, no
Firestore. Live behavior is covered by tests/integration/test_conflict_agent.py.
"""

from app.sub_agents.conflict_agent import (
    ConflictContextAgent,
    conflict_detection_agent,
    conflict_pipeline,
)


def test_conflict_detection_agent_has_no_tools() -> None:
    """It only reasons over the pre-gathered facts — never sees raw
    Firestore, so every id it can possibly reference is already bounded by
    what ConflictContextAgent handed it."""
    assert conflict_detection_agent.tools == []


def test_conflict_detection_agent_output_schema_wired() -> None:
    assert conflict_detection_agent.output_key == "detected_conflicts"
    assert conflict_detection_agent.output_schema is not None


def test_context_agent_logs_activity() -> None:
    agent = ConflictContextAgent()
    assert agent.before_agent_callback is not None
    assert agent.after_agent_callback is not None


def test_pipeline_order() -> None:
    assert [agent.name for agent in conflict_pipeline.sub_agents] == [
        "conflict_context_agent",
        "conflict_detection_agent",
    ]
