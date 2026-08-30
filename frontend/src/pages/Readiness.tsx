import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { ReadinessCard } from "@/components/collegentic/ReadinessCard";
import { Card, CardContent } from "@/components/ui/card";
import { getTasks, recomputeReadiness } from "@/lib/api";
import type { College } from "@/lib/types";

// Deterministic and cheap (app/api.py's recompute_readiness — no LLM call),
// so it's fine to keep this fresh on a plain interval rather than needing a
// manual "Refresh" button: a requirement's status can change from another
// tab/page while this one sits open, and there's no in-flight pipeline
// signal here (unlike Colleges.tsx's polling) to key a smarter start/stop
// off of.
const POLL_INTERVAL_MS = 5000;

export function Readiness() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [collegeIdsWithTasks, setCollegeIdsWithTasks] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const [readinessColleges, tasks] = await Promise.all([
        recomputeReadiness(),
        getTasks(),
      ]);
      if (cancelled) return;
      setColleges(readinessColleges);
      setCollegeIdsWithTasks(
        new Set(tasks.map((t) => t.collegeId).filter((id): id is string => id !== null))
      );
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader title="Application Readiness" />

      {colleges !== null && colleges.length === 0 && (
        <p className="text-sm text-muted-foreground">
          You're not tracking any colleges yet.
        </p>
      )}

      {colleges !== null && colleges.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {colleges.map((college) => (
            <Card key={college.id} className="border-0 shadow-none bg-background p-0">
              <CardContent className="p-0 space-y-1.5">
                <Link
                  to={`/colleges/${college.id}`}
                  className="block text-center text-xl font-semibold text-foreground hover:underline"
                >
                  {college.name}
                </Link>
                <ReadinessCard
                  college={college}
                  readiness={college.readiness}
                  hasTasks={collegeIdsWithTasks.has(college.id)}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
