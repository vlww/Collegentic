import { ConfidenceBadge } from "./ConfidenceBadge";
import { SourcesDisclosure } from "./SourcesDisclosure";
import { formatDate } from "@/lib/format";
import type { Requirement } from "@/lib/types";

interface RequirementsListProps {
  requirements: Requirement[];
  /** Show which college each row belongs to — for the cross-college view. */
  collegeName?: (collegeId: string) => string;
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

export function RequirementsList({ requirements, collegeName }: RequirementsListProps) {
  if (requirements.length === 0) {
    return <p className="text-sm text-muted-foreground">No requirements researched yet.</p>;
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
          <SourcesDisclosure sourceIds={requirement.sourceIds} />
        </div>
      ))}
    </div>
  );
}
