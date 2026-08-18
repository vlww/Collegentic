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

"""Structural checks on college_research_agent's wiring — no model calls."""

from google.adk.tools import google_search

from app.sub_agents.research_agent import college_research_agent


def test_research_agent_has_no_write_tools() -> None:
    """Per .agents-cli-spec.md § Constraints, the research agent may only
    read the web — it has no Firestore write tool, so it cannot itself
    persist unverified data."""
    assert college_research_agent.tools == [google_search]


def test_research_agent_output_key_and_callbacks_wired() -> None:
    assert college_research_agent.output_key == "raw_research_findings"
    assert college_research_agent.before_agent_callback is not None
    assert college_research_agent.after_agent_callback is not None


def test_research_agent_instruction_enforces_source_priority_and_honesty() -> None:
    instruction = college_research_agent.instruction
    assert isinstance(instruction, str)  # not a callable instruction-provider
    assert "Official college/admissions websites" in instruction
    assert "UNCERTAIN" in instruction
    assert "never invent information" in instruction.lower()
