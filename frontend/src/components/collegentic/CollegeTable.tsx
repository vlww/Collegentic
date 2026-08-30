import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronRight,
  Loader2,
  Trash2,
} from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { CollegeAvatar, collegeAccentColor, schoolAccentStyle } from "./CollegeAvatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { formatDateShort, daysUntil } from "@/lib/format";
import { cn } from "@/utils";
import type { College, CollegeStatus, Readiness, Requirement } from "@/lib/types";

interface CollegeTableProps {
  colleges: College[];
  requirementsByCollege: Record<string, Requirement[]>;
  /** Which colleges have at least one planned task — gates the Readiness
   * column (see ReadinessCell) so a score never appears before Tasks does. */
  collegeIdsWithTasks: Set<string>;
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

type SortKey = "name" | "status" | "ea" | "ed" | "rd" | "financialAid";
type SortDirection = "asc" | "desc";

// The order applications actually move through — .agents-cli-spec.md's own
// status lifecycle — not alphabetical, so "sort by status" reads as "how far
// along," the thing a student actually wants to scan for.
const STATUS_ORDER: Record<CollegeStatus, number> = {
  Planning: 0,
  InProgress: 1,
  Ready: 2,
  Submitted: 3,
};

function compareDeadline(a: string | null, b: string | null, dir: SortDirection): number {
  // Colleges with no deadline on file yet sort to the bottom regardless of
  // direction — flipping to descending should surface the soonest-crunch
  // deadlines first, not bury them under a pile of unresearched "-" rows.
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const delta = new Date(a).getTime() - new Date(b).getTime();
  return dir === "asc" ? delta : -delta;
}

function SortableHeader({
  label,
  active,
  direction,
  onClick,
}: {
  label: string;
  active: boolean;
  direction: SortDirection;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 hover:text-navy-foreground/80"
    >
      {label}
      {active ? (
        direction === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-40" />
      )}
    </button>
  );
}

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
    // them one field at a time — see requirements_agent.py's
    // branding_and_deadlines_agent) pops in on its own beat instead of
    // silently replacing the "-".
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

// Fake count never reaches this — real data always swaps in first in
// practice, but capping short of it means even a slow real response can't
// make the fake count and the real one collide/overshoot on screen. A
// random cap per college (not a single fixed number) — every college
// stalling at exactly the same "11 tracked" is itself a tell that it's
// fake, same reasoning as the irregular tick delay below.
const _FAKE_REQUIREMENTS_CAP_MIN = 7;
const _FAKE_REQUIREMENTS_CAP_MAX = 12;

// Module-level, keyed by college id, so a college's fake progress survives
// navigating away and back — CollegeTable (and this cell) fully remounts on
// that round trip, which would otherwise reset React state back to count=1
// and visibly restart the climb, itself another tell that it's fake. A
// plain module-level Map (not localStorage/backend state) is enough since
// it only needs to survive for the current tab's session; it naturally goes
// away on reload as the college transitions to its real, final count.
const _fakeRequirementsProgress = new Map<string, { count: number; cap: number }>();

/**
 * Shown in the Requirements cell once deadlines are done and
 * research_stage moves to "requirements" — the last, and by far the
 * slowest, part of a college's research (requirements_agent.py's one big
 * structured-extraction LLM call). Unlike color/logo/deadlines, the
 * backend genuinely has no incremental signal to report here: every
 * requirement becomes known at the same instant, in one response, so
 * there's no real "3 of 12 found" count to show while it's running.
 *
 * Rather than sit on a static spinner for that whole stretch (previously:
 * "Researching…" the entire time, then the real count appearing all at
 * once), this fakes a plausible "still finding things" climb entirely
 * client-side, in the same "N tracked" shape the real final label uses —
 * a count from 1 up to this college's own random cap, occasionally
 * skipping a number, with irregular pauses between ticks (never a
 * smooth/linear climb, which reads as fake in a different way). The count
 * is fake — nobody has actually found "6 requirements" at that moment —
 * but reads far more like real incremental progress than an unlabeled bar
 * alone. Replaced outright, the instant real data arrives, by the actual
 * "N tracked" count one tier up in CollegeTable's render — this component
 * never learns or shows a real number itself.
 */
function FakeRequirementsProgressCell({ collegeId }: { collegeId: string }) {
  const [, forceRender] = useState(0);
  const stateRef = useRef<{ count: number; cap: number } | null>(null);
  if (!stateRef.current) {
    stateRef.current = _fakeRequirementsProgress.get(collegeId) ?? {
      count: 1,
      cap:
        _FAKE_REQUIREMENTS_CAP_MIN +
        Math.floor(Math.random() * (_FAKE_REQUIREMENTS_CAP_MAX - _FAKE_REQUIREMENTS_CAP_MIN + 1)),
    };
    _fakeRequirementsProgress.set(collegeId, stateRef.current);
  }

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    function scheduleTick() {
      // Irregular delay, not a fixed interval — a metronome-steady climb
      // reads as an animation, not as sporadic real discovery.
      const delay = 900 + Math.random() * 1900;
      timeoutId = setTimeout(() => {
        if (cancelled) return;
        const state = stateRef.current!;
        if (state.count < state.cap) {
          // Skip a number sometimes (+2) rather than always +1 — a
          // perfectly steady 1,2,3,4... climb reads as an animation, not
          // as things being found one at a time.
          const step = Math.random() < 0.4 ? 2 : 1;
          state.count = Math.min(state.cap, state.count + step);
          forceRender((n) => n + 1);
        }
        scheduleTick();
      }, delay);
    }
    scheduleTick();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  const { count, cap } = stateRef.current;
  // +2 headroom so even the capped count never visually fills the bar —
  // same "must never look finished before the real count swaps in" reason
  // the count itself is capped short of any plausible real total.
  const fraction = count / (cap + 2);

  return (
    <div className="flex items-center gap-2" title="Finding requirements…">
      <span className="text-xs tabular-nums text-muted-foreground">{count} tracked</span>
      <div className="h-1.5 w-16 shrink-0 rounded-full bg-secondary overflow-hidden">
        <div
          className="h-full rounded-full bg-navy transition-[width] duration-700 ease-out"
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
    </div>
  );
}

function ReadinessCell({ readiness, hasTasks }: { readiness: Readiness; hasTasks: boolean }) {
  // Withhold the score until this college has planned tasks — see
  // ReadinessCard's matching guard for why.
  if (readiness.computedAt === null || !hasTasks) {
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
  collegeIdsWithTasks,
  onDelete,
}: CollegeTableProps) {
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  const sortedColleges = useMemo(() => {
    if (sortKey === null) return colleges;
    const dir = sortDirection === "asc" ? 1 : -1;
    return [...colleges].sort((a, b) => {
      switch (sortKey) {
        case "name":
          return dir * a.name.localeCompare(b.name);
        case "status":
          return dir * (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]);
        case "ea":
          return compareDeadline(a.deadlines.ea, b.deadlines.ea, sortDirection);
        case "ed":
          return compareDeadline(a.deadlines.ed, b.deadlines.ed, sortDirection);
        case "rd":
          return compareDeadline(a.deadlines.rd, b.deadlines.rd, sortDirection);
        case "financialAid":
          return compareDeadline(a.deadlines.financialAid, b.deadlines.financialAid, sortDirection);
      }
    });
  }, [colleges, sortKey, sortDirection]);

