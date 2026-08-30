import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { CollegeTable } from "@/components/collegentic/CollegeTable";
import { TodaysPriorities } from "@/components/collegentic/TodaysPriorities";
import { ConflictAlerts } from "@/components/collegentic/ConflictAlerts";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { deleteCollege, getColleges, getRequirements, getTasks } from "@/lib/api";
import type { College, Requirement } from "@/lib/types";
import { Link } from "react-router-dom";

export function Dashboard() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [collegeIdsWithTasks, setCollegeIdsWithTasks] = useState<Set<string>>(new Set());
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    getColleges()
      .then(async (result) => {
        const [newRequirements, newTasks] = await Promise.all([
          result.length > 0 ? getRequirements(result.map((c) => c.id)) : Promise.resolve([]),
          getTasks(),
        ]);
        setColleges(result);
        setRequirements(newRequirements);
        setCollegeIdsWithTasks(
          new Set(newTasks.map((t) => t.collegeId).filter((id): id is string => id !== null))
        );
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(collegeId: string) {
    await deleteCollege(collegeId);
    load();
  }

  const requirementsByCollege: Record<string, Requirement[]> = {};
  for (const requirement of requirements) {
    (requirementsByCollege[requirement.collegeId] ??= []).push(requirement);
  }

  const collegeNameById = useMemo(
    () => Object.fromEntries((colleges ?? []).map((c) => [c.id, c.name])),
    [colleges]
  );

  return (
    <div>
      <PageHeader title="Dashboard" />

      <div className="mb-6 grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
        <TodaysPriorities />
        {colleges !== null && colleges.length > 0 && (
          <ConflictAlerts collegeName={(id) => collegeNameById[id] ?? id} />
        )}
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="text-sm text-destructive">
            Couldn't reach Collegentic's backend. Is it running?
          </CardContent>
        </Card>
      )}

      {!error && colleges === null && (
        <p className="text-sm text-muted-foreground">Loading your applications…</p>
      )}

      {!error && colleges !== null && colleges.length === 0 && (
        <Card>
          <CardContent className="space-y-3 text-center py-6">
            <p className="text-sm text-muted-foreground">
              You're not tracking any colleges yet.
            </p>
            <Button asChild>
              <Link to="/colleges">Add your first college</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {!error && colleges !== null && colleges.length > 0 && (
        <CollegeTable
          colleges={colleges}
          requirementsByCollege={requirementsByCollege}
          collegeIdsWithTasks={collegeIdsWithTasks}
          onDelete={handleDelete}
        />
      )}
    </div>
  );
}
