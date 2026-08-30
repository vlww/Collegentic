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

"""Deadline & Priority Agent — .agents-cli-spec.md § Deadline & Priority Agent.

Two-stage shape (same reasoning as every other pipeline stage so far):
`TaskPriorityContextAgent` (custom BaseAgent, no LLM) computes every
non-Done task's priority score deterministically via app/tools/scoring.py,
then `priority_explanation_agent` (LlmAgent, output_schema, no tools)
rewrites each task's pre-computed facts into ONE natural sentence — it
never sees or invents the number, only explains it. This is the
"deterministic formula, LLM only for phrasing" split the spec calls for
("the exact formula should be explainable").

Batches every task's explanation into ONE Gemini call regardless of task
count (cost control) — the LLM reads a compact {task_id: facts} payload and
returns {task_id: sentence} pairs, not one call per task.

Re-scores every non-Done task on every pipeline run, same reasoning as
TaskContextAgent in task_planning_agent.py: correctness over incremental
tracking, and it's cheap (one deterministic pass + one batched LLM call,
no web search, no re-persisting Requirements/Tasks themselves).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import BaseModel, Field

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config, llm_timeout_config
from app.schemas import TaskStatus
from app.tools import firestore_tools as ft
from app.tools.scoring import compute_priority_score, resolve_effective_deadline


class TaskPriorityContextAgent(BaseAgent):
    def __init__(self, name: str = "task_priority_context_agent"):
        super().__init__(
            name=name,
            before_agent_callback=log_agent_run_start,
            after_agent_callback=log_agent_run_complete,
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        user_id = ctx.session.user_id
        tasks = [
            task for task in ft.get_tasks(user_id) if task.status != TaskStatus.DONE
        ]
        colleges_by_id = {
            college.id: college for college in ft.get_tracked_colleges(user_id)
        }

        context_payload = {}
        for task in tasks:
            college = colleges_by_id.get(task.college_id) if task.college_id else None
            effective_deadline = resolve_effective_deadline(
                task.deadline, college.deadlines if college else None
            )
            breakdown = compute_priority_score(
                deadline=effective_deadline,
                estimated_minutes=task.estimated_minutes,
                required=task.required,
                status=task.status.value,
                has_dependencies=bool(task.dependencies),
                category=task.category,
            )
            context_payload[task.id] = {
                "title": task.title,
                "score": breakdown.score,
                "facts": breakdown.explanation_facts,
            }

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"task_priority_context": context_payload}
            ),
        )


class TaskExplanation(BaseModel):
    task_id: str = Field(description="Must exactly match a key from TASKS.")
    explanation: str = Field(
        description="ONE natural, concise sentence explaining why this task has "
        "this priority — style: 'This task is high priority because its deadline "
        "is 8 days away and it's estimated to take 4 hours.' Use ONLY the given "
        "facts; never invent a date, percentage, or detail not present in them."
    )


class TaskExplanationList(BaseModel):
    explanations: list[TaskExplanation]


_PRIORITY_EXPLANATION_INSTRUCTION = """You write one-sentence priority
explanations for a college-application task list. For EACH task below,
write a natural, plain-language sentence explaining why it has the score it
has, echoing its given facts, don't add anything they didn't say. No
markdown formatting and no em dashes, write it like an ordinary sentence.

TASKS (task_id -> title, score 0-100, facts):
{task_priority_context}

Respond with a single raw JSON object matching the TaskExplanationList schema,
with one entry per task_id above."""


def _persist_priorities(callback_context) -> None:
    """Runs as an after_agent_callback for the same reason as every other
    output_schema agent's persist step in this codebase."""
    user_id = callback_context.user_id
    context_payload = callback_context.state.get("task_priority_context") or {}
    explanation_list = callback_context.state.get("task_explanations") or {}
    explanations_by_id = {
        item["task_id"]: item["explanation"]
        for item in explanation_list.get("explanations", [])
    }

    for task_id, info in context_payload.items():
        # Falls back to the raw deterministic facts if the LLM ever drops a
        # task_id — every task still gets a truthful explanation, never a
        # blank one, even if the LLM's phrasing pass is incomplete.
        explanation = explanations_by_id.get(task_id) or info["facts"]
        ft.update_task_priority(user_id, task_id, info["score"], explanation)

    log_agent_run_complete(
        callback_context, f"Scored priority for {len(context_payload)} task(s)."
    )


priority_explanation_agent = LlmAgent(
    model=config.worker_model,
    # `batched=True`, not the plain (45s) timeout: this call batches EVERY
    # non-Done task's explanation into one Gemini call regardless of count
    # (see module docstring), same shape as readiness/essay/conflict's own
    # batched calls — all of which already use this longer timeout. Found
    # live: with the plain 45s timeout, a student tracking several colleges
    # (15-25+ open tasks) reliably hit 504 DEADLINE_EXCEEDED here, and since
    # this stage sits ahead of readiness_pipeline/cross_college_analysis in
    # college_intake_pipeline, that timeout aborted the ENTIRE rest of the
    # run — Readiness and Cross-College Conflicts (via conflict_pipeline)
    # never got a chance to run either, for a reason that had nothing to do
    # with either of them.
    generate_content_config=llm_timeout_config(batched=True),
    name="priority_explanation_agent",
    description="Writes natural-language explanations for pre-computed task priority scores.",
    instruction=_PRIORITY_EXPLANATION_INSTRUCTION,
    output_schema=TaskExplanationList,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="task_explanations",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_persist_priorities,
)

priority_pipeline = SequentialAgent(
    name="priority_pipeline",
    description="Scores every non-Done task's priority deterministically, then explains each in plain language.",
    sub_agents=[TaskPriorityContextAgent(), priority_explanation_agent],
)
