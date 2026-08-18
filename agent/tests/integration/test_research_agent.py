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

"""Live integration test for the College Research Agent.

Per .agents-cli-spec.md's testing rules, this asserts on *plumbing*, not on
research quality/content (that belongs in agents-cli eval, Milestone 15):
that a real `google_search`-backed run produces non-trivial output, that
the source-collection callback populates session state from real grounding
metadata, and that the activity-logging callbacks write a completed
AgentRun doc to Firestore.
"""

import uuid

from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agent import root_agent
from app.tools import firestore_tools as ft


def test_research_agent_produces_findings_and_collects_sources() -> None:
    user_id = f"test-{uuid.uuid4()}"
    runner = InMemoryRunner(agent=root_agent, app_name="test")
    session = runner.session_service.create_session_sync(
        user_id=user_id, app_name="test"
    )

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Research this college: Rice University")],
    )
    events = list(
        runner.run(new_message=message, user_id=user_id, session_id=session.id)
    )

    final_text = "".join(
        part.text
        for event in events
        if event.content and event.content.parts
        for part in event.content.parts
        if part.text
    )
    assert len(final_text) > 200  # a real per-college write-up, not a one-liner
    assert "Rice" in final_text

    updated_session = runner.session_service.get_session_sync(
        app_name="test", user_id=user_id, session_id=session.id
    )
    sources = updated_session.state.get("sources", {})
    assert len(sources) > 0
    first_source = next(iter(sources.values()))
    assert first_source["url"].startswith("http")

    runs = ft.get_agent_runs(user_id)
    assert len(runs) == 1
    assert runs[0].agent_name == "college_research_agent"
    assert runs[0].status.value == "completed"

    # Cleanup: this test writes directly under a throwaway user_id.
    for run in runs:
        ft._agent_runs(user_id).document(run.id).delete()
