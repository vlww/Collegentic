import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Colleges() {
  return (
    <div>
      <PageHeader
        title="Colleges"
        description="Every school you're tracking, with application type, deadlines, and school colors."
      />
      <ComingSoon milestone="Milestone 6 — Dashboard / Colleges / Requirements pages">
        College list + detail view, backed by Firestore's colleges collection
        once the College Research Agent (M3) is writing real data.
      </ComingSoon>
    </div>
  );
}
