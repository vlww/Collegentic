import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { AddCollegeForm } from "@/components/collegentic/AddCollegeForm";
import { CollegeTable } from "@/components/collegentic/CollegeTable";
import { EssayProgressBar } from "@/components/collegentic/EssayProgressBar";
import { ResearchProgressBar } from "@/components/collegentic/ResearchProgressBar";
import { TaskPlanningProgressBar } from "@/components/collegentic/TaskPlanningProgressBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  deleteCollege,
  getAgentRuns,
  getColleges,
  getPipelineProgress,
  getRequirements,
  getTasks,
  refreshCollegeLogos,
  sendOrchestratorMessage,
} from "@/lib/api";
import { latestPipelineStatus } from "@/lib/agentRuns";
import type { College, PipelineProgress, Requirement } from "@/lib/types";

// The backend paces its Firestore writes per-college and per-field (color,
// then logo, then each deadline individually — see requirements_agent.py's
// staged persistence) specifically so a student watching this table sees
// each value land one at a time. Polls fast enough to catch that without
// flattening several fields' worth of individually-timed writes into one
// visible jump per tick — also just genuinely snappier for a judge
// watching a live demo.
const POLL_INTERVAL_MS = 700;

export function Colleges() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [collegeIdsWithTasks, setCollegeIdsWithTasks] = useState<Set<string>>(new Set());
  const [error, setError] = useState(false);
  const [progress, setProgress] = useState<PipelineProgress | null>(null);
  const [pipelineFailed, setPipelineFailed] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  // Set straight from AddCollegeForm's onLoadingChange, not derived from
  // `progress` — a brand-new submission's very first tick can land before
  // the backend's own start_pipeline_progress write exists yet, so
  // `progress` itself is still null for a moment right at the start. Purely
  // a local "a request is in flight on THIS page load" flag: it resets on
  // remount same as AddCollegeForm's own loading state does, which is fine
  // — `progress`'s own stage (fetched fresh on mount) covers a submission
  // still running after a navigate-away-and-back.
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(() => {
    getColleges()
      .then(async (result) => {
        // Fetch requirements/tasks BEFORE setting any state — setting
        // `colleges` first (with an `await` before the rest catches up) let
        // React flush a render in between, showing a college whose research
        // just finished (researching: false) against the OLD, still-empty
        // requirements list: a one-frame "Not researched yet" flash before
        // the real count landed. Resolving everything first means all the
        // setState calls land back to back in the same render.
        const [newRequirements, newTasks] = await Promise.all([
          result.length > 0 ? getRequirements(result.map((c) => c.id)) : Promise.resolve([]),
          getTasks(),
        ]);
        setColleges(result);
        setRequirements(newRequirements);
        setCollegeIdsWithTasks(
          new Set(newTasks.map((t) => t.collegeId).filter((id): id is string => id !== null))
        );
      })
      .catch(() => setError(true));
    getPipelineProgress()
      .then(setProgress)
      .catch(() => {});
  }, []);

  // Drives the Resume Research button — hidden whenever the most recent
  // pipeline run didn't fail, shown when it did (see api.py's
  // college_intake_pipeline error handler, which is what leaves a run
  // "failed" rather than silently vanishing).
  const checkPipelineStatus = useCallback(() => {
    getAgentRuns()
      .then((runs) => setPipelineFailed(latestPipelineStatus(runs) === "failed"))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    checkPipelineStatus();
  }, [load, checkPipelineStatus]);

  // Both derived fresh from polled data every load, NOT from a local
  // "is a submission in flight" flag — a page navigation away and back
  // remounts this component, resetting any such flag to false even though
  // a submission from before is still running on the backend. Basing this
  // on the colleges/progress this mount just fetched means these reflect
  // reality on remount instead of silently going blank (found live: this
  // used to be tied to AddCollegeForm's onLoadingChange alone, so leaving
  // the page mid-run and coming back showed no progress bar at all, even
  // though research — or task planning/readiness scoring right after it —
  // was still genuinely in flight).
  const anyCollegeResearching = (colleges ?? []).some((c) => c.researching);
  const isPlanning =
    !anyCollegeResearching && progress !== null && progress.stage === "planning";
  const isEssaysOrDone =
    !anyCollegeResearching &&
    progress !== null &&
    (progress.stage === "essays" || progress.stage === "done");

  // Polls for as long as `stage` is anything other than "done" — not an OR
  // of the specific transient flags above (anyCollegeResearching, stage ===
  // "planning"/"essays"). Found live: that OR had a real gap between the
  // LAST college's `researching` flag clearing and the backend's next
  // stage-marker write actually landing — anyCollegeResearching goes false
  // an instant before stage flips off "researching", and a poll tick
  // landing in exactly that window read pollingActive as false, cleared
  // the interval, and never polled again (nothing was left to flip it back
  // on) — the page just sat there looking frozen on a stale, contradictory
  // state even though the backend kept working. Keying off `stage` alone
  // has no such gap: every stage transition is itself a `stage` write, so
  // there's no moment where "not done yet" reads as "nothing to poll for."
  const pollingActive = submitting || (progress !== null && progress.stage !== "done");

  useEffect(() => {
    if (!pollingActive) return;
    const interval = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [pollingActive, load]);

  const requirementsByCollege: Record<string, Requirement[]> = {};
  for (const requirement of requirements) {
    (requirementsByCollege[requirement.collegeId] ??= []).push(requirement);
  }

  async function handleResume() {
    const incomplete = (colleges ?? []).filter(
      (c) => (requirementsByCollege[c.id]?.length ?? 0) === 0
    );
    setResuming(true);
    setResumeError(null);
    try {
      const names = incomplete.map((c) => c.name);
      await sendOrchestratorMessage(
        names.length > 0
          ? `Resume research. A previous attempt was interrupted by an error. ` +
              `Please finish researching these colleges I'm already tracking: ${names.join(", ")}.`
          : `Resume research. A previous attempt was interrupted by an error before it finished ` +
              `planning tasks and scoring readiness for my tracked colleges. Please pick up where it left off.`
      );
      load();
      checkPipelineStatus();
    } catch (err) {
      setResumeError(
        err instanceof Error && err.message
          ? err.message
          : "Resuming didn't work. Please try again."
      );
    } finally {
      setResuming(false);
    }
  }

  // Runs after every "Research and add" submission — re-fetches logos with
  // whatever the current picker logic is (cheap, no LLM call) for every
  // tracked college, not just the ones just researched, so there's no
  // separate manual "refresh logos" action for picking up a later fix.
  // Best-effort: a failure here shouldn't hide the research result itself.
  async function handleResearchDone() {
    try {
      await refreshCollegeLogos();
    } catch {
      // ignore — logos will still be refreshed on the next research pass
    }
    load();
    checkPipelineStatus();
  }

  async function handleDelete(collegeId: string) {
    await deleteCollege(collegeId);
    load();
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Colleges" />

      <AddCollegeForm
        onDone={handleResearchDone}
        onLoadingChange={(loading) => {
          setSubmitting(loading);
          // Kick off an immediate refresh the instant a submission starts,
          // rather than waiting up to POLL_INTERVAL_MS for the first poll
          // tick.
          if (loading) load();
        }}
      />

      {anyCollegeResearching && progress && (
        <ResearchProgressBar progress={progress} />
      )}
      {isPlanning && <TaskPlanningProgressBar />}
      {isEssaysOrDone && progress && <EssayProgressBar progress={progress} />}

      {pipelineFailed && (
        <Card className="border-warning/40">
          <CardContent className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm text-warning">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Research hit an error partway through, some colleges may be incomplete.
              Check Agent Activity for details, then try again.
            </p>
            <Button
              variant="outline"
              onClick={handleResume}
              disabled={resuming}
              className="shrink-0"
            >
              {resuming ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Resuming…
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4" /> Resume research
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      )}
      {resumeError && <p className="text-sm text-destructive">{resumeError}</p>}

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="text-sm text-destructive">
            Couldn't reach Collegentic's backend. Is it running?
          </CardContent>
        </Card>
      )}

      {!error && colleges === null && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      {!error && colleges !== null && colleges.length > 0 && (
        <CollegeTable
          colleges={colleges}
          requirementsByCollege={requirementsByCollege}
          collegeIdsWithTasks={collegeIdsWithTasks}
          onDelete={handleDelete}
        />
      )}
    </div>
  );
}
