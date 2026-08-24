#!/usr/bin/env python
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

"""Captures all 3 of Collegentic's eval cases directly via InMemoryRunner
and writes them in the "grading input" trace format `agents-cli eval
grade` expects — bypassing `agents-cli eval generate`'s HTTP/SSE path
entirely.

Why this exists: `agents-cli eval generate` boots a local HTTP server and
streams each case over `/run_sse` with a hardcoded 120s inter-event read
timeout (google/agents/cli/_adk_client.py's `_RUN_SSE_TIMEOUT`, not
CLI-configurable). Collegentic's real research pipeline routinely has a
single stage (a `google_search`-heavy LLM call, or the requirements
confidence-refinement loop) that goes quiet for longer than that between
visible events — confirmed live: the two real-college cases failed with
"Read timed out" even after upgrading agents-cli 1.3.1 -> 1.4.1 fixed an
unrelated content-less-event parsing bug (the third case, a cheap
clarifying-question-only turn, succeeded through the normal HTTP path
both before and after that fix). This isn't an agent-quality problem to
fix; it's this tool's fixed timeout being shorter than a genuinely
multi-stage, real-web-search pipeline can guarantee. Calling the same
root_agent in-process sidesteps the HTTP layer (and its timeout)
altogether while exercising the *exact* same agent code eval_generate
would have — nothing about the pipeline is stubbed or shortened. The
third case is captured the same way here too (even though it doesn't
strictly need to be) so the whole suite reproduces from one script run
with no `eval generate` step or manual merge needed.

Run this whenever tests/eval/datasets/collegentic-scenarios.json's prompts
change; `agents-cli eval grade` then reads this script's output directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from google.adk.events import Event  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from app.agent import root_agent  # noqa: E402
from app.tools import firestore_tools as ft  # noqa: E402


def _event_to_json(event: Event) -> dict:
    payload: dict = {"author": event.author}
    if event.content is not None:
        payload["content"] = event.content.model_dump(mode="json", exclude_none=True)
    if event.actions is not None and event.actions.state_delta:
        payload["state_delta"] = event.actions.state_delta
    if event.timestamp is not None:
        payload["event_time"] = event.timestamp
    return payload


async def _run_case(prompt: str, user_id: str) -> list[dict]:
    runner = InMemoryRunner(agent=root_agent, app_name="app")
    session = await runner.session_service.create_session(
        app_name="app", user_id=user_id
    )
    events: list[dict] = [
        {
            "author": "user",
            "content": {"role": "user", "parts": [{"text": prompt}]},
        }
    ]
    async for event in runner.run_async(
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=prompt)]
        ),
        user_id=user_id,
        session_id=session.id,
    ):
        events.append(_event_to_json(event))
    return events


def _cleanup(user_id: str) -> None:
    """Same teardown shape every live integration test in this repo uses —
    a captured-trace case is a real pipeline run against real Firestore."""
    from app.schemas import Requirement

    for college in ft.get_tracked_colleges(user_id):
        for req in ft._read_all(ft._requirements(user_id, college.id), Requirement):
            ft._requirements(user_id, college.id).document(req.id).delete()
        for prompt in ft.get_essay_prompts(user_id, college.id):
            ft._essay_prompts(user_id, college.id).document(prompt.id).delete()
        ft._colleges(user_id).document(college.id).delete()
    for coll_fn in (
        ft._research_sources,
        ft._tasks,
        ft._conflicts,
        ft._materials,
        ft._essay_matches,
        ft._agent_runs,
        ft._recommendations,
    ):
        for doc in coll_fn(user_id).stream():
            doc.reference.delete()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(
            Path(__file__).parent / "datasets" / "collegentic-live-traces.json"
        ),
    )
    args = parser.parse_args()

    cases = [
        (
            "single_college_grounded_research",
            "I'm applying to Rice University.",
        ),
        (
            "two_colleges_cross_college_analysis",
            "I'm applying to Princeton University and Stanford University.",
        ),
        # Cheap enough to also go through `agents-cli eval generate`
        # directly (no research pipeline invoked, just a clarifying
        # question) — captured the same way here too so the whole suite
        # reproduces from one script run with no merge step needed.
        (
            "ambiguous_college_name_asks_for_clarification",
            "I'm applying to Miami.",
        ),
    ]

    eval_cases = []
    for case_id, prompt in cases:
        user_id = f"eval-{uuid.uuid4()}"
        print(f"[capture] running {case_id} ({prompt!r}) as user {user_id} ...")
        try:
            events = await _run_case(prompt, user_id)
        finally:
            _cleanup(user_id)
        # `prompt`/`responses` alongside `agent_data` isn't strictly
        # required (eval grade can derive {prompt}/{response} from the
        # first/last text-bearing event in agent_data.turns), but adding
        # them explicitly matches the shape `agents-cli eval generate`
        # itself produces and makes the file grade-ready with no
        # additional processing.
        last_text_event = next(
            e
            for e in reversed(events)
            if e.get("content", {}).get("parts", [{}])[0].get("text")
        )
        eval_cases.append(
            {
                "eval_case_id": case_id,
                "prompt": events[0]["content"],
                "responses": [{"response": last_text_event["content"]}],
                "agent_data": {"turns": [{"turn_index": 0, "events": events}]},
            }
        )
        print(f"[capture] {case_id}: {len(events)} events captured.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"eval_cases": eval_cases}, indent=2))
    print(f"[capture] wrote {len(eval_cases)} case(s) to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
