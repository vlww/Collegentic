import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { AddCollegeForm } from "@/components/collegentic/AddCollegeForm";
import { CollegeTable } from "@/components/collegentic/CollegeTable";
import { ResearchProgressBar } from "@/components/collegentic/ResearchProgressBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  deleteCollege,
  getAgentRuns,
  getColleges,
  getPipelineProgress,
  getRequirements,
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
  const [error, setError] = useState(false);
  const [researching, setResearching] = useState(false);
  const [progress, setProgress] = useState<PipelineProgress | null>(null);
  const [pipelineFailed, setPipelineFailed] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  // Shown in place of the progress bar right after a run finishes — a
  // one-line green confirmation instead of the Orchestrator's own
  // paragraph-long plain-language reply (AddCollegeForm no longer renders
  // that at all; it read as long and out of place next to a live-updating
  // table that already shows the result). Auto-clears after a few seconds
  // and immediately on the next submission.
  const [justCompleted, setJustCompleted] = useState(false);
  const justCompletedTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  function announceCompletion() {
    setJustCompleted(true);
    if (justCompletedTimeout.current) clearTimeout(justCompletedTimeout.current);
    justCompletedTimeout.current = setTimeout(() => setJustCompleted(false), 6000);
  }

  const load = useCallback(() => {
    getColleges()
      .then(async (result) => {
        setColleges(result);
        setRequirements(result.length > 0 ? await getRequirements(result.map((c) => c.id)) : []);
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

  useEffect(() => {
    return () => {
      if (justCompletedTimeout.current) clearTimeout(justCompletedTimeout.current);
    };
  }, []);

  // While a "research and add" submission is running, the orchestrator
  // pipeline is writing colleges/deadlines/requirements/branding to
  // Firestore progressively as each sub-agent finishes — poll so the table
  // fills in live instead of only refreshing once the whole request (which
  // can take a minute+) completes.
  useEffect(() => {
    if (!researching) return;
    const interval = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [researching, load]);

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
    setResearching(true);
    try {
      const names = incomplete.map((c) => c.name);
      await sendOrchestratorMessage(
        names.length > 0
          ? `Resume research — a previous attempt was interrupted by an error. ` +
              `Please finish researching these colleges I'm already tracking: ${names.join(", ")}.`
          : `Resume research — a previous attempt was interrupted by an error before it finished ` +
              `planning tasks and scoring readiness for my tracked colleges. Please pick up where it left off.`
      );
      load();
      checkPipelineStatus();
      announceCompletion();
    } catch (err) {
      setResumeError(
        err instanceof Error && err.message
          ? err.message
          : "Resuming didn't work. Please try again."
      );
    } finally {
      setResuming(false);
      setResearching(false);
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
    announceCompletion();
  }

  async function handleDelete(collegeId: string) {
    await deleteCollege(collegeId);
    load();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Colleges"
        description="Every school you're tracking, with application type, deadlines, and school colors."
      />

      <AddCollegeForm
        onDone={handleResearchDone}
        onLoadingChange={(loading) => {
          setResearching(loading);
          if (loading) setJustCompleted(false);
        }}
      />

      {researching && progress && <ResearchProgressBar progress={progress} />}
      {!researching && justCompleted && (
        <Card className="border-success/40">
          <CardContent className="flex items-center gap-2 py-4 text-sm font-medium text-success">
            <CheckCircle2 className="h-4 w-4" />
            Research completed
          </CardContent>
        </Card>
      )}

      {pipelineFailed && (
        <Card className="border-warning/40">
          <CardContent className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm text-warning">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Research hit an error partway through — some colleges may be incomplete.
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
          onDelete={handleDelete}
        />
      )}
    </div>
  );
}
