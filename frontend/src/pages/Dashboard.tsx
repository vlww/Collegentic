import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";
import { CollegeTable } from "@/components/collegentic/CollegeTable";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getColleges, getRequirements } from "@/lib/api";
import type { College, Requirement } from "@/lib/types";
import { Link } from "react-router-dom";

export function Dashboard() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    getColleges()
      .then(async (result) => {
        setColleges(result);
        if (result.length > 0) {
          setRequirements(await getRequirements(result.map((c) => c.id)));
        }
      })
      .catch(() => setError(true));
  }, []);

  const requirementsByCollege: Record<string, Requirement[]> = {};
  for (const requirement of requirements) {
    (requirementsByCollege[requirement.collegeId] ??= []).push(requirement);
  }

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Today's Priorities and the full college application matrix — what's going on with all of your applications, at a glance."
      />

      <div className="mb-6">
        <ComingSoon milestone="Milestone 8 — Deadline & Priority Agent">
          Today's Priorities lands once the Priority Agent can score and explain what
          matters most today, not just list every open item.
        </ComingSoon>
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
          <CardContent className="space-y-3 text-center py-10">
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
        <CollegeTable colleges={colleges} requirementsByCollege={requirementsByCollege} />
      )}
    </div>
  );
}
