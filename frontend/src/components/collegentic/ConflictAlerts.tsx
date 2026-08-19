import { useEffect, useState } from "react";
import { AlertTriangle, Check, Eye } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils";
import { acknowledgeConflict, getConflicts, resolveConflict } from "@/lib/api";
import type { Conflict, ConflictSeverity } from "@/lib/types";

const SEVERITY_CLASSES: Record<ConflictSeverity, string> = {
  high: "border-destructive/30 bg-destructive/10 text-destructive",
  medium: "border-warning/30 bg-warning/10 text-warning",
  low: "border-border bg-secondary text-secondary-foreground",
};

const TYPE_LABEL: Record<Conflict["type"], string> = {
  recommendation: "Recommendation",
  essay: "Essay",
  deadline: "Deadline",
  testing: "Testing",
  financialAid: "Financial Aid",
};

/**
 * Cross-college conflicts (.agents-cli-spec.md's Requirement Conflict
 * Agent, Milestone 10) have no dedicated sidebar page — they're
 * cross-cutting, so they surface here on the Dashboard, same reasoning as
 * Today's Priorities. Only open/acknowledged conflicts show; resolved ones
 * (student-resolved, or auto-resolved once the agent stops re-detecting
 * them) drop out entirely rather than cluttering the dashboard.
 */
export function ConflictAlerts({
  collegeName,
}: {
  collegeName: (collegeId: string) => string;
}) {
  const [conflicts, setConflicts] = useState<Conflict[] | null>(null);

  useEffect(() => {
    getConflicts().then(setConflicts);
  }, []);

  if (!conflicts) return null;
  const visible = conflicts.filter((c) => c.status !== "resolved");
  if (visible.length === 0) return null;

  async function handleAcknowledge(id: string) {
    await acknowledgeConflict(id);
    setConflicts((prev) =>
      prev ? prev.map((c) => (c.id === id ? { ...c, status: "acknowledged" } : c)) : prev
    );
  }

  async function handleResolve(id: string) {
    await resolveConflict(id);
    setConflicts((prev) => (prev ? prev.filter((c) => c.id !== id) : prev));
  }

  return (
    <Card className="border-warning/30">
      <CardContent>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3 flex items-center gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5 text-warning" />
          Cross-College Conflicts
        </h2>
        <div className="space-y-3">
          {visible.map((conflict) => (
            <div
              key={conflict.id}
              className="rounded-md border border-border p-3 space-y-2"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium uppercase tracking-wide">
                    {TYPE_LABEL[conflict.type]}
                  </span>
                  <span>·</span>
                  <span>{conflict.collegeIds.map(collegeName).join(", ")}</span>
                </div>
                <Badge variant="outline" className={cn(SEVERITY_CLASSES[conflict.severity])}>
                  {conflict.severity}
                </Badge>
              </div>
              <p className="text-sm text-foreground">{conflict.description}</p>
              <p className="text-sm text-muted-foreground">{conflict.recommendation}</p>
              <div className="flex items-center gap-2 pt-1">
                {conflict.status === "open" && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleAcknowledge(conflict.id)}
                  >
                    <Eye className="h-3.5 w-3.5" />
                    Acknowledge
                  </Button>
                )}
                <Button variant="outline" size="sm" onClick={() => handleResolve(conflict.id)}>
                  <Check className="h-3.5 w-3.5" />
                  Resolve
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
