/** Mirrors agent/app/schemas.py — kept in sync by hand for now (no shared
 * codegen yet). Field names are camelCase to match the FirestoreModel
 * alias_generator, so these map 1:1 onto API JSON responses. */

export type ConfidenceLevel = "high" | "medium" | "low";

export interface SchoolColors {
  primary: string | null;
  secondary: string | null;
}

export interface CollegeDeadlines {
  ea: string | null;
  ed: string | null;
  rd: string | null;
  financialAid: string | null;
}

export interface ReadinessBreakdown {
  essays: number;
  recommendations: number;
  testing: number;
  deadline: number;
}

export interface Readiness {
  score: number;
  breakdown: ReadinessBreakdown;
  explanation: string;
  computedAt: string | null;
}

export type CollegeStatus = "Planning" | "InProgress" | "Ready" | "Submitted";

export interface College {
  id: string;
  name: string;
  aliases: string[];
  applicationType: "CommonApp" | "Coalition" | "Direct" | null;
  schoolColors: SchoolColors;
  logoUrl: string | null;
  status: CollegeStatus;
  deadlines: CollegeDeadlines;
  readiness: Readiness;
  priority: number;
  lastResearchedAt: string | null;
  /** True while this college's own per-college research pass is actively
   * running (see agent/app/schemas.py's College.researching) — an empty
   * cell on a row with this true is still being looked for, not confirmed
   * absent, so CollegeTable shows a loading spinner there instead of "-". */
  researching: boolean;
  /** Which one field is being actively looked for right now, while
   * researching is true — "logo", "ea", "ed", "rd", "financialAid",
   * "requirements", or null. See agent/app/schemas.py's
   * College.research_stage — this is what lets CollegeTable show exactly
   * ONE loading spinner at a time, in order, rather than every empty cell
   * spinning together. */
  researchStage: string | null;
  /** Set while requirements are being saved for this college — lets
   * CollegeTable render a "3 of 12 requirements" progress bar instead of a
   * growing, denominator-less count. Null before/after that window. */
  requirementsTotal: number | null;
}

/** Mirrors agent/app/schemas.py's PipelineProgress — polled while a
 * research submission is in flight to drive the Colleges page's progress
 * bar. `null` when no run has ever started for this account. */
export interface PipelineProgress {
  totalColleges: number;
  completedColleges: number;
  startedAt: string;
}

export type RequirementStatus =
  | "NotStarted"
  | "Planning"
  | "InProgress"
  | "NearlyComplete"
  | "Complete"
  | "Submitted"
  | "Verified";

export interface Requirement {
  id: string;
  collegeId: string;
  type: string;
  description: string;
  required: boolean;
  status: RequirementStatus;
  completionPercentage: number;
  deadline: string | null;
  dependencies: string[];
  category: string | null;
  confidence: ConfidenceLevel;
  needsVerification: boolean;
  sourceIds: string[];
  studentNotes: string | null;
}

export interface ResearchSource {
  id: string;
  collegeId: string;
  url: string;
  title: string;
  dateResearched: string;
  official: boolean;
  confidence: ConfidenceLevel;
  excerpt: string | null;
}

export type TaskStatus = "NotStarted" | "InProgress" | "Blocked" | "Done";

export interface Task {
  id: string;
  title: string;
  description: string | null;
  collegeId: string | null;
  category: string | null;
  deadline: string | null;
  estimatedMinutes: number | null;
  required: boolean;
  status: TaskStatus;
  priorityScore: number;
  priorityExplanation: string;
  dependencies: string[];
  sourceRequirementId: string | null;
  createdBy: "agent" | "user";
  createdAt: string | null;
}

export type ConflictType =
  | "recommendation"
  | "essay"
  | "deadline"
  | "testing"
  | "financialAid";

export type ConflictSeverity = "low" | "medium" | "high";

export type ConflictStatus = "open" | "acknowledged" | "resolved";

export interface Conflict {
  id: string;
  type: ConflictType;
  collegeIds: string[];
  description: string;
  recommendation: string;
  severity: ConflictSeverity;
  relatedRequirementIds: string[];
  status: ConflictStatus;
}

export type MaterialType =
  | "CommonApp"
  | "Supplemental"
  | "ActivityDescription"
  | "Award"
  | "Note"
  | "Idea";

export type MaterialStatus =
  | "NotStarted"
  | "Idea"
  | "Drafting"
  | "InProgress"
  | "NearlyComplete"
  | "Complete"
  | "Submitted";

export interface StudentMaterial {
  id: string;
  title: string;
  type: MaterialType;
  topic: string | null;
  description: string | null;
  partialText: string | null;
  completionPercentage: number;
  wordCount: number | null;
  themes: string[];
  status: MaterialStatus;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface EssayPrompt {
  id: string;
  collegeId: string;
  text: string;
  wordLimit: number | null;
  required: boolean;
  category: string | null;
  requirementId: string | null;
}

export type MatchRecommendation = "adapt" | "new";

export interface EssayMatch {
  id: string;
  promptId: string;
  collegeId: string;
  materialId: string;
  matchScore: number;
  sharedThemes: string[];
  recommendation: MatchRecommendation;
  reasoning: string;
  computedAt: string | null;
}

export type RecommenderType =
  | "TeacherSTEM"
  | "TeacherHumanities"
  | "Counselor"
  | "Employer"
  | "Other";

export type RecommendationStatus = "NotRequested" | "Requested" | "Submitted";

/** Sentinel inside `collegeIds` meaning "every college I'm tracking" — the
 * My Progress recommenders table's "All" option, resolved dynamically
 * against the current college list rather than a frozen snapshot. Mirrors
 * app/schemas.py's RECOMMENDATION_ALL_COLLEGES. */
export const RECOMMENDATION_ALL_COLLEGES = "ALL";

export interface Recommendation {
  id: string;
  recommenderName: string | null;
  recommenderType: RecommenderType;
  status: RecommendationStatus;
  collegeIds: string[];
  requestedAt: string | null;
}

export type AgentRunStatus = "running" | "completed" | "waiting_for_user" | "failed";

export interface AgentRun {
  id: string;
  pipelineRunId: string;
  agentName: string;
  status: AgentRunStatus;
  startedAt: string;
  completedAt: string | null;
  summary: string | null;
  relatedCollegeIds: string[];
  errorMessage: string | null;
}
