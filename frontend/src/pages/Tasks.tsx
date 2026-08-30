import { useCallback, useEffect, useMemo, useState } from "react";
import { Clock } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { collegeAccentColor, schoolAccentStyle } from "@/components/collegentic/CollegeAvatar";
import { ConfidenceBadge } from "@/components/collegentic/ConfidenceBadge";
import { PriorityBadge } from "@/components/collegentic/PriorityBadge";
import { SourcesDisclosure } from "@/components/collegentic/SourcesDisclosure";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getColleges,
  getRequirements,
  getTasks,
  recomputeReadiness,
  type PrioritizedTask,
  updateRequirementProgress,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { College, Requirement, RequirementStatus } from "@/lib/types";

const ALL_COLLEGES = "__all__";
const ALL_CATEGORIES = "__all__";

const CATEGORY_LABEL: Record<string, string> = {
  essay: "Essay",
  recommendation: "Recommendation",
  testing: "Testing",
  financial_aid: "Financial Aid",
  portfolio: "Portfolio",
  interview: "Interview",
  major_specific: "Major-Specific",
};

const STATUS_LABEL: Record<RequirementStatus, string> = {
  NotStarted: "Not started",
  Planning: "Planning",
  InProgress: "In progress",
  NearlyComplete: "Nearly complete",
  Complete: "Complete",
  Submitted: "Submitted",
  Verified: "Verified",
};

const STATUS_OPTIONS = Object.keys(STATUS_LABEL) as RequirementStatus[];

export function Tasks() {
  const [colleges, setColleges] = useState<College[]>([]);
  const [tasks, setTasks] = useState<PrioritizedTask[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [collegeFilter, setCollegeFilter] = useState(ALL_COLLEGES);
  const [categoryFilter, setCategoryFilter] = useState(ALL_CATEGORIES);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(() => {
    getColleges().then(async (result) => {
      const [newTasks, newRequirements] = await Promise.all([
        getTasks(),
        result.length > 0 ? getRequirements(result.map((c) => c.id)) : Promise.resolve([]),
      ]);
      setColleges(result);
      setTasks(newTasks);
      setRequirements(newRequirements);
      setLoaded(true);
    });
  }, []);

  useEffect(load, [load]);

  // Research (and the task planning/priority/readiness stages after it)
  // keeps running on the backend well after this page's initial fetch — a
  // student sitting on the Tasks page waiting for them to appear would
  // otherwise see nothing update until they manually reload. Poll the same
  // way the Colleges page does while any tracked college is still mid-
  // research.
  useEffect(() => {
    if (!colleges.some((c) => c.researching)) return;
    const interval = setInterval(load, 700);
    return () => clearInterval(interval);
  }, [colleges, load]);

  async function handleStatusChange(requirement: Requirement, status: RequirementStatus) {
    await updateRequirementProgress(requirement.collegeId, requirement.id, status);
    setRequirements((prev) =>
      prev.map((r) => (r.id === requirement.id ? { ...r, status } : r))
    );
    // Feeds compute_readiness_score — without this, Application Readiness
    // stays stale until something else (My Progress, College Detail)
    // triggers a recompute.
    await recomputeReadiness();
  }

  const collegeNameById = useMemo(
    () => Object.fromEntries(colleges.map((c) => [c.id, c.name])),
    [colleges]
  );

  const collegeById = useMemo(
    () => Object.fromEntries(colleges.map((c) => [c.id, c])),
    [colleges]
  );

  const requirementById = useMemo(
    () => Object.fromEntries(requirements.map((r) => [r.id, r])),
    [requirements]
  );

  const categories = useMemo(
    () => Array.from(new Set(tasks.map((t) => t.category).filter((c): c is string => !!c))),
    [tasks]
  );

  const filtered = tasks
    .filter((t) => collegeFilter === ALL_COLLEGES || t.collegeId === collegeFilter)
    .filter((t) => categoryFilter === ALL_CATEGORIES || t.category === categoryFilter)
    .sort((a, b) => b.priorityScore - a.priorityScore);

  return (
    <div className="space-y-6">
      <PageHeader title="Tasks" />

      {(colleges.length > 0 || categories.length > 0 || filtered.length > 0) && (
        <div className="rounded-lg border border-border overflow-hidden">
          {(colleges.length > 0 || categories.length > 0) && (
            <div className="bg-navy px-4 py-5 flex flex-wrap gap-3">
              {colleges.length > 0 && (
                <Select value={collegeFilter} onValueChange={setCollegeFilter}>
                  <SelectTrigger className="w-64 bg-background">
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

              {categories.length > 0 && (
                <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                  <SelectTrigger className="w-64 bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_CATEGORIES}>All task types</SelectItem>
                    {categories.map((category) => (
                      <SelectItem key={category} value={category}>
                        {CATEGORY_LABEL[category] ?? category}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          {filtered.length > 0 && (
            <div className="divide-y divide-border">
              {filtered.map((task) => {
                const requirement = task.sourceRequirementId
                  ? requirementById[task.sourceRequirementId]
                  : undefined;
                const college = task.collegeId ? collegeById[task.collegeId] : undefined;
                return (
                  <div
                    key={task.id}
                    className={college ? "school-tint border-l-4 p-4 space-y-2" : "p-4 space-y-2"}
                    style={
                      college
                        ? { borderLeftColor: collegeAccentColor(college), ...schoolAccentStyle(college) }
                        : undefined
                    }
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 space-y-1.5">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          {task.category && (
                            <span className="font-medium uppercase tracking-wide">
                              {CATEGORY_LABEL[task.category] ?? task.category}
                            </span>
                          )}
                          {collegeFilter === ALL_COLLEGES && task.collegeId && (
                            <span>· {collegeNameById[task.collegeId] ?? task.collegeId}</span>
                          )}
                          {task.estimatedMinutes && (
                            <span className="inline-flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {task.estimatedMinutes} min
                            </span>
                          )}
                        </div>
                        <p className="text-sm font-medium text-foreground">{task.title}</p>
                        <p className="text-xs text-muted-foreground">
                          Deadline: {formatDate(task.effectiveDeadline)}
                        </p>
                        {task.description && (
                          <p className="text-sm text-muted-foreground truncate">
                            {task.description}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-col items-end gap-1.5 shrink-0">
                        <PriorityBadge score={task.priorityScore} />
                        {requirement && (
                          <ConfidenceBadge
                            confidence={requirement.confidence}
                            needsVerification={requirement.needsVerification}
                          />
                        )}
                      </div>
                    </div>
                    {requirement && (
                      <div className="flex items-center justify-between gap-4">
                        <SourcesDisclosure sourceIds={requirement.sourceIds} />
                        <Select
                          value={requirement.status}
                          onValueChange={(value) =>
                            handleStatusChange(requirement, value as RequirementStatus)
                          }
                        >
                          <SelectTrigger className="h-7 w-40 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {STATUS_OPTIONS.map((status) => (
                              <SelectItem key={status} value={status}>
                                {STATUS_LABEL[status]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {loaded && filtered.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {colleges.length === 0
            ? "Nothing yet, add a college to get started."
            : tasks.length === 0
              ? "No tasks yet, they'll appear once your colleges finish being researched."
              : "No tasks match this filter."}
        </p>
      )}
    </div>
  );
}
