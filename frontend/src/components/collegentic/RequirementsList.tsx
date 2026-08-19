import { ConfidenceBadge } from "./ConfidenceBadge";
import { SourcesDisclosure } from "./SourcesDisclosure";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

export function RequirementsList({
  requirements,
  collegeName,
  onProgressChange,
}: RequirementsListProps) {
  if (requirements.length === 0) {
    return <p className="text-sm text-muted-foreground">No requirements researched yet.</p>;
  }

  async function handleStatusChange(requirement: Requirement, status: RequirementStatus) {
    await updateRequirementProgress(requirement.collegeId, requirement.id, status);
    onProgressChange?.(requirement.id, status);
  }

  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {requirements.map((requirement) => (
        <div key={requirement.id} className="p-4 space-y-2">
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
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
