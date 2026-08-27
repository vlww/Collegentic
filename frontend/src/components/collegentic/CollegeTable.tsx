import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ChevronRight, Loader2, Trash2 } from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { CollegeAvatar, collegeAccentColor, schoolAccentStyle } from "./CollegeAvatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { formatDateShort, daysUntil } from "@/lib/format";
import { cn } from "@/utils";
import type { College, Readiness, Requirement } from "@/lib/types";

interface CollegeTableProps {
  colleges: College[];
  requirementsByCollege: Record<string, Requirement[]>;
  /** True while a research pipeline is actively running (Colleges.tsx's
   * poll-while-in-flight state) — lets an unresearched row read as "still
   * working on it" rather than indistinguishable from a college nobody's
   * researched at all. */
  researching?: boolean;
  /** Deletes a college and everything derived from researching it (see
   * api.ts's deleteCollege) and refetches — the row disappears on its own
   * once `colleges` no longer includes it. This component only owns the
   * confirm-before-delete step. */
  onDelete: (collegeId: string) => Promise<void>;
}

/**
 * Trash icon -> a confirm dialog, rather than a single click or an inline
 * row affordance — a whole college's tracked requirements/tasks/essay
 * matches disappear with it (see ft.delete_college), so an accidental click
 * needs a deliberate second action, in its own modal, to actually lose that
 * data. Kept as its own popup (not inline in the row) so the row's own
 * layout doesn't have to make room for a confirm/cancel state.
 */
