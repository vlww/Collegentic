import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Requirements() {
  return (
    <div>
      <PageHeader
        title="Requirements"
        description="Every requirement across every college, with status, confidence, and source transparency."
      />
      <ComingSoon milestone="Milestone 6 — Dashboard / Colleges / Requirements pages">
        Cross-college requirements table with "View Source" detail, once the
        Requirements Agent (M4) is normalizing research into structured records.
      </ComingSoon>
    </div>
  );
}
