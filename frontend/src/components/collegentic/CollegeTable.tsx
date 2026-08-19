import { Link } from "react-router-dom";
import { AlertTriangle, ChevronRight } from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { formatDate, nextDeadline, daysUntil } from "@/lib/format";
import { cn } from "@/utils";
import type { College, Requirement } from "@/lib/types";

interface CollegeTableProps {
  colleges: College[];
  requirementsByCollege: Record<string, Requirement[]>;
}

/**
 * The core "what's going on with all of my applications?" view (spec § 6).
 * Progress / essays / recommendations / priority / readiness columns from
 * the original mock aren't shown yet — those agents don't exist until
 * Milestones 7-9; showing a fake number for them would violate "don't build
 * mock features that pretend to work." What's real today: status, the
 * nearest known deadline, and a requirement-verification count.
 */
export function CollegeTable({ colleges, requirementsByCollege }: CollegeTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-secondary/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="px-4 py-2.5 font-medium">College</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            <th className="px-4 py-2.5 font-medium">Next deadline</th>
            <th className="px-4 py-2.5 font-medium">Requirements</th>
            <th className="px-4 py-2.5 font-medium" />
          </tr>
        </thead>
        <tbody>
          {colleges.map((college) => {
            const requirements = requirementsByCollege[college.id] ?? [];
            const needsVerification = requirements.filter((r) => r.needsVerification).length;
            const deadline = nextDeadline(college.deadlines);
            const days = deadline ? daysUntil(deadline) : null;
            return (
              <tr key={college.id} className="border-b border-border last:border-0 hover:bg-secondary/30">
                <td className="px-4 py-3 font-medium text-foreground">
                  <Link to={`/colleges/${college.id}`} className="hover:underline">
                    {college.name}
                  </Link>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={college.status} />
                </td>
                <td className="px-4 py-3">
                  {deadline ? (
                    <span className={cn(days !== null && days <= 14 && "text-orange font-medium")}>
                      {formatDate(deadline)}
                      {days !== null && (
                        <span className="text-muted-foreground"> ({days >= 0 ? `${days}d` : "past"})</span>
                      )}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {requirements.length === 0 ? (
                    <span className="text-muted-foreground">Not researched yet</span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5">
                      {requirements.length} tracked
                      {needsVerification > 0 && (
                        <span className="inline-flex items-center gap-1 text-warning">
                          <AlertTriangle className="h-3.5 w-3.5" />
                          {needsVerification} to verify
                        </span>
                      )}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link to={`/colleges/${college.id}`}>
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
