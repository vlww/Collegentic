import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { PriorityBadge } from "./PriorityBadge";
import { getTasks, recomputePriorities } from "@/lib/api";
import type { Task } from "@/lib/types";

const TOP_N = 5;

/**
 * .agents-cli-spec.md § Today's Priorities: a thin, ranked list, not
 * every open task — 3-5 items, per the spec's own worked example.
 * Recomputes scores (deterministic, no LLM cost) on mount so the ranking
 * reflects today's actual deadline proximity, not whatever it was the last
 * time a college was researched.
 */
export function TodaysPriorities() {
  const [tasks, setTasks] = useState<Task[] | null>(null);

  useEffect(() => {
    recomputePriorities()
      .then(setTasks)
      .catch(() => getTasks().then(setTasks));
  }, []);

  if (tasks === null) return null;

  const top = tasks
    .filter((t) => t.status !== "Done")
    .sort((a, b) => b.priorityScore - a.priorityScore)
    .slice(0, TOP_N);

  if (top.length === 0) return null;

  return (
    <Card>
      <CardContent>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">
          Today&rsquo;s Priorities
        </h2>
        <ol className="space-y-3">
          {top.map((task, index) => (
            <li key={task.id} className="flex items-start gap-3">
              <span className="text-sm font-semibold text-orange w-4 shrink-0">{index + 1}.</span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{task.title}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <PriorityBadge score={task.priorityScore} />
                  {task.priorityExplanation && (
                    <span className="text-xs text-muted-foreground truncate">
                      {task.priorityExplanation}
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
