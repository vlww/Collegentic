import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Readiness() {
  return (
    <div>
      <PageHeader
        title="Application Readiness"
        description="An explainable readiness score per college — weighted completion of required components, not an arbitrary percentage."
      />
      <ComingSoon milestone="Milestone 9 — Application Readiness Agent">
        Per-college breakdown (requirements / essays / recommendations /
        testing / deadline readiness) with a plain-language explanation.
      </ComingSoon>
    </div>
  );
}
