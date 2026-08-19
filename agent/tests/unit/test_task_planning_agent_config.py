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

"""Structural checks on the Task Planning Agent's wiring — no model calls,
no Firestore. Live behavior is covered by
tests/integration/test_task_planning_agent.py.
"""

from app.sub_agents.task_planning_agent import (
    TaskContextAgent,
    task_planning_agent,
    task_planning_pipeline,
)


def test_task_planning_agent_has_no_tools() -> None:
    """Pure synthesis over state populated by TaskContextAgent — never
    searches or writes Firestore directly (persistence happens in its
    after_agent_callback, not via a tool call)."""
    assert task_planning_agent.tools == []


def test_task_planning_agent_output_schema_wired() -> None:
    assert task_planning_agent.output_key == "planned_tasks"
    assert task_planning_agent.output_schema is not None


def test_task_context_agent_logs_activity() -> None:
    agent = TaskContextAgent()
    assert agent.before_agent_callback is not None
    assert agent.after_agent_callback is not None


def test_pipeline_order() -> None:
    assert [agent.name for agent in task_planning_pipeline.sub_agents] == [
        "task_context_agent",
        "task_planning_agent",
    ]
