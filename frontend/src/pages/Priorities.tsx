import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Priorities() {
  return (
    <div>
      <PageHeader
        title="Priorities"
        description="The full prioritized task list with plain-language explanations for each score."
      />
      <ComingSoon milestone="Milestone 8 — Deadline & Priority Agent">
        Explainable priority scoring (deadline urgency + workload + dependency
        pressure + requirement importance + progress) — the formula lives in
        scoring.py, deterministic and unit-tested; the agent only writes the
        explanation sentence.
      </ComingSoon>
    </div>
  );
}
