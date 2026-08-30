import { useEffect, useState } from "react";
import { AlertTriangle, Check, Eye } from "lucide-react";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { Button } from "@/components/ui/button";
import { acknowledgeConflict, getConflicts, resolveConflict } from "@/lib/api";
import type { Conflict, ConflictSeverity } from "@/lib/types";

// Still used to rank which single conflict shows up front (see the
// docstring below) — just no longer surfaced as its own badge in the row.
const SEVERITY_RANK: Record<ConflictSeverity, number> = { high: 0, medium: 1, low: 2 };

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
 * Today's Priorities. Open/acknowledged conflicts show as before; resolved
 * ones (student-resolved, or auto-resolved once the agent stops
 * re-detecting them) drop out of the list. Unlike an earlier version of
 * this component, the panel itself always renders (loading, empty, and
 * populated all get their own state) rather than returning null whenever
 * there was nothing to show — that read as this section randomly vanishing
 * from the Dashboard instead of reporting "no conflicts."
 *
 * Sorted high-severity-first so the one always-visible conflict is the most
 * important one, not whatever order Firestore happened to return. Only the
 * first renders directly; any rest sit behind a `<details>` disclosure (same
 * pattern as SourcesDisclosure) so this panel can't grow taller than
 * TodaysPriorities next to it on the Dashboard — nothing is dropped, just
 * collapsed until the student expands it.
 */
export function ConflictAlerts({
  collegeName,
}: {
  collegeName: (collegeId: string) => string;
}) {
  const [conflicts, setConflicts] = useState<Conflict[] | null>(null);

  useEffect(() => {
    // Without `.catch`, a failed fetch left `conflicts` null forever and
    // this panel just silently never appeared again — indistinguishable
    // from "no conflicts detected" (also null-then-empty). Falling back to
    // [] here at least makes a real error self-heal on the next poll/visit
    // instead of the panel disappearing outright.
    getConflicts()
      .then(setConflicts)
      .catch(() => setConflicts([]));
  }, []);

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

  const visible = (conflicts ?? [])
    .filter((c) => c.status !== "resolved")
    .sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]);

  const [first, ...rest] = visible;

  function renderConflict(conflict: Conflict) {
    return (
      <div key={conflict.id} className="px-4 py-3 space-y-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
          <span className="font-medium uppercase tracking-wide shrink-0">
            {TYPE_LABEL[conflict.type]}
          </span>
          <span className="shrink-0">·</span>
          <span className="truncate">{conflict.collegeIds.map(collegeName).join(", ")}</span>
        </div>
        <p className="text-sm text-foreground">{conflict.description}</p>
        <div className="flex items-center gap-2 pt-1">
          {conflict.status === "open" && (
            <Button variant="outline" size="sm" onClick={() => handleAcknowledge(conflict.id)}>
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
    );
  }

  return (
    <SectionCard
      title="Cross-College Conflicts"
      icon={AlertTriangle}
      className="h-full"
      contentClassName={visible.length > 0 ? "" : "p-4"}
    >
      {conflicts === null && (
        <p className="text-sm text-muted-foreground">Checking for conflicts…</p>
      )}
      {conflicts !== null && visible.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No conflicts detected across your tracked colleges.
        </p>
      )}
      {first && (
        <div className="divide-y divide-border">
          {renderConflict(first)}
          {rest.length > 0 && (
            <details className="group">
              <summary className="cursor-pointer select-none px-4 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
                Show {rest.length} more conflict{rest.length > 1 ? "s" : ""}
              </summary>
              <div className="divide-y divide-border border-t border-border">
                {rest.map(renderConflict)}
              </div>
            </details>
          )}
        </div>
      )}
    </SectionCard>
  );
}
