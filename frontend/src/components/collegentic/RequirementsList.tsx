import { useState } from "react";
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
import { formatDate } from "@/lib/format";
import { updateRequirementProgress } from "@/lib/api";
import type { Requirement, RequirementStatus } from "@/lib/types";

interface RequirementsListProps {
  requirements: Requirement[];
  /** Show which college each row belongs to — for the cross-college view. */
  collegeName?: (collegeId: string) => string;
  /** Called after a student marks their own progress on a requirement — the
   * one place this data changes outside of an agent run (feeds the
   * Readiness Agent's formula). Omit to render the list read-only. */
  onProgressChange?: (requirementId: string, status: RequirementStatus) => void;
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
  onProgressChange,
}: {
  requirement: Requirement;
  collegeName?: (collegeId: string) => string;
  onProgressChange?: (requirementId: string, status: RequirementStatus) => void;
}) {
  const [notes, setNotes] = useState(requirement.studentNotes ?? "");
  const [savingNotes, setSavingNotes] = useState(false);

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
    <div className="p-4 space-y-2">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-medium uppercase tracking-wide">
              {TYPE_LABEL[requirement.type] ?? requirement.type}
            </span>
            {collegeName && <span>· {collegeName(requirement.collegeId)}</span>}
            {!requirement.required && <span>· Optional</span>}
            {requirement.deadline && <span>· Due {formatDate(requirement.deadline)}</span>}
          </div>
          <p className="text-sm text-foreground">{requirement.description}</p>
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
      {onProgressChange && (
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
  onProgressChange,
}: RequirementsListProps) {
  if (requirements.length === 0) {
    return <p className="text-sm text-muted-foreground">No requirements researched yet.</p>;
  }

  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {requirements.map((requirement) => (
        <RequirementRow
          key={requirement.id}
          requirement={requirement}
          collegeName={collegeName}
          onProgressChange={onProgressChange}
        />
      ))}
    </div>
  );
}
