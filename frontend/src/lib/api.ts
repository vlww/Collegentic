import { v4 as uuidv4 } from "uuid";
import type {
  AgentRun,
  College,
  Conflict,
  EssayMatch,
  EssayPrompt,
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

/** The one place a student directly asserts their own progress on a
 * requirement — see app/api.py's update_requirement_progress. Omitting
 * completionPercentage lets the backend derive it from `status`. */
export function updateRequirementProgress(
  collegeId: string,
  requirementId: string,
  status: Requirement["status"],
  completionPercentage?: number
): Promise<void> {
  return apiFetch(`/api/colleges/${collegeId}/requirements/${requirementId}`, {
    method: "PATCH",
    body: JSON.stringify({
      status,
      ...(completionPercentage !== undefined
        ? { completionPercentage }
        : {}),
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
