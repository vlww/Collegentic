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

"""Task Planning Agent — .agents-cli-spec.md § Task Planning Agent.

Converts Requirement docs into concrete, actionable Task docs.

SCOPE NOTE — pipeline ordering: the spec's ideal pipeline runs Task
Planning after the Conflict Agent (Milestone 10) and Essay Matching Agent
(Milestone 11), so it could fold their findings in (e.g. one
recommendation-request task per teacher role from the Conflict Agent's
minimum-recommendation-plan, rather than one generic "request 2
recommendations" task). Those agents don't exist yet, and the milestone
list builds Task Planning now regardless — so this reasons from
Requirements alone. `task_planning_agent`'s instruction only reads
`{requirements_for_planning}`; adding `{conflict_findings}` /
`{essay_matches}` state refs later is additive, not a rewrite.

Two-stage shape (same reasoning as college_intake_agent before
requirements_agent, and findings_evaluator before requirements_agent in
Milestone 4): `TaskContextAgent` is a deterministic Firestore-read step
(custom BaseAgent, no LLM), `task_planning_agent` is pure synthesis
(output_schema, no tools) — kept apart rather than giving the LLM a
read tool + output_schema together, an untested combination in this
codebase; every other synthesis agent so far reads state, not a live tool.

Re-scans ALL tracked colleges' Requirement docs every run (never just
newly-researched ones — adding college #2 shouldn't lose task coverage for
college #1), but only sends the LLM requirements that don't already have a
task (see TaskContextAgent) — a requirement's title/description/category
are pure LLM-synthesis output with no reason to change once planned (see
firestore_tools.save_tasks's docstring), so re-deriving them for every
already-tracked college on every run got slower and slower as more
colleges piled up, entirely reprocessing the same, unchanged output each
time. `POST /tasks/replan` opts back into reprocessing everything (session
state `force_full_replan`) for the one case that legitimately needs it: a
student wanting already-planned tasks regenerated after a prompt/logic
change, without re-adding every college.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from pydantic import BaseModel, Field

from app.callbacks import log_agent_run_complete, log_agent_run_start
from app.config import config, llm_timeout_config
from app.schemas import Task, TaskCreatedBy
from app.tools import firestore_tools as ft


class TaskContextAgent(BaseAgent):
    """Loads every tracked college's Requirement docs into session state
    for task_planning_agent to reason over — see module docstring for why
    this re-scans every college's Requirements but only sends the ones that
    don't already have a task, unless `force_full_replan` is set."""

    def __init__(self, name: str = "task_context_agent"):
        super().__init__(
            name=name,
            before_agent_callback=log_agent_run_start,
            after_agent_callback=log_agent_run_complete,
        )

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        user_id = ctx.session.user_id
        colleges = ft.get_tracked_colleges(user_id)
        college_id_to_name = {
            college.id: college.name for college in colleges if college.id
        }
        requirements = ft.get_requirements(user_id, list(college_id_to_name.keys()))

        # Only /tasks/replan sets this — see module docstring. Every other
        # caller (the automatic pipeline after new-college research) wants
        # just the requirements planning hasn't already covered.
        if not ctx.session.state.get("force_full_replan"):
            already_planned = {
                task.source_requirement_id
                for task in ft.get_tasks(user_id)
                if task.source_requirement_id
            }
            requirements = [r for r in requirements if r.id not in already_planned]

        requirements_payload = [
            {
                "id": requirement.id,
                "college_id": requirement.college_id,
                "type": requirement.type,
                "description": requirement.description,
                "required": requirement.required,
                "deadline": requirement.deadline.isoformat()
                if requirement.deadline
                else None,
                "confidence": requirement.confidence.value,
                "needs_verification": requirement.needs_verification,
            }
            for requirement in requirements
        ]
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "requirements_for_planning": requirements_payload,
                    "college_id_to_name": college_id_to_name,
                }
            ),
        )


