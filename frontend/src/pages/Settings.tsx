import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bot, Laptop, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { AgentRunStatusBadge } from "@/components/collegentic/AgentRunStatusBadge";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { exitDemoMode, getAgentRuns, getUserId, isDemoSession } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { AgentRun } from "@/lib/types";

const PREVIEW_COUNT = 5;

function humanizeAgentName(name: string): string {
  return name
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function Settings() {
  const navigate = useNavigate();
  const demo = isDemoSession();
  const [runs, setRuns] = useState<AgentRun[] | null>(null);

  useEffect(() => {
    getAgentRuns().then(setRuns);
  }, []);

  function handleExitDemo() {
    exitDemoMode();
    navigate("/onboarding", { replace: true });
  }

  const recentRuns = (runs ?? [])
    .slice()
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt))
    .slice(0, PREVIEW_COUNT);

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />

      {demo && (
        <Card className="border-orange/30">
          <CardContent className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="border-orange/30 bg-orange-tint text-orange">
                <Sparkles className="h-3 w-3" />
                Demo Mode
              </Badge>
              <p className="text-sm text-muted-foreground">
                You're viewing a pre-built fictional profile, nothing here is real.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={handleExitDemo}>
              Exit Demo Mode
            </Button>
          </CardContent>
        </Card>
      )}

      <SectionCard
        title="Agent Activity"
        icon={Bot}
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate("/agent-activity")}
            className="h-7 text-navy-foreground hover:bg-navy-foreground/10 hover:text-navy-foreground"
          >
            See all
            <ArrowRight className="h-4 w-4" />
          </Button>
        }
        contentClassName={recentRuns.length > 0 ? "" : "p-4"}
      >
        {runs !== null && recentRuns.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Add a college to see activity here.
          </p>
        )}
        {recentRuns.length > 0 && (
          <div className="divide-y divide-border">
            {recentRuns.map((run) => (
              <div key={run.id} className="p-3 space-y-1">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm font-medium text-foreground">
                    {humanizeAgentName(run.agentName)}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(run.startedAt)} ·{" "}
                      {formatDuration(run.startedAt, run.completedAt)}
                    </span>
                    <AgentRunStatusBadge status={run.status} />
                  </div>
                </div>
                {run.summary && (
                  <p className="text-sm text-muted-foreground">{run.summary}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Local Session" icon={Laptop}>
        <div className="text-sm text-muted-foreground space-y-1">
          <p>
            No login yet, Collegentic identifies you by a browser-local id.
          </p>
          <p className="font-mono text-xs break-all">{getUserId()}</p>
        </div>
      </SectionCard>
    </div>
  );
}