  return (
    <div className="overflow-x-auto rounded-lg border border-border shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-navy text-navy-foreground text-left text-xs uppercase tracking-wide divide-x divide-navy-foreground/15">
            <th rowSpan={2} className={cn(HEADER_CELL, "rounded-tl-lg")}>
              <SortableHeader
                label="College"
                active={sortKey === "name"}
                direction={sortDirection}
                onClick={() => handleSort("name")}
              />
            </th>
            <th rowSpan={2} className={HEADER_CELL}>
              <SortableHeader
                label="Status"
                active={sortKey === "status"}
                direction={sortDirection}
                onClick={() => handleSort("status")}
              />
            </th>
            <th colSpan={4} className={cn(HEADER_CELL, "text-center")}>
              Deadlines
            </th>
            {/* Explicit border-l, not left to divide-x: divide-x only
                borders siblings within the SAME <tr>, but this cell's
                rowSpan makes it stand beside row 2's "Fin. Aid" cell too —
                without this, that boundary rendered with no divider at
                all (found live: looked like the header just ran together
                there). */}
            <th rowSpan={2} className={cn(HEADER_CELL, "border-l border-navy-foreground/15")}>
              Requirements
            </th>
            <th rowSpan={2} className={HEADER_CELL}>
              Readiness
            </th>
            <th rowSpan={2} className={HEADER_CELL} />
            <th rowSpan={2} className={cn(HEADER_CELL, "rounded-tr-lg")} />
          </tr>
          <tr className="bg-navy text-navy-foreground text-left text-xs uppercase tracking-wide divide-x divide-navy-foreground/15 border-t border-navy-foreground/15">
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>
              <SortableHeader
                label="EA"
                active={sortKey === "ea"}
                direction={sortDirection}
                onClick={() => handleSort("ea")}
              />
            </th>
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>
              <SortableHeader
                label="ED"
                active={sortKey === "ed"}
                direction={sortDirection}
                onClick={() => handleSort("ed")}
              />
            </th>
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>
              <SortableHeader
                label="RD"
                active={sortKey === "rd"}
                direction={sortDirection}
                onClick={() => handleSort("rd")}
              />
            </th>
            <th className={cn(HEADER_CELL, "text-navy-foreground/70")}>
              <SortableHeader
                label="Fin. Aid"
                active={sortKey === "financialAid"}
                direction={sortDirection}
                onClick={() => handleSort("financialAid")}
              />
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedColleges.map((college) => {
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
                  {requirements.length > 0 ? (
                    // Keyed by count: the moment the real, final list
                    // lands (one flat write — see requirements_agent.py),
                    // this pops in and permanently replaces whatever was
                    // showing before (the fake progress cell below, or the
                    // plain "Researching…" spinner during logo/deadlines).
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
                  ) : !college.researching ? (
                    <span className="text-muted-foreground">Not researched yet</span>
                  ) : college.researchStage === "requirements" ? (
                    <FakeRequirementsProgressCell collegeId={college.id} />
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Researching…
                    </span>
                  )}
                </td>
                <td className={BODY_CELL}>
                  <ReadinessCell
                    readiness={college.readiness}
                    hasTasks={collegeIdsWithTasks.has(college.id)}
                  />
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
