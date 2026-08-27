import type { AgentRun, AgentRunStatus } from "./types";

export interface PipelineGroup {
  pipelineRunId: string;
  runs: AgentRun[];
  startedAt: string;
  status: AgentRunStatus;
}

/** One group per pipeline execution (e.g. one "add these colleges"
 * submission) — every agent that ran within it, oldest first within the
 * group, most recent pipeline run first. Shared by the Agent Activity page
 * (full per-agent detail) and the Colleges page (just "did the latest run
 * fail?", to show/hide the Resume Research button). */
export function groupByPipeline(runs: AgentRun[]): PipelineGroup[] {
  const byId: Record<string, AgentRun[]> = {};
  for (const run of runs) {
    (byId[run.pipelineRunId] ??= []).push(run);
  }
  const groups = Object.values(byId).map((groupRuns): PipelineGroup => {
    const sorted = [...groupRuns].sort((a, b) => a.startedAt.localeCompare(b.startedAt));
    const status: AgentRunStatus = sorted.some((r) => r.status === "running")
      ? "running"
      : sorted.some((r) => r.status === "failed")
        ? "failed"
        : sorted.some((r) => r.status === "waiting_for_user")
          ? "waiting_for_user"
          : "completed";
    return {
      pipelineRunId: sorted[0].pipelineRunId,
      runs: sorted,
      startedAt: sorted[0].startedAt,
      status,
    };
  });
  return groups.sort((a, b) => b.startedAt.localeCompare(a.startedAt));
}

/** Status of the single most recently started pipeline run, or null if
 * nothing has run yet. */
export function latestPipelineStatus(runs: AgentRun[]): AgentRunStatus | null {
  return groupByPipeline(runs)[0]?.status ?? null;
}
