import { Card, CardContent } from "@/components/ui/card";
import type { PipelineProgress } from "@/lib/types";

/** Starting-point pace per college before this run has any real data of its
 * own — roughly what a single college's research+extraction pass actually
 * takes (see requirements_agent.py). Blended with the run's own observed
 * pace as colleges finish (see estimateRemainingMs) rather than replaced
 * outright — a plain "elapsed / completed" estimate swung wildly (9m -> 15m
 * -> back down) on small sample sizes, since one unusually fast or slow
 * college is the ENTIRE sample when completedColleges is 1 or 2. */
const BASELINE_SECONDS_PER_COLLEGE = 45;

/** Formats a millisecond duration as a short "~Xm Ys" / "~Xs" estimate —
 * intentionally coarse (rounded to the nearest 5s past a minute). */
function formatEta(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  if (totalSeconds < 60) return `~${Math.max(5, Math.round(totalSeconds / 5) * 5)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round((totalSeconds % 60) / 5) * 5;
  return seconds === 0 ? `~${minutes}m` : `~${minutes}m ${seconds}s`;
}

/** Remaining time, starting from `totalColleges * 45s` and blending in this
 * run's own observed pace as more colleges finish — the blend weight grows
 * with completedColleges (capped at 85%) so the estimate settles onto real
 * data instead of overreacting to one early college's duration. */
function estimateRemainingMs(progress: PipelineProgress): number {
  const { totalColleges, completedColleges, startedAt } = progress;
  const remainingColleges = Math.max(0, totalColleges - completedColleges);
  const baselinePerCollegeMs = BASELINE_SECONDS_PER_COLLEGE * 1000;
  if (remainingColleges === 0 || totalColleges === 0) return 0;
  if (completedColleges === 0) return baselinePerCollegeMs * remainingColleges;

  const elapsedMs = Date.now() - new Date(startedAt).getTime();
  const actualPerCollegeMs = elapsedMs / completedColleges;
  const weight = Math.min(0.85, completedColleges / totalColleges);
  const blendedPerCollegeMs =
    actualPerCollegeMs * weight + baselinePerCollegeMs * (1 - weight);
  return blendedPerCollegeMs * remainingColleges;
}

/**
 * Sits above the Colleges table while a research submission is in flight —
 * "researching college N of M" plus a rough time-remaining estimate, so a
 * judge watching this live has a sense of how much longer it'll take
 * instead of an indefinite spinner.
 */
export function ResearchProgressBar({ progress }: { progress: PipelineProgress }) {
  const { totalColleges, completedColleges } = progress;
  const allResearched = completedColleges >= totalColleges;
  const fraction = totalColleges > 0 ? completedColleges / totalColleges : 0;
  const etaLabel = allResearched ? null : formatEta(estimateRemainingMs(progress));

  return (
    <Card>
      <CardContent className="space-y-1.5 py-2.5">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">
            {allResearched
              ? "Finishing up — planning tasks and scoring readiness…"
              : `Researching college ${completedColleges + 1} of ${totalColleges}`}
          </span>
          <span className="text-xs text-muted-foreground">
            {etaLabel ? `${etaLabel} remaining` : ""}
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
