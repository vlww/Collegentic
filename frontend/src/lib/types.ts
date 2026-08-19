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
  requirements: number;
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
