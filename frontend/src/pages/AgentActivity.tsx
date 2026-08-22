import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { AgentRunStatusBadge } from "@/components/collegentic/AgentRunStatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { getAgentRuns } from "@/lib/api";
import { formatDuration, formatTimestamp } from "@/lib/format";
import type { AgentRun, AgentRunStatus } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;

function humanizeAgentName(name: string): string {
  return name
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

interface PipelineGroup {
  pipelineRunId: string;
  runs: AgentRun[];
  startedAt: string;
  status: AgentRunStatus;
}

/** One card per pipeline execution (e.g. one "add these colleges"
 * submission) — every agent that ran within it, oldest first. Most recent
 * pipeline run first. */
function groupByPipeline(runs: AgentRun[]): PipelineGroup[] {
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

export function AgentActivity() {
  const [runs, setRuns] = useState<AgentRun[] | null>(null);

  const load = useCallback(() => {
    getAgentRuns().then(setRuns);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const groups = runs !== null ? groupByPipeline(runs) : [];
  const hasRunning = groups.some((g) => g.status === "running");

  // Poll only while something is actually in flight — a pipeline run is a
  // synchronous backend request, so another tab (or this one, mid-request)
  // can watch it progress live; once nothing is running there's nothing to
  // refresh until the next pipeline run starts.
  useEffect(() => {
    if (!hasRunning) return;
    const interval = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [hasRunning, load]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Activity"
        description="What Collegentic's agents are doing right now, and what they've done — running, completed, waiting for you, or failed."
      />

      {runs !== null && groups.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No agent activity yet — add a college to see the pipeline run here.
        </p>
      )}

      {groups.map((group) => (
        <Card key={group.pipelineRunId}>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {formatTimestamp(group.startedAt)}
              </p>
              <AgentRunStatusBadge status={group.status} />
            </div>
            <div className="divide-y divide-border rounded-lg border border-border">
              {group.runs.map((run) => (
                <div key={run.id} className="p-3 space-y-1">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm font-medium text-foreground">
                      {humanizeAgentName(run.agentName)}
                    </span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-muted-foreground">
                        {formatDuration(run.startedAt, run.completedAt)}
                      </span>
                      <AgentRunStatusBadge status={run.status} />
                    </div>
                  </div>
                  {run.summary && (
                    <p className="text-sm text-muted-foreground">{run.summary}</p>
                  )}
                  {run.errorMessage && (
                    <p className="text-sm text-destructive">{run.errorMessage}</p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
