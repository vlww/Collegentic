import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

// Capped short of 100 — same reasoning as EssayProgressBar's own cap: the
// real "planning" -> "essays" stage transition always swaps this card out
// first in practice, but staying short of full means even a slow real
// response can't make the fake climb and the real transition collide.
const _CAP_PERCENT = 90;

/**
 * Shown right after ResearchProgressBar's own per-college count reaches
 * 100% — that bar has nothing left to report at that point (every college
 * IS researched), but task_planning_pipeline/priority_pipeline/readiness_
 * pipeline still run, sequentially, right after (see orchestrator_agent.py's
 * college_intake_pipeline and PipelineProgress.stage's docstring). Without
 * this, a student watched a full, frozen progress bar for however long that
 * remaining stretch took, with nothing telling them it wasn't finished yet.
 *
 * Only ever shown while `progress.stage === "planning"` (see Colleges.tsx) —
 * once that's done, EssayProgressBar takes over for the "essays"/"done"
 * stages that follow it.
 *
 * No fraction to show here — unlike per-college research, there's no
 * "N of M" count for a single batched task-planning/priority/readiness
 * call to report mid-flight, so this fakes a gradual climb client-side
 * instead, same idea as EssayProgressBar/CollegeTable's
 * FakeRequirementsProgressCell — a static bar that just sits there reads as
 * stuck, not as still working.
 */
export function TaskPlanningProgressBar() {
  const [percent, setPercent] = useState(12);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    function scheduleTick() {
      const delay = 900 + Math.random() * 2200;
      timeoutId = setTimeout(() => {
        if (cancelled) return;
        setPercent((p) => Math.min(_CAP_PERCENT, p + 3 + Math.random() * 6));
        scheduleTick();
      }, delay);
    }
    scheduleTick();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  return (
    <Card className="py-3">
      <CardContent className="space-y-1.5">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">Planning tasks and scoring readiness…</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-navy transition-[width] duration-700 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