class ExtractedTask(BaseModel):
    college_id: str = Field(
        description="Must exactly match a college_id key from COLLEGES."
    )
    title: str = Field(
        description="A label, not a sentence — about 3 words: the college's short "
        "name followed by a 1-2 word type, e.g. 'Texas A&M Main Essay', 'Georgia "
        "Tech Personal Statement', 'Texas A&M Portfolio', 'Texas A&M Short Answer "
        "1'. No verbs ('Draft', 'Request', 'Submit'), no colons, no restating the "
        "requirement description — that detail belongs in `description`, not here."
    )
    description: str | None = Field(
        default=None,
        description="One short sentence, 7 words or fewer — what the task actually "
        "involves (e.g. 'Explain briefly why you're applying.'). Not a restatement "
        "of the requirement, not multiple sentences. Never mention verification/"
        "uncertainty here — the confidence badge already shows that.",
    )
    category: str = Field(
        description="Same category as the source requirement: essay, recommendation, "
        "testing, financial_aid, portfolio, interview, or major_specific."
    )
    deadline_iso: str | None = Field(
        default=None,
        description="Copy the source requirement's deadline, if it has one.",
    )
    estimated_minutes: int | None = Field(
        default=None,
        description="Realistic focused-work estimate — an essay draft might be "
        "60-120, requesting a recommendation 10-15, most admin tasks are short.",
    )
    required: bool = Field(
        description="Copy the source requirement's 'required' field exactly — "
        "used to weight priority, don't guess."
    )
    source_requirement_id: str = Field(
        description="The exact 'id' field from the matching requirement in "
        "REQUIREMENTS. This is what prevents duplicate tasks on re-runs — never "
        "invent one."
    )


class TaskPlan(BaseModel):
    tasks: list[ExtractedTask]


_TASK_PLANNING_INSTRUCTION = """You are the Task Planning Agent. Convert the
requirements below into concrete, actionable tasks a student can actually
do — not a restatement of each requirement.

COLLEGES (college_id -> name):
{college_id_to_name}

REQUIREMENTS:
{requirements_for_planning}

If REQUIREMENTS is empty, respond with an empty `tasks` list — either
nothing is tracked yet, or everything already has a task.

RULES:
- Generate exactly ONE task per actionable requirement — never split one
  requirement into multiple tasks (e.g. "2 recommendations required"
  becomes ONE task like "Request 2 teacher recommendations for Baylor",
  not two separate tasks). Finer-grained breakdown (which specific teacher
  for which subject) is a future agent's job, not yours.
- Actionable requirement types: essay, recommendation, testing,
  financial_aid, portfolio, interview, major_specific.
- Do NOT generate a task for a "deadline" requirement itself — a deadline
  is context attached to other tasks, not an action on its own.
- A requirement marked needs_verification still gets a normal task — do NOT
  mention the uncertainty in title or description; the Tasks page already
  shows a confidence badge for that, so repeating it in the 7-word
  description would just be redundant.
- source_requirement_id MUST be the exact "id" field from the matching
  requirement above.
- required: copy the source requirement's own "required" field exactly.
- `title` is a ~3-word label — college short name + 1-2 word type (e.g.
  "Texas A&M Main Essay", "Georgia Tech Personal Statement", "Texas A&M
  Short Answer 1") — not a sentence. Put any action or detail in
  `description` instead.
- `description` is ONE short sentence, 7 words or fewer, plain text (no
  markdown, no em dashes) — e.g. "Explain briefly why you're applying."

Respond with a single raw JSON object matching the TaskPlan schema."""


def _persist_tasks(callback_context) -> None:
    """Runs as an after_agent_callback for the same reason as
    requirements_agent's persist step: an output_schema agent can't also
    hold a write tool mid-turn."""
    user_id = callback_context.user_id
    plan = callback_context.state.get("planned_tasks") or {}
    items = plan.get("tasks", [])

    if items:
        tasks = [
            Task(
                title=item["title"],
                description=item.get("description"),
                college_id=item["college_id"],
                category=item.get("category"),
                deadline=item.get("deadline_iso") or None,
                estimated_minutes=item.get("estimated_minutes"),
                required=item.get("required", True),
                source_requirement_id=item["source_requirement_id"],
                created_by=TaskCreatedBy.AGENT,
                created_at=ft.now(),
            )
            for item in items
        ]
        ft.save_tasks(user_id, tasks)

    log_agent_run_complete(callback_context, f"Planned {len(items)} task(s).")


task_planning_agent = LlmAgent(
    model=config.critic_model,
    generate_content_config=llm_timeout_config(batched=True),
    name="task_planning_agent",
    description="Converts requirements into concrete, deduplicated tasks.",
    instruction=_TASK_PLANNING_INSTRUCTION,
    output_schema=TaskPlan,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key="planned_tasks",
    before_agent_callback=log_agent_run_start,
    after_agent_callback=_persist_tasks,
)

task_planning_pipeline = SequentialAgent(
    name="task_planning_pipeline",
    description="Loads all tracked colleges' requirements, then plans actionable tasks from them.",
    sub_agents=[TaskContextAgent(), task_planning_agent],
)
