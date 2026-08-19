import { useEffect, useMemo, useState } from "react";
import { Clock } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getColleges, getTasks } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { College, Task } from "@/lib/types";

const ALL_COLLEGES = "__all__";

const CATEGORY_LABEL: Record<string, string> = {
  essay: "Essay",
  recommendation: "Recommendation",
  testing: "Testing",
  financial_aid: "Financial Aid",
  portfolio: "Portfolio",
  interview: "Interview",
  major_specific: "Major-Specific",
};

export function Tasks() {
  const [colleges, setColleges] = useState<College[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [collegeFilter, setCollegeFilter] = useState(ALL_COLLEGES);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getColleges().then(async (result) => {
      setColleges(result);
      setTasks(await getTasks());
      setLoaded(true);
    });
  }, []);

  const collegeNameById = useMemo(
    () => Object.fromEntries(colleges.map((c) => [c.id, c.name])),
    [colleges]
  );

  const filtered =
    collegeFilter === ALL_COLLEGES ? tasks : tasks.filter((t) => t.collegeId === collegeFilter);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tasks"
        description="Every generated task, filterable by college — planned from your requirements, deduplicated automatically."
      />

      {colleges.length > 0 && (
        <Select value={collegeFilter} onValueChange={setCollegeFilter}>
          <SelectTrigger className="w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_COLLEGES}>All colleges</SelectItem>
            {colleges.map((college) => (
              <SelectItem key={college.id} value={college.id}>
                {college.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {loaded && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No tasks yet — tasks are planned automatically once a college has been researched.
        </p>
      )}

      {filtered.length > 0 && (
        <div className="divide-y divide-border rounded-lg border border-border">
          {filtered.map((task) => (
            <div key={task.id} className="p-4 space-y-1.5">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                {task.category && (
                  <span className="font-medium uppercase tracking-wide">
                    {CATEGORY_LABEL[task.category] ?? task.category}
                  </span>
                )}
                {collegeFilter === ALL_COLLEGES && task.collegeId && (
                  <span>· {collegeNameById[task.collegeId] ?? task.collegeId}</span>
                )}
                {task.deadline && <span>· Due {formatDate(task.deadline)}</span>}
                {task.estimatedMinutes && (
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {task.estimatedMinutes} min
                  </span>
                )}
              </div>
              <p className="text-sm font-medium text-foreground">{task.title}</p>
              {task.description && (
                <p className="text-sm text-muted-foreground">{task.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
