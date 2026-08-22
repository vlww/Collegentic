/**
 * Deadlines are stored as UTC midnight (a calendar date, not a real moment
 * in time) — formatting in the viewer's local timezone would show the
 * wrong day for anyone west of UTC (e.g. a UTC-7 reader would see "Oct 31"
 * for a stored "2026-11-01T00:00:00Z" deadline). `timeZone: "UTC"` pins
 * display to the date that was actually stored.
 */
export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** Whole calendar days from today (UTC) until `iso` (negative if already past). */
export function daysUntil(iso: string): number {
  const startOfTodayUtc = Date.UTC(
    new Date().getUTCFullYear(),
    new Date().getUTCMonth(),
    new Date().getUTCDate()
  );
  const ms = new Date(iso).getTime() - startOfTodayUtc;
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

/** A real moment in time (AgentRun.startedAt/completedAt), unlike deadlines
 * above — shown in the viewer's own local timezone, not pinned to UTC. */
export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** How long an agent run took, or how long it's been running so far if
 * `endIso` is null. */
export function formatDuration(startIso: string, endIso: string | null): string {
  const ms = (endIso ? new Date(endIso).getTime() : Date.now()) - new Date(startIso).getTime();
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

/** Earliest of a college's set deadlines, or null if none are known yet. */
export function nextDeadline(deadlines: {
  ea: string | null;
  ed: string | null;
  rd: string | null;
  financialAid: string | null;
}): string | null {
  const dates = [deadlines.ea, deadlines.ed, deadlines.rd, deadlines.financialAid].filter(
    (d): d is string => Boolean(d)
  );
  if (dates.length === 0) return null;
  return dates.reduce((earliest, d) => (d < earliest ? d : earliest));
}
