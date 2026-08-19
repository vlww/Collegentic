import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/utils";
import type { Readiness } from "@/lib/types";

const BREAKDOWN_LABEL: Record<keyof Readiness["breakdown"], string> = {
  requirements: "Other requirements",
  essays: "Essays",
  recommendations: "Recommendations",
  testing: "Testing",
  deadline: "Deadline readiness",
};

function scoreColor(score: number): string {
  if (score >= 70) return "text-success";
  if (score >= 40) return "text-warning";
  return "text-destructive";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-success";
  if (score >= 40) return "bg-warning";
  return "bg-destructive";
}

/** Per-college readiness display — .agents-cli-spec.md § Application
 * Readiness Agent's own worked example ("MIT — 82% Ready — Requirements:
 * 95%, Essays: 70%, ..."). Shared by the Readiness page (every college) and
 * CollegeDetail (one college), so the breakdown reads identically in both
 * places. */
export function ReadinessCard({ collegeName, readiness }: { collegeName: string; readiness: Readiness }) {
  if (readiness.computedAt === null) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">
          Not scored yet — readiness is computed once {collegeName} has been researched.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex items-baseline gap-2">
          <span className={cn("text-3xl font-semibold tabular-nums", scoreColor(readiness.score))}>
            {Math.round(readiness.score)}%
          </span>
          <span className="text-sm text-muted-foreground">ready</span>
        </div>

        <div className="space-y-2">
          {(Object.keys(BREAKDOWN_LABEL) as (keyof Readiness["breakdown"])[]).map((key) => {
            const value = readiness.breakdown[key];
            return (
              <div key={key} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{BREAKDOWN_LABEL[key]}</span>
                  <span className="tabular-nums text-foreground">{Math.round(value)}%</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-secondary">
                  <div
                    className={cn("h-1.5 rounded-full", barColor(value))}
                    style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {readiness.explanation && (
          <p className="text-sm text-muted-foreground">{readiness.explanation}</p>
        )}
      </CardContent>
    </Card>
  );
}
