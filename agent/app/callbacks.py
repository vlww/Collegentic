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

"""Shared ADK callbacks reused across sub-agents.

`log_agent_run_start` / `log_agent_run_complete`: attach as
before_agent_callback / after_agent_callback on every sub-agent. Writes an
AgentRun doc to Firestore at the start and end of that agent's turn — this
is what will power the Agent Activity page (Milestone 13), logging from the
very first agent built rather than being bolted on later. `pipeline_run_id`
groups one intake run's agents together; falls back to the ADK session id
when nothing upstream (i.e. the Orchestrator, Milestone 5) has set one yet,
so an agent is independently testable before the full pipeline exists.

`collect_research_sources_callback`: adapted near-verbatim from
`deep-search/app/agent.py`'s callback of the same name (see
.agents-cli-spec.md § Reference Samples) — harvests Gemini's grounding
metadata (URLs, titles, domains, confidence) into a short-id-keyed source
pool in session state. Deliberately does NOT write to Firestore here: which
college a source supports only becomes clear once the Requirements Agent
(Milestone 4) structures raw findings into per-college Requirement records,
so that agent is the one that persists ResearchSource docs.

Every callback swallows and logs its own Firestore errors rather than
raising — a logging failure must never block agent execution or research
output, per .agents-cli-spec.md § Error Handling.
"""

from __future__ import annotations

import logging

from google.adk.agents.callback_context import CallbackContext

from app.tools import firestore_tools as ft

logger = logging.getLogger(__name__)


def log_agent_run_start(callback_context: CallbackContext) -> None:
    agent_name = callback_context.agent_name
    pipeline_run_id = (
        callback_context.state.get("pipeline_run_id") or callback_context.session.id
    )
    try:
        run_id = ft.start_agent_run(
            callback_context.user_id,
            pipeline_run_id=pipeline_run_id,
            agent_name=agent_name,
        )
        callback_context.state[f"_agent_run_id__{agent_name}"] = run_id
    except Exception:
        logger.exception("Failed to log agent run start for %s", agent_name)


def log_agent_run_complete(callback_context: CallbackContext) -> None:
    agent_name = callback_context.agent_name
    run_id = callback_context.state.get(f"_agent_run_id__{agent_name}")
    if not run_id:
        return
    try:
        ft.complete_agent_run(
            callback_context.user_id, run_id, summary=f"{agent_name} completed."
        )
    except Exception:
        logger.exception("Failed to log agent run completion for %s", agent_name)


def collect_research_sources_callback(callback_context: CallbackContext) -> None:
    """Collects web-based research sources and the claims they support from
    the agent's session events into `state["sources"]` /
    `state["url_to_short_id"]`. Adapted from deep-search/app/agent.py.
    """
    session = callback_context.session
    url_to_short_id = callback_context.state.get("url_to_short_id", {})
    sources = callback_context.state.get("sources", {})
    id_counter = len(url_to_short_id) + 1
    for event in session.events:
        if not (event.grounding_metadata and event.grounding_metadata.grounding_chunks):
            continue
        chunks_info = {}
        for idx, chunk in enumerate(event.grounding_metadata.grounding_chunks):
            if not chunk.web:
                continue
            url = chunk.web.uri
            title = (
                chunk.web.title
                if chunk.web.title != chunk.web.domain
                else chunk.web.domain
            )
            if url not in url_to_short_id:
                short_id = f"src-{id_counter}"
                url_to_short_id[url] = short_id
                sources[short_id] = {
                    "short_id": short_id,
                    "title": title,
                    "url": url,
                    "domain": chunk.web.domain,
                    "supported_claims": [],
                }
                id_counter += 1
            chunks_info[idx] = url_to_short_id[url]
        if event.grounding_metadata.grounding_supports:
            for support in event.grounding_metadata.grounding_supports:
                confidence_scores = support.confidence_scores or []
                chunk_indices = support.grounding_chunk_indices or []
                for i, chunk_idx in enumerate(chunk_indices):
                    if chunk_idx in chunks_info:
                        short_id = chunks_info[chunk_idx]
                        confidence = (
                            confidence_scores[i] if i < len(confidence_scores) else 0.5
                        )
                        text_segment = support.segment.text if support.segment else ""
                        sources[short_id]["supported_claims"].append(
                            {"text_segment": text_segment, "confidence": confidence}
                        )
    callback_context.state["url_to_short_id"] = url_to_short_id
    callback_context.state["sources"] = sources
