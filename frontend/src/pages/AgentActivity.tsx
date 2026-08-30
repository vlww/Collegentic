import { useCallback, useEffect, useState } from "react";
import { Bot } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { AgentRunStatusBadge } from "@/components/collegentic/AgentRunStatusBadge";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { getAgentRuns } from "@/lib/api";
import { groupByPipeline } from "@/lib/agentRuns";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { AgentRun } from "@/lib/types";

const POLL_INTERVAL_MS = 3000;

function humanizeAgentName(name: string): string {
  return name
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
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
      <PageHeader title="Agent Activity" />

      {runs !== null && groups.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Add a college to see activity here.
        </p>
      )}

      {groups.map((group) => (
        <SectionCard
          key={group.pipelineRunId}
          title={formatDateTime(group.startedAt)}
          icon={Bot}
          action={<AgentRunStatusBadge status={group.status} />}
          contentClassName=""
        >
          <div className="divide-y divide-border">
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
        </SectionCard>
      ))}
    </div>
  );
}
