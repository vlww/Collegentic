import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { ReadinessCard } from "@/components/collegentic/ReadinessCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getColleges, recomputeReadiness } from "@/lib/api";
import type { College } from "@/lib/types";

export function Readiness() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    getColleges().then(setColleges);
  }, []);

  async function refresh() {
    setRefreshing(true);
    try {
      setColleges(await recomputeReadiness());
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Application Readiness"
          description="How ready you are for each college, and why."
        />
        <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
          <RefreshCw className={refreshing ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
          Refresh
        </Button>
      </div>

      {colleges !== null && colleges.length === 0 && (
        <p className="text-sm text-muted-foreground">
          You're not tracking any colleges yet.
        </p>
      )}

      {colleges !== null && colleges.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {colleges.map((college) => (
            <Card key={college.id} className="border-0 shadow-none p-0">
              <CardContent className="p-0 space-y-3">
                <Link
                  to={`/colleges/${college.id}`}
                  className="text-sm font-semibold text-foreground hover:underline"
                >
                  {college.name}
                </Link>
                <ReadinessCard college={college} readiness={college.readiness} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
