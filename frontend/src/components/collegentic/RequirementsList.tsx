import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { SourcesDisclosure } from "./SourcesDisclosure";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { cn } from "@/utils";
import { formatDate } from "@/lib/format";
import { updateRequirementProgress } from "@/lib/api";
import type { Requirement, RequirementStatus } from "@/lib/types";

interface RequirementsListProps {
  requirements: Requirement[];
  /** Show which college each row belongs to — for the cross-college view. */
  collegeName?: (collegeId: string) => string;
  /** That college's own accent color (see CollegeAvatar's
   * collegeAccentColor) — paired with `collegeName` for the cross-college
   * view, same left-border-plus-tint treatment CollegeTable uses so a row
   * here reads as "this college" the same way a row there does. Omit for
   * a single-college view (CollegeDetail), where every row would just get
   * the same color anyway. */
  collegeAccent?: (collegeId: string) => string;
  /** Called after a student marks their own progress on a requirement — the
   * one place this data changes outside of an agent run (feeds the
   * Readiness Agent's formula). Omit to render the list read-only. */
  onProgressChange?: (requirementId: string, status: RequirementStatus) => void;
  /** Show only this many rows up front, with a "Show N more" toggle to
   * reveal the rest — omit to always show every row. */
  initialCount?: number;
  /** Trims each row for a space-constrained preview (Essays' side-by-side
   * Materials/Essay Progress columns, matched row-for-row against
   * "Your Materials") — clamps the description to two lines and drops the
   * notes input, which isn't essential for a glance. Default (unset) keeps
   * the full row CollegeDetail already relies on. */
  compact?: boolean;
  /** Extra classes merged onto each row's outer wrapper — e.g. a fixed
   * height so rows line up against a differently-shaped list next to them.
   * Only meaningful paired with `compact`. */
  rowClassName?: string;
}

const TYPE_LABEL: Record<string, string> = {
  essay: "Essay",
  recommendation: "Recommendation",
  testing: "Testing",
  deadline: "Deadline",
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

// Essays get their own narrower status set — "Revising" (same underlying
// NearlyComplete value as everywhere else, just labeled for what an essay
// draft actually needs at that stage) instead of "Nearly complete", and no
// "Verified" (that's a research-confidence idea, meaningless for a
// student's own essay).
const ESSAY_STATUS_LABEL: Partial<Record<RequirementStatus, string>> = {
  NotStarted: "Not started",
  Planning: "Planning",
  InProgress: "In progress",
  NearlyComplete: "Revising",
  Complete: "Complete",
  Submitted: "Submitted",
};

const ESSAY_STATUS_OPTIONS = Object.keys(ESSAY_STATUS_LABEL) as RequirementStatus[];

/** Placeholder text depends on the requirement type — a nudge toward what's
 * actually worth jotting down (an SAT/ACT score, which teacher was asked
 * and when), not a generic "notes" prompt. */
function notesPlaceholder(type: string): string {
  if (type === "testing") return "e.g. SAT 1480, ACT 33";
  if (type === "recommendation") return "e.g. Asked Ms. Chen 3/1, mailed 3/3";
  return "Add a note for yourself…";
}

function RequirementRow({
  requirement,
  collegeName,
  collegeAccent,
  onProgressChange,
  compact,
  rowClassName,
}: {
  requirement: Requirement;
  collegeName?: (collegeId: string) => string;
  collegeAccent?: (collegeId: string) => string;
  onProgressChange?: (requirementId: string, status: RequirementStatus) => void;
  compact?: boolean;
  rowClassName?: string;
}) {
  const [notes, setNotes] = useState(requirement.studentNotes ?? "");
  const [savingNotes, setSavingNotes] = useState(false);
  const accent = collegeAccent?.(requirement.collegeId);

  async function handleStatusChange(status: RequirementStatus) {
    await updateRequirementProgress(requirement.collegeId, requirement.id, status);
    onProgressChange?.(requirement.id, status);
  }

  async function handleNotesBlur() {
    const trimmed = notes.trim();
    if (trimmed === (requirement.studentNotes ?? "")) return;
    setSavingNotes(true);
    try {
      await updateRequirementProgress(
        requirement.collegeId,
        requirement.id,
        requirement.status,
        requirement.completionPercentage,
        trimmed || null
      );
    } finally {
      setSavingNotes(false);
    }
  }

  return (
    <div
      className={cn("p-4 space-y-2", accent && "school-tint border-l-4", rowClassName)}
      style={
        accent
          ? ({ borderLeftColor: accent, "--school-accent": accent } as React.CSSProperties)
          : undefined
      }
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
            <span className="font-medium uppercase tracking-wide shrink-0">
              {TYPE_LABEL[requirement.type] ?? requirement.type}
            </span>
            {collegeName && <span className="truncate">· {collegeName(requirement.collegeId)}</span>}
            {!requirement.required && <span className="shrink-0">· Optional</span>}
            {requirement.deadline && (
              <span className="shrink-0">· Due {formatDate(requirement.deadline)}</span>
            )}
          </div>
          <p className={cn("text-sm text-foreground", compact && "line-clamp-2")}>
            {requirement.description}
          </p>
        </div>
        <ConfidenceBadge
          confidence={requirement.confidence}
          needsVerification={requirement.needsVerification}
        />
      </div>
      <div className="flex items-center justify-between gap-4">
        <SourcesDisclosure sourceIds={requirement.sourceIds} />
        {onProgressChange && (
          <Select
            value={requirement.status}
            onValueChange={(value) => handleStatusChange(value as RequirementStatus)}
          >
            <SelectTrigger className="h-7 w-40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(requirement.type === "essay" ? ESSAY_STATUS_OPTIONS : STATUS_OPTIONS).map(
                (status) => (
                  <SelectItem key={status} value={status}>
                    {(requirement.type === "essay" ? ESSAY_STATUS_LABEL : STATUS_LABEL)[status]}
                  </SelectItem>
                )
              )}
            </SelectContent>
          </Select>
        )}
      </div>
      {onProgressChange && !compact && (
        <Input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={handleNotesBlur}
          placeholder={notesPlaceholder(requirement.type)}
          disabled={savingNotes}
          className="h-8 text-xs"
        />
      )}
    </div>
  );
}

export function RequirementsList({
  requirements,
  collegeName,
  collegeAccent,
  onProgressChange,
  initialCount,
  compact,
  rowClassName,
}: RequirementsListProps) {
  const [expanded, setExpanded] = useState(false);

  if (requirements.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No requirements researched yet.</p>;
  }

  const showToggle = initialCount !== undefined && requirements.length > initialCount;
  const visible =
    showToggle && !expanded ? requirements.slice(0, initialCount) : requirements;
  const remaining = requirements.length - (initialCount ?? 0);

  return (
    <div className="divide-y divide-border">
      {visible.map((requirement) => (
        <RequirementRow
          key={requirement.id}
          requirement={requirement}
          collegeName={collegeName}
          collegeAccent={collegeAccent}
          onProgressChange={onProgressChange}
          compact={compact}
          rowClassName={rowClassName}
        />
      ))}
      {showToggle && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex w-full items-center justify-center gap-1.5 px-4 py-2.5 text-xs font-medium text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
        >
          {expanded ? (
            <>
              Show fewer <ChevronUp className="h-3.5 w-3.5" />
            </>
          ) : (
            <>
              Show {remaining} more <ChevronDown className="h-3.5 w-3.5" />
            </>
          )}
        </button>
      )}
    </div>
  );
}
