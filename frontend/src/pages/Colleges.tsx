import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { AddCollegeForm } from "@/components/collegentic/AddCollegeForm";
import { CollegeTable } from "@/components/collegentic/CollegeTable";
import { Card, CardContent } from "@/components/ui/card";
import { getColleges, getRequirements } from "@/lib/api";
import type { College, Requirement } from "@/lib/types";

export function Colleges() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    getColleges()
      .then(async (result) => {
        setColleges(result);
        setRequirements(result.length > 0 ? await getRequirements(result.map((c) => c.id)) : []);
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const requirementsByCollege: Record<string, Requirement[]> = {};
  for (const requirement of requirements) {
    (requirementsByCollege[requirement.collegeId] ??= []).push(requirement);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Colleges"
        description="Every school you're tracking, with application type, deadlines, and school colors."
      />

      <AddCollegeForm onDone={load} />

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="text-sm text-destructive">
            Couldn't reach Collegentic's backend. Is it running?
          </CardContent>
        </Card>
      )}

      {!error && colleges === null && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      {!error && colleges !== null && colleges.length > 0 && (
        <CollegeTable colleges={colleges} requirementsByCollege={requirementsByCollege} />
      )}
    </div>
  );
}
