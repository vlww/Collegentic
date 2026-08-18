import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Dashboard() {
  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Today's Priorities and the full college application matrix — what's going on with all of your applications, at a glance."
      />
      <ComingSoon milestone="Milestone 6 — Dashboard / Colleges / Requirements pages">
        Today's Priorities strip and the multi-college progress table land once
        Requirements (M4) and the Orchestrator (M5) are producing real data to show.
      </ComingSoon>
    </div>
  );
}
