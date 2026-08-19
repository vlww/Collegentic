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

"""Typed Firestore document models — the single source of truth for the
schema described in .agents-cli-spec.md § Firestore Schema.

Every model's Python fields are snake_case; `alias_generator=to_camel` makes
the wire/Firestore representation camelCase, matching the frontend's TS
field naming exactly (e.g. `completion_percentage` <-> `completionPercentage`).

Write tools validate payloads against these schemas before writing to
Firestore — see .agents-cli-spec.md § Constraints ("agents cannot silently
write malformed or partial documents").
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class FirestoreModel(BaseModel):
    """Base for every Firestore document model: camelCase wire format,
    snake_case Python fields, and an optional `id` populated from the
    Firestore document id (never written back as a field)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str | None = None


# --- Enums (values match the string states in .agents-cli-spec.md exactly) --


class UserMode(StrEnum):
    LIVE = "live"
    DEMO = "demo"


class ApplicationType(StrEnum):
    COMMON_APP = "CommonApp"
    COALITION = "Coalition"
    DIRECT = "Direct"


class CollegeStatus(StrEnum):
    PLANNING = "Planning"
    IN_PROGRESS = "InProgress"
    READY = "Ready"
    SUBMITTED = "Submitted"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RequirementStatus(StrEnum):
    NOT_STARTED = "NotStarted"
    PLANNING = "Planning"
    IN_PROGRESS = "InProgress"
    NEARLY_COMPLETE = "NearlyComplete"
    COMPLETE = "Complete"
    SUBMITTED = "Submitted"
    VERIFIED = "Verified"


class MaterialType(StrEnum):
    COMMON_APP = "CommonApp"
    SUPPLEMENTAL = "Supplemental"
    ACTIVITY_DESCRIPTION = "ActivityDescription"
    AWARD = "Award"
    NOTE = "Note"
    IDEA = "Idea"


class MaterialStatus(StrEnum):
    NOT_STARTED = "NotStarted"
    IDEA = "Idea"
    DRAFTING = "Drafting"
    IN_PROGRESS = "InProgress"
    NEARLY_COMPLETE = "NearlyComplete"
    COMPLETE = "Complete"
    SUBMITTED = "Submitted"


class MatchRecommendation(StrEnum):
    ADAPT = "adapt"
    NEW = "new"


class TaskStatus(StrEnum):
    NOT_STARTED = "NotStarted"
    IN_PROGRESS = "InProgress"
    BLOCKED = "Blocked"
    DONE = "Done"


class TaskCreatedBy(StrEnum):
    AGENT = "agent"
    USER = "user"


class RecommenderType(StrEnum):
    STEM = "STEM"
    HUMANITIES = "Humanities"
    COUNSELOR = "Counselor"
    OTHER = "Other"


class RecommendationStatus(StrEnum):
    NOT_IDENTIFIED = "NotIdentified"
    PLANNED = "Planned"
    REQUESTED = "Requested"
    RECEIVED = "Received"
    VERIFIED = "Verified"


class ConflictType(StrEnum):
    RECOMMENDATION = "recommendation"
    ESSAY = "essay"
    DEADLINE = "deadline"
    TESTING = "testing"
    FINANCIAL_AID = "financialAid"


class ConflictSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConflictStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_FOR_USER = "waiting_for_user"
    FAILED = "failed"


class PendingActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# --- users/{userId} ----------------------------------------------------------


class UserProfile(FirestoreModel):
    mode: UserMode = UserMode.LIVE
    application_year: int
    created_at: datetime


# --- users/{userId}/colleges/{collegeId} -------------------------------------