function DeleteCell({
  college,
  onDelete,
}: {
  college: College;
  onDelete: (collegeId: string) => Promise<void>;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [failed, setFailed] = useState(false);

  async function handleConfirm() {
    setDeleting(true);
    setFailed(false);
    try {
      await onDelete(college.id);
      // Row unmounts once the parent's `colleges` list no longer has it —
      // nothing left to reset here on success.
    } catch {
      setDeleting(false);
      setConfirmOpen(false);
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        title={`Remove ${college.name}`}
        aria-label={`Remove ${college.name}`}
        className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
      >
        <Trash2 className="h-4 w-4" />
      </button>
      {failed && <span className="text-xs text-destructive">Failed, try again</span>}
      <ConfirmDialog
        open={confirmOpen}
        message={`Are you sure you want to remove ${college.name} from your college list?`}
        loading={deleting}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

const HEADER_CELL = "px-3 py-2 font-medium whitespace-nowrap";
const BODY_CELL = "px-3 py-3 align-middle";

const TONE_TEXT = {
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
} as const;
const TONE_BG = {
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
} as const;
type Tone = keyof typeof TONE_TEXT;

function readinessTone(score: number): Tone {
  if (score >= 70) return "success";
  if (score >= 40) return "warning";
  return "destructive";
}

function DeadlineCell({ iso }: { iso: string | null }) {
  if (!iso) return <span className="text-muted-foreground">-</span>;
  const days = daysUntil(iso);
  const crunch = days >= 0 && days <= 14;
  return (
    // Keyed by the date itself: a deadline landing live (research writes
    // them one college at a time — see requirements_agent.py Stage 3)
    // pops in on its own beat instead of silently replacing the "-".
    <span
      key={iso}
      className={cn(
        "animate-in fade-in zoom-in-90 duration-500 inline-block",
        crunch && "text-orange font-semibold"
      )}
    >
      {formatDateShort(iso)}
    </span>
  );
}

function ReadinessCell({ readiness }: { readiness: Readiness }) {
  if (readiness.computedAt === null) {
    return <span className="text-muted-foreground">Not scored yet</span>;
  }
  const score = Math.round(readiness.score);
  const tone = readinessTone(score);
  const b = readiness.breakdown;
  const title = `Essays ${Math.round(b.essays)}% · Recommendations ${Math.round(
    b.recommendations
  )}% · Testing ${Math.round(b.testing)}% · Deadline pressure ${Math.round(b.deadline)}%`;
  return (
    <div className="flex items-center gap-2" title={title}>
      <span className={cn("font-medium tabular-nums", TONE_TEXT[tone])}>{score}%</span>
      <div className="h-1.5 w-14 shrink-0 rounded-full bg-secondary overflow-hidden">
        <div
          className={cn("h-full rounded-full", TONE_BG[tone])}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
    </div>
  );
}

/**
 * The core "what's going on with all of my applications?" view (spec § 6).
 * Essay/recommendation-specific columns from the original mock still aren't
 * shown — Essay Matching (Milestone 11) and Conflict Detection (Milestone
 * 10) don't exist yet, and showing a fake number for them would violate
 * "don't build mock features that pretend to work." Columns here are all
 * backed by fields the pipeline actually populates: status, each deadline
 * type individually (not just the nearest one), a requirement-verification
 * count, and (Milestone 9) readiness with its real category breakdown.
 * applicationType/priority aren't shown for the same reason — no agent or
 * form in this app ever sets them, so a column for them would always read
 * "-" and add noise instead of information. schoolColors/logoUrl (Milestone
 * 19) ARE real once research has run — used for the row's accent stripe and
 * the leading avatar, with a deterministic placeholder as fallback.
 */
export function CollegeTable({
  colleges,
  requirementsByCollege,
  researching,
  onDelete,
}: CollegeTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-navy text-navy-foreground text-left text-xs uppercase tracking-wide divide-x divide-navy-foreground/15">
            <th rowSpan={2} className={HEADER_CELL}>
              College
            </th>
            <th rowSpan={2} className={HEADER_CELL}>
              Status
            </th>
            <th colSpan={4} className={cn(HEADER_CELL, "text-center")}>
              Deadlines
            </th>
            <th rowSpan={2} className={HEADER_CELL}>
              Requirements
            </th>
            <th rowSpan={2} className={HEADER_CELL}>
              Readiness
            </th>
            <th rowSpan={2} className={HEADER_CELL} />
            <th rowSpan={2} className={HEADER_CELL} />
          </tr>
          <tr className="bg-navy text-navy-foreground text-left text-xs uppercase tracking-wide divide-x divide-navy-foreground/15 border-t border-navy-foreground/15">
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>EA</th>
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>ED</th>
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>RD</th>
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>Fin. Aid</th>
          </tr>
        </thead>
        <tbody>
          {colleges.map((college) => {
            const requirements = requirementsByCollege[college.id] ?? [];
            const needsVerification = requirements.filter((r) => r.needsVerification).length;
            return (
              <tr
                key={college.id}
                className="school-tint border-b border-border last:border-0 divide-x divide-border animate-in fade-in slide-in-from-left-1 duration-500"
                style={schoolAccentStyle(college)}
              >
                <td
                  className={cn(
                    BODY_CELL,
                    "font-medium text-foreground border-l-4 transition-colors duration-700"
                  )}
                  style={{ borderLeftColor: collegeAccentColor(college) }}
                >
                  <Link to={`/colleges/${college.id}`} className="flex items-center gap-2.5 hover:underline">
                    {/* Keyed by logoUrl: research finding a real logo (or a
                        color, above) swaps in live while this row is
                        already on screen — a step-by-step arrival worth a
                        beat of its own animation, not just a silent value
                        change. Unaffected rows never replay this. */}
                    <span key={college.logoUrl ?? "pending"} className="animate-in fade-in zoom-in-75 duration-500">
                      <CollegeAvatar college={college} />
                    </span>
                    {college.name}
                  </Link>
                </td>
                <td className={BODY_CELL}>
                  <StatusBadge status={college.status} />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell iso={college.deadlines.ea} />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell iso={college.deadlines.ed} />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell iso={college.deadlines.rd} />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell iso={college.deadlines.financialAid} />
                </td>
                <td className={BODY_CELL}>
                  {requirements.length === 0 ? (
                    researching ? (
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Researching…
                      </span>
                    ) : (
                      <span className="text-muted-foreground">Not researched yet</span>
                    )
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
                <td className={BODY_CELL}>
                  <ReadinessCell readiness={college.readiness} />
                </td>
                <td className={cn(BODY_CELL, "text-right")}>
                  <Link to={`/colleges/${college.id}`}>
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </Link>
                </td>
                <td className={cn(BODY_CELL, "text-right")}>
                  <DeleteCell college={college} onDelete={onDelete} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
