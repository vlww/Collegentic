import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function AgentActivity() {
  return (
    <div>
      <PageHeader
        title="Agent Activity"
        description="What Collegentic's agents are doing right now, and what they've done — running, completed, waiting for you, or failed."
      />
      <ComingSoon milestone="Milestone 13 — Agent Activity page">
        Live feed backed by the agentRuns collection, written by a shared
        activity-logging callback attached to every sub-agent in the pipeline.
      </ComingSoon>
    </div>
  );
}
