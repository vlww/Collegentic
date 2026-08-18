import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Tasks() {
  return (
    <div>
      <PageHeader
        title="Tasks"
        description="Every generated task, filterable and sortable by college, category, and priority."
      />
      <ComingSoon milestone="Milestone 7 — Task Planning Agent">
        Task list backed by Firestore's tasks collection, deduped against
        existing tasks by the Task Planning Agent.
      </ComingSoon>
    </div>
  );
}
