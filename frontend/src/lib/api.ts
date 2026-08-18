import { v4 as uuidv4 } from "uuid";

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