class SchoolColors(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    primary: str | None = None
    secondary: str | None = None


class CollegeDeadlines(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    ea: datetime | None = None
    ed: datetime | None = None
    rd: datetime | None = None
    financial_aid: datetime | None = None


class ReadinessBreakdown(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    requirements: float = 0
    essays: float = 0
    recommendations: float = 0
    testing: float = 0
    deadline: float = 0


class Readiness(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    score: float = 0
    breakdown: ReadinessBreakdown = Field(default_factory=ReadinessBreakdown)
    explanation: str = ""
    computed_at: datetime | None = None


class College(FirestoreModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    application_type: ApplicationType | None = None
    school_colors: SchoolColors = Field(default_factory=SchoolColors)
    logo_url: str | None = None
    status: CollegeStatus = CollegeStatus.PLANNING
    deadlines: CollegeDeadlines = Field(default_factory=CollegeDeadlines)
    readiness: Readiness = Field(default_factory=Readiness)
    priority: float = 0
    last_researched_at: datetime | None = None


# --- users/{userId}/colleges/{collegeId}/requirements/{requirementId} -------


class Requirement(FirestoreModel):
    college_id: str
    type: str
    description: str
    required: bool = True
    status: RequirementStatus = RequirementStatus.NOT_STARTED
    completion_percentage: float = Field(default=0, ge=0, le=100)
    deadline: datetime | None = None
    dependencies: list[str] = Field(default_factory=list)
    category: str | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    needs_verification: bool = False
    source_ids: list[str] = Field(default_factory=list)


# --- users/{userId}/researchSources/{sourceId} -------------------------------


class ResearchSource(FirestoreModel):
    college_id: str
    url: str
    title: str
    date_researched: datetime
    official: bool
    confidence: ConfidenceLevel
    excerpt: str | None = None


# --- users/{userId}/materials/{materialId} -----------------------------------


class StudentMaterial(FirestoreModel):
    title: str
    type: MaterialType
    topic: str | None = None
    description: str | None = None
    partial_text: str | None = None
    completion_percentage: float = Field(default=0, ge=0, le=100)
    word_count: int | None = None
    themes: list[str] = Field(default_factory=list)
    status: MaterialStatus = MaterialStatus.NOT_STARTED
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- users/{userId}/colleges/{collegeId}/essayPrompts/{promptId} ------------


class EssayPrompt(FirestoreModel):
    college_id: str
    text: str
    word_limit: int | None = None
    required: bool = True
    category: str | None = None
    requirement_id: str | None = None


# --- users/{userId}/essayMatches/{matchId} -----------------------------------


class EssayMatch(FirestoreModel):
    prompt_id: str
    college_id: str
    material_id: str
    match_score: float = Field(ge=0, le=100)
    shared_themes: list[str] = Field(default_factory=list)
    recommendation: MatchRecommendation
    reasoning: str
    computed_at: datetime | None = None


# --- users/{userId}/tasks/{taskId} -------------------------------------------


class Task(FirestoreModel):
    title: str
    description: str | None = None
    college_id: str | None = None
    category: str | None = None
    deadline: datetime | None = None
    estimated_minutes: int | None = None
    # Denormalized from the source Requirement at creation time (not looked
    # up at scoring time) — Milestone 8's priority formula needs it and
    # scoring.py deliberately reads only Task fields, no joins.
    required: bool = True
    status: TaskStatus = TaskStatus.NOT_STARTED
    priority_score: float = 0
    priority_explanation: str = ""
    dependencies: list[str] = Field(default_factory=list)
    source_requirement_id: str | None = None
    created_by: TaskCreatedBy = TaskCreatedBy.AGENT
    created_at: datetime | None = None


# --- users/{userId}/recommendations/{recId} ----------------------------------


class Recommendation(FirestoreModel):
    recommender_name: str | None = None
    recommender_type: RecommenderType
    status: RecommendationStatus = RecommendationStatus.NOT_IDENTIFIED
    college_ids: list[str] = Field(default_factory=list)
    requested_at: datetime | None = None


# --- users/{userId}/conflicts/{conflictId} -----------------------------------


class Conflict(FirestoreModel):
    type: ConflictType
    college_ids: list[str]
    description: str
    recommendation: str
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    related_requirement_ids: list[str] = Field(default_factory=list)
    status: ConflictStatus = ConflictStatus.OPEN


# --- users/{userId}/agentRuns/{runId} -----------------------------------------


class AgentRun(FirestoreModel):
    pipeline_run_id: str
    agent_name: str
    status: AgentRunStatus = AgentRunStatus.RUNNING
    started_at: datetime
    completed_at: datetime | None = None
    summary: str | None = None
    related_college_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


# --- users/{userId}/pendingActions/{actionId} --------------------------------


class PendingAction(FirestoreModel):
    type: str
    description: str
    proposed_change: dict
    status: PendingActionStatus = PendingActionStatus.PENDING
    created_by_agent: str
    created_at: datetime
    resolved_at: datetime | None = None
