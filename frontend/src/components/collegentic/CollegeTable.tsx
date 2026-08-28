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
  /** Deletes a college and everything derived from researching it (see
   * api.ts's deleteCollege) and refetches — the row disappears on its own
   * once `colleges` no longer includes it. This component only owns the
   * confirm-before-delete step. */
  onDelete: (collegeId: string) => Promise<void>;
}

/** A cell whose value the agent is actively still looking for (see
 * College.researching) — a spinner instead of a plain "-", since an empty
 * cell on a row currently being researched isn't confirmed absent, just
 * not found yet. */
function LoadingCell() {
  return (
    <Loader2
      className="h-3.5 w-3.5 animate-spin text-muted-foreground"
      aria-label="Searching…"
    />
  );
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

function DeadlineCell({ iso, active }: { iso: string | null; active: boolean }) {
  // `active` means research_stage is sitting on exactly this field right
  // now (see College.research_stage) — never shown once a value has
  // actually landed, even if the backend hasn't advanced the stage marker
  // past this field yet.
  if (!iso) return active ? <LoadingCell /> : <span className="text-muted-foreground">-</span>;
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

/** Shown in the Requirements cell while College.requirementsTotal is set —
 * requirements are saved in small paced batches (see requirements_agent.py
 * Stage 5), so `done` climbs visibly toward `total` instead of the count
 * jumping straight from nothing to its final value. */
function RequirementsProgressCell({ done, total }: { done: number; total: number }) {
  const fraction = total > 0 ? done / total : 0;
  return (
    <div className="flex items-center gap-2" title={`${done} of ${total} requirements found`}>
      <span className="text-xs tabular-nums text-muted-foreground">
        {done}/{total}
      </span>
      <div className="h-1.5 w-16 shrink-0 rounded-full bg-secondary overflow-hidden">
        <div
          className="h-full rounded-full bg-navy transition-[width] duration-300 ease-out"
          style={{ width: `${Math.min(100, Math.max(4, fraction * 100))}%` }}
        />
      </div>
    </div>
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
    // Keyed by computedAt: readiness_agent.py now persists one college at a
    // time (paced, like the deadline/logo staging above), so the very first
    // score a college gets pops in on its own beat rather than silently
    // replacing "Not scored yet". A later recompute reusing the same
    // computedAt-ish moment won't replay it, which is fine — the arrival
    // itself is the moment worth animating.
    <div key={readiness.computedAt} className="flex items-center gap-2 animate-in fade-in zoom-in-90 duration-500" title={title}>
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
                    <span
                      key={college.logoUrl ?? "pending"}
                      className="relative animate-in fade-in zoom-in-75 duration-500"
                    >
                      <CollegeAvatar college={college} />
                      {!college.logoUrl && college.researchStage === "logo" && (
                        <Loader2
                          className="absolute -right-1 -bottom-1 h-3.5 w-3.5 animate-spin rounded-full bg-background text-muted-foreground"
                          aria-label="Searching for logo…"
                        />
                      )}
                    </span>
                    {college.name}
                  </Link>
                </td>
                <td className={BODY_CELL}>
                  <StatusBadge status={college.status} />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell
                    iso={college.deadlines.ea}
                    active={college.researchStage === "ea"}
                  />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell
                    iso={college.deadlines.ed}
                    active={college.researchStage === "ed"}
                  />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell
                    iso={college.deadlines.rd}
                    active={college.researchStage === "rd"}
                  />
                </td>
                <td className={BODY_CELL}>
                  <DeadlineCell
                    iso={college.deadlines.financialAid}
                    active={college.researchStage === "financialAid"}
                  />
                </td>
                <td className={BODY_CELL}>
                  {college.requirementsTotal != null ? (
                    <RequirementsProgressCell
                      done={requirements.length}
                      total={college.requirementsTotal}
                    />
                  ) : requirements.length === 0 ? (
                    college.researching ? (
                      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Researching…
                      </span>
                    ) : (
                      <span className="text-muted-foreground">Not researched yet</span>
                    )
                  ) : (
                    // Keyed by count: requirements_agent.py's Stage 5 now
                    // saves requirements in small paced batches (see
                    // RequirementsProgressCell above for while that's still
                    // in progress), so this pops in the moment the final
                    // batch lands instead of silently replacing the
                    // progress bar.
                    <span
                      key={requirements.length}
                      className="inline-flex items-center gap-1.5 animate-in fade-in zoom-in-90 duration-500"
                    >
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
