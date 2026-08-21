import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { EssayNetworkGraph } from "@/components/collegentic/EssayNetworkGraph";
import { getColleges, getEssayMatches, getEssayPrompts, getMaterials } from "@/lib/api";
import type { College, EssayMatch, EssayPrompt, StudentMaterial } from "@/lib/types";

export function EssayMap() {
  const [colleges, setColleges] = useState<College[] | null>(null);
  const [prompts, setPrompts] = useState<EssayPrompt[]>([]);
  const [materials, setMaterials] = useState<StudentMaterial[]>([]);
  const [matches, setMatches] = useState<EssayMatch[]>([]);

  useEffect(() => {
    getColleges().then(setColleges);
    getEssayPrompts().then(setPrompts);
    getMaterials().then(setMaterials);
    getEssayMatches().then(setMatches);
  }, []);

  return (
    <div>
      <PageHeader
        title="Essay Map"
        description="A network view of your materials, the prompts they match, and how strong each match is."
      />
      {colleges !== null && (
        <EssayNetworkGraph
          colleges={colleges}
          prompts={prompts}
          materials={materials}
          matches={matches}
        />
      )}
    </div>
  );
}
