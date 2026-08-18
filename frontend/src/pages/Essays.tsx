import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Essays() {
  return (
    <div>
      <PageHeader
        title="Essays"
        description="Your existing essays, activities, and notes — titles, topics, and completion percentage, not a document editor."
      />
      <ComingSoon milestone="Milestone 11 — Essay Matching Agent">
        Student material library (add/edit metadata only — Collegentic never
        writes or edits essay text, see .agents-cli-spec.md § Constraints).
      </ComingSoon>
    </div>
  );
}
