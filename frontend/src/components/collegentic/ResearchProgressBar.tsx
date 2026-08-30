import { Card, CardContent } from "@/components/ui/card";
import type { PipelineProgress } from "@/lib/types";

/**
 * Sits above the Colleges table while a research submission is in flight —
 * a plain "N of M colleges researched" count, so a judge watching this live
 * has a sense of overall progress instead of an indefinite spinner.
 *
 * Worded as a count, not "researching college N" — colleges are now
 * researched CONCURRENTLY (orchestrator_agent.py's PerCollegeResearchAnd
 * Extraction runs every requested college's research at once, each in its
 * own isolated session), so there's no single "current" college to name and
 * no one consistent per-college pace to extrapolate a time estimate from
 * (an earlier version of this component tried; it's gone along with
 * `PipelineProgress.startedAt`).
 */
export function ResearchProgressBar({ progress }: { progress: PipelineProgress }) {
  const { totalColleges, completedColleges } = progress;
  const allResearched = completedColleges >= totalColleges;
  const fraction = totalColleges > 0 ? completedColleges / totalColleges : 0;

  return (
    <Card className="py-3">
      <CardContent className="space-y-1.5">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            {allResearched
              ? "Finishing up, planning tasks and scoring readiness…"
              : `Researching ${totalColleges} college${totalColleges === 1 ? "" : "s"}…`}
          </span>
          <span className="text-xs text-muted-foreground">
            {allResearched ? "" : `${completedColleges} of ${totalColleges} done`}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-navy transition-[width] duration-500 ease-out"
            style={{ width: `${Math.min(100, Math.max(4, fraction * 100))}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
