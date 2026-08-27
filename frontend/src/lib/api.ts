import { v4 as uuidv4 } from "uuid";
import type {
  AgentRun,
  College,
  Conflict,
  EssayMatch,
  EssayPrompt,
  Recommendation,
  RecommendationStatus,
  RecommenderType,
  Requirement,
  ResearchSource,
  StudentMaterial,
  Task,
} from "./types";

/**
 * userId is a client-generated UUID persisted in localStorage — there is no
 * login yet (Google OAuth is an explicit future extension, see
 * .agents-cli-spec.md § Data Sources & Auth). This is the seam OAuth
 * replaces later; every backend route keys data off this id.
 */
const USER_ID_KEY = "collegentic.userId";

export function getUserId(): string {
  let id = localStorage.getItem(USER_ID_KEY);
  if (!id) {
    id = uuidv4();
    localStorage.setItem(USER_ID_KEY, id);
  }
  return id;
}

/** A "demo-" prefix on the client-generated id is the only signal Demo Mode
 * needs — no server round-trip required to know whether the current
 * session is a demo one. */
export function isDemoSession(): boolean {
  return getUserId().startsWith("demo-");
}

/** Starts a brand-new session under a fresh id — used both by "Try Demo
 * Mode" (prefixed, then seeded) and "Exit Demo Mode" (plain, unseeded, back
 * to a normal empty account). Never reuses an existing id: two people
 * trying Demo Mode must never see or perturb each other's session. */
function startNewSession(prefix: string): string {
  const id = `${prefix}${uuidv4()}`;
  localStorage.setItem(USER_ID_KEY, id);
  return id;
}

export function exitDemoMode(): void {
  startNewSession("");
}

/** Seeds a full fictional student profile under a fresh demo user id —
 * see app/demo_data.py for what gets created. */
export async function startDemoSession(): Promise<void> {
  startNewSession("demo-");
  await apiFetch("/api/demo/seed", { method: "POST" });
}

export interface HealthStatus {
  status: "ok" | "unreachable";
  service?: string;
}

/** Pings the backend's liveness endpoint (no model/DB calls involved). */
export async function checkHealth(): Promise<HealthStatus> {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return { status: "unreachable" };
    const data = await res.json();
    return { status: "ok", service: data.service };
  } catch {
    return { status: "unreachable" };
  }
}

class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "X-User-Id": getUserId(),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new ApiError(detail?.detail ?? res.statusText, res.status);
  }
  return res.json();
}

export function getColleges(): Promise<College[]> {
  return apiFetch("/api/colleges");
}

export function getCollege(collegeId: string): Promise<College> {
  return apiFetch(`/api/colleges/${collegeId}`);
}

/** Drops a college and everything derived from researching it (requirements,
 * essay prompts, research sources, tasks, essay matches, conflicts, and its
 * id out of any recommendation) — see app/api.py's delete_college. */
export function deleteCollege(collegeId: string): Promise<{ id: string }> {
  return apiFetch(`/api/colleges/${collegeId}`, { method: "DELETE" });
}

export function getRequirements(collegeIds?: string[]): Promise<Requirement[]> {
  const query = collegeIds?.length ? `?college_ids=${collegeIds.join(",")}` : "";
  return apiFetch(`/api/requirements${query}`);
}

export function getTasks(collegeId?: string): Promise<Task[]> {
  const query = collegeId ? `?college_id=${collegeId}` : "";
  return apiFetch(`/api/tasks${query}`);
}

/** Refreshes priority scores only (no LLM call) — see app/api.py's
 * recompute_priorities for why this exists alongside the full agent pipeline. */
export function recomputePriorities(): Promise<Task[]> {
  return apiFetch("/api/priorities/recompute", { method: "POST" });
}

/** Refreshes readiness scores only (no LLM call) — see app/api.py's
 * recompute_readiness. Call after updateRequirementProgress so the
 * Readiness page reflects a manual update immediately. */
export function recomputeReadiness(): Promise<College[]> {
  return apiFetch("/api/readiness/recompute", { method: "POST" });
}

/** My Progress' Test Scores toggle — a single account-wide answer, not per
 * college (see app/tools/scoring.py's compute_readiness_score). */
