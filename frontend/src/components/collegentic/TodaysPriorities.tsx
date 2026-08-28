import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckSquare, ChevronRight } from "lucide-react";
import { getTasks, recomputePriorities, type PrioritizedTask } from "@/lib/api";
import { formatDate } from "@/lib/format";

const TOP_N = 5;

/**
 * .agents-cli-spec.md § Today's Priorities: a thin, ranked list, not
 * every open task — 3-5 items, per the spec's own worked example.
 * Recomputes scores (deterministic, no LLM cost) on mount so the ranking
 * reflects today's actual deadline proximity, not whatever it was the last
 * time a college was researched. Deliberately terse per row — title and
 * deadline only, no score/explanation — this is a glance, not a report;
 * Tasks (the full page) is where the reasoning behind the ranking lives.
 * `task.title` is rendered as-is: both task sources (task_planning_agent.py
 * and demo_data.py) generate a short "College + what it is" label directly
 * — a client-side word cut would either leave it untouched (already short)
 * or mangle it into a sentence fragment, so there's nothing useful for the
 * frontend to trim.
 *
 * Only asks the backend to score/persist the top `TOP_N` tasks (recompute
 * used to touch every open task with a sequential Firestore write each,
 * which is what made switching onto the Dashboard take several seconds —
 * see app/api.py's recompute_priorities) so this loads fast enough not to
 * need its own loading state.
 */
export function TodaysPriorities() {
  const [tasks, setTasks] = useState<PrioritizedTask[] | null>(null);

  useEffect(() => {
    recomputePriorities(TOP_N)
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
    <div className="h-full rounded-lg border border-border shadow-sm overflow-hidden">
      <h2 className="bg-navy text-navy-foreground px-4 py-2.5 text-xs font-semibold uppercase tracking-wide flex items-center justify-between gap-1.5">
        <span className="flex items-center gap-1.5">
          <CheckSquare className="h-3.5 w-3.5 text-orange" />
          Today&rsquo;s Priorities
        </span>
        <Link
          to="/tasks"
          className="flex items-center text-navy-foreground/70 hover:text-navy-foreground"
          aria-label="View all tasks"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </h2>
      <ol className="divide-y divide-border">
        {top.map((task, index) => {
          const deadline = task.effectiveDeadline;
          return (
            <li key={task.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
              <div className="flex items-center gap-2.5 min-w-0">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-orange text-[11px] font-semibold text-orange-foreground">
                  {index + 1}
                </span>
                <span className="text-sm font-medium text-foreground truncate">
                  {task.title}
                </span>
              </div>
              <span className="text-xs text-muted-foreground shrink-0">
                Deadline: {formatDate(deadline)}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
