import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { PriorityBadge } from "@/components/collegentic/PriorityBadge";
import { Button } from "@/components/ui/button";
import { getTasks, recomputePriorities } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Task } from "@/lib/types";

export function Priorities() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    getTasks().then(setTasks);
  }, []);

  async function refresh() {
    setRefreshing(true);
    try {
      setTasks(await recomputePriorities());
    } finally {
      setRefreshing(false);
    }
  }

  const ranked = (tasks ?? [])
    .filter((t) => t.status !== "Done")
    .sort((a, b) => b.priorityScore - a.priorityScore);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Priorities"
          description="The full prioritized task list with plain-language explanations for each score."
        />
        <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
          <RefreshCw className={refreshing ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
          Refresh
        </Button>
      </div>

      {tasks !== null && ranked.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No open tasks yet — tasks are planned automatically once a college has been researched.
        </p>
      )}

      {ranked.length > 0 && (
        <div className="divide-y divide-border rounded-lg border border-border">
          {ranked.map((task, index) => (
            <div key={task.id} className="p-4 space-y-1.5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <span className="text-sm font-semibold text-orange w-5 shrink-0">
                    {index + 1}.
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{task.title}</p>
                    {task.priorityExplanation && (
                      <p className="text-sm text-muted-foreground mt-0.5">
                        {task.priorityExplanation}
                      </p>
                    )}
                    {task.deadline && (
                      <p className="text-xs text-muted-foreground mt-1">
                        Due {formatDate(task.deadline)}
                      </p>
                    )}
                  </div>
                </div>
                <PriorityBadge score={task.priorityScore} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