export function getTestScores(): Promise<{ submitted: boolean }> {
  return apiFetch("/api/test-scores");
}

export function updateTestScores(submitted: boolean): Promise<{ submitted: boolean }> {
  return apiFetch("/api/test-scores", {
    method: "PUT",
    body: JSON.stringify({ submitted }),
  });
}

/** My Progress' recommenders table — one recommender can cover several
 * colleges (or every one, via RECOMMENDATION_ALL_COLLEGES), so this is
 * account-wide, not scoped to a single college like Requirements. */
export function getRecommendations(): Promise<Recommendation[]> {
  return apiFetch("/api/recommendations");
}

interface RecommendationInput {
  recommenderName: string | null;
  recommenderType: RecommenderType;
  status: RecommendationStatus;
  collegeIds: string[];
}

export function createRecommendation(input: RecommendationInput): Promise<{ id: string }> {
  return apiFetch("/api/recommendations", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateRecommendation(
  id: string,
  input: RecommendationInput
): Promise<{ id: string }> {
  return apiFetch(`/api/recommendations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteRecommendation(id: string): Promise<{ id: string }> {
  return apiFetch(`/api/recommendations/${id}`, { method: "DELETE" });
}

/** Re-runs just the deterministic logo lookup for every already-tracked
 * college (no LLM call, no re-research) — see app/api.py's
 * refresh_college_logos. Lets a college researched under an earlier
 * version of the logo picker pick up a later fix without a full
 * re-research pass. */
export function refreshCollegeLogos(): Promise<College[]> {
  return apiFetch("/api/colleges/refresh-logos", { method: "POST" });
}

/** The one place a student directly asserts their own progress on a
 * requirement — see app/api.py's update_requirement_progress. Omitting
 * completionPercentage lets the backend derive it from `status`. */
export function updateRequirementProgress(
  collegeId: string,
  requirementId: string,
  status: Requirement["status"],
  completionPercentage?: number,
  studentNotes?: string | null
): Promise<void> {
  return apiFetch(`/api/colleges/${collegeId}/requirements/${requirementId}`, {
    method: "PATCH",
    body: JSON.stringify({
      status,
      ...(completionPercentage !== undefined
        ? { completionPercentage }
        : {}),
      ...(studentNotes !== undefined ? { studentNotes } : {}),
    }),
  });
}

export function getResearchSources(sourceIds: string[]): Promise<ResearchSource[]> {
  if (sourceIds.length === 0) return Promise.resolve([]);
  return apiFetch(`/api/research-sources?ids=${sourceIds.join(",")}`);
}

export function getConflicts(): Promise<Conflict[]> {
  return apiFetch("/api/conflicts");
}

export function acknowledgeConflict(conflictId: string): Promise<void> {
  return apiFetch(`/api/conflicts/${conflictId}/acknowledge`, { method: "POST" });
}

export function resolveConflict(conflictId: string): Promise<void> {
  return apiFetch(`/api/conflicts/${conflictId}/resolve`, { method: "POST" });
}

export function getMaterials(): Promise<StudentMaterial[]> {
  return apiFetch("/api/materials");
}

export interface CreateMaterialInput {
  title: string;
  type: StudentMaterial["type"];
  topic?: string;
  description?: string;
  partialText?: string;
  wordCount?: number;
}

/** The one place a StudentMaterial comes into existence — see app/api.py's
 * create_material. Collegentic never writes or edits essay text itself. */
export function createMaterial(input: CreateMaterialInput): Promise<StudentMaterial> {
  return apiFetch("/api/materials", { method: "POST", body: JSON.stringify(input) });
}

export function getEssayPrompts(collegeIds?: string[]): Promise<EssayPrompt[]> {
  const query = collegeIds?.length ? `?college_ids=${collegeIds.join(",")}` : "";
  return apiFetch(`/api/essay-prompts${query}`);
}

export function getEssayMatches(): Promise<EssayMatch[]> {
  return apiFetch("/api/essay-matches");
}

export function sendOrchestratorMessage(message: string): Promise<{ reply: string }> {
  return apiFetch("/api/orchestrator/messages", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function getAgentRuns(): Promise<AgentRun[]> {
  return apiFetch("/api/agent-runs");
}
