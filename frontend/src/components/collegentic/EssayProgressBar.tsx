import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { dismissEssaysBubble, isEssaysBubbleDismissed } from "@/lib/api";
import type { PipelineProgress } from "@/lib/types";

// Capped short of 100 — same reasoning as CollegeTable's
// FakeRequirementsProgressCell: real completion (progress.stage flipping to
// "done") always swaps this card out first in practice, but staying short
// of full means even a slow real response can't make the fake climb and the
// real "done" card collide/overshoot on screen.
const _CAP_PERCENT = 92;

/**
 * Shown once task_planning_pipeline/priority_pipeline/readiness_pipeline
 * finish (PipelineProgress.stage moves "planning" -> "essays") while
 * cross_college_analysis (essay_matching_pipeline structuring essay prompts
 * + conflict_pipeline) is still running — see orchestrator_agent.py's
 * college_intake_pipeline, where the "done" stage marker now sits AFTER
 * cross_college_analysis rather than before it, specifically so this stage
 * has something real to cover instead of the frontend claiming "done" while
 * essay prompts are still being structured underneath it.
 *
 * No fraction to show here either (same reasoning as
 * TaskPlanningProgressBar) — one batched LLM call, no "N of M" mid-flight
 * signal — so this fakes a gradual climb client-side, same idea as
 * CollegeTable's FakeRequirementsProgressCell, just as a filling bar instead
 * of a climbing count. Deliberately gradual/slow (irregular, multi-second
 * ticks) rather than an instant jump to some value — a bar that fills too
 * fast would land the student on "done" before the backend genuinely is.
 */
export function EssayProgressBar({ progress }: { progress: PipelineProgress }) {
  const [percent, setPercent] = useState(6);
  const percentRef = useRef(percent);
  percentRef.current = percent;
  const [dismissed, setDismissed] = useState(isEssaysBubbleDismissed);

  useEffect(() => {
    if (progress.stage !== "essays") return;
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
  }, [progress.stage]);

  if (progress.stage === "done") {
    if (dismissed) return null;
    return (
      <Card className="py-3 border-success/40">
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-sm font-medium text-success">
            <CheckCircle2 className="h-4 w-4" />
            Tasks planned and readiness scored.
          </p>
          <Button asChild size="sm" variant="outline">
            <Link
              to="/progress"
              onClick={() => {
                dismissEssaysBubble();
                setDismissed(true);
              }}
            >
              Add test scores, rec letters, &amp; essays
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="py-3">
      <CardContent className="space-y-1.5">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium">Inputting essays…</span>
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
