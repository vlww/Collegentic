import { Badge } from "@/components/ui/badge";
import { cn } from "@/utils";

/**
 * score is 0-100 from app/tools/scoring.py's compute_priority_score —
 * thresholds here are purely a display convenience, not part of the
 * formula. Calibrated against the formula's actual achievable range: with
 * weights deadline=0.40/workload=0.20/importance=0.15/dependency=0.15/
 * progress=0.10, a realistic active task scores roughly 16 (distant,
 * optional, no workload) to ~95 (overdue + required + heavy + blocked) —
 * 70 as a "High" cutoff was checked and almost never reachable even for
 * genuinely urgent tasks (see test_scoring.py), so it sat there silently
 * making every task read as Medium/Low. 55 is the point a close deadline
 * (~90%+ urgency) plus "required" alone crosses, which is what a student
 * would actually call urgent.
 */
export function priorityLevel(score: number): "High" | "Medium" | "Low" {
  if (score >= 55) return "High";
  if (score >= 30) return "Medium";
  return "Low";
}

const CLASSES: Record<ReturnType<typeof priorityLevel>, string> = {
  High: "border-destructive/30 bg-destructive/10 text-destructive",
  Medium: "border-warning/30 bg-warning/10 text-warning",
  Low: "border-border bg-secondary text-secondary-foreground",
};

export function PriorityBadge({ score }: { score: number }) {
  const level = priorityLevel(score);
  return (
    <Badge variant="outline" className={cn(CLASSES[level])}>
      {level} priority
    </Badge>
  );
}
