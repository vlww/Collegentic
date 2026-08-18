import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function EssayMap() {
  return (
    <div>
      <PageHeader
        title="Essay Map"
        description="A network view of your materials, the prompts they match, and how strong each match is."
      />
      <ComingSoon milestone="Milestone 12 — Essay Map visualization">
        Node/edge visualization of essayMatches — line thickness encodes match
        strength, per .agents-cli-spec.md § Essay Matching Agent.
      </ComingSoon>
    </div>
  );
}
