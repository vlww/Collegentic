import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { AddMaterialForm } from "@/components/collegentic/AddMaterialForm";
import { EssayNetworkGraph } from "@/components/collegentic/EssayNetworkGraph";
import { RequirementsList } from "@/components/collegentic/RequirementsList";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  getColleges,
  getEssayMatches,
  getEssayPrompts,
  getMaterials,
  getRequirements,
  recomputeReadiness,
} from "@/lib/api";
import type {
  College,
  EssayMatch,
  EssayPrompt,
  Requirement,
  RequirementStatus,
  StudentMaterial,
} from "@/lib/types";

const TYPE_LABEL: Record<StudentMaterial["type"], string> = {
  CommonApp: "Common App Essay",
  Supplemental: "Supplemental Essay",
  ActivityDescription: "Activity Description",
  Award: "Award / Honor",
  Note: "Note",
  Idea: "Idea",
};

export function Essays() {
  const [materials, setMaterials] = useState<StudentMaterial[] | null>(null);
  const [matches, setMatches] = useState<EssayMatch[]>([]);
  const [prompts, setPrompts] = useState<EssayPrompt[]>([]);
  const [colleges, setColleges] = useState<College[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);

  const load = useCallback(() => {
    getMaterials().then(setMaterials);
    getEssayMatches().then(setMatches);
    getEssayPrompts().then(setPrompts);
    getColleges().then(async (result) => {
      setColleges(result);
      setRequirements(result.length > 0 ? await getRequirements(result.map((c) => c.id)) : []);
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const promptById = Object.fromEntries(prompts.map((p) => [p.id, p]));
  const materialById = Object.fromEntries((materials ?? []).map((m) => [m.id, m]));
  const collegeById = Object.fromEntries(colleges.map((c) => [c.id, c]));
  const essayRequirements = requirements.filter((r) => r.type === "essay");

  async function handleProgressChange(requirementId: string, status: RequirementStatus) {
    setRequirements((prev) =>
      prev.map((r) => (r.id === requirementId ? { ...r, status } : r))
    );
    // Feeds compute_readiness_score — essays are now the largest-weighted
    // readiness category, so this should land promptly, not eventually.
    await recomputeReadiness();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Essays"
        description="Your essays, activities, and notes, not a document editor."
      />

      <AddMaterialForm onAdded={load} />

      <div>
        <h2 className="text-sm font-semibold mb-3">Your Materials</h2>
        {materials !== null && materials.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Add an essay, activity, or note above to get started.
          </p>
        )}
        {materials !== null && materials.length > 0 && (
          <div className="divide-y divide-border rounded-lg border border-border">
            {materials.map((material) => (
              <div key={material.id} className="p-4 space-y-1">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-medium uppercase tracking-wide">
                    {TYPE_LABEL[material.type]}
                  </span>
                  {material.topic && <span>· {material.topic}</span>}
                  {material.wordCount !== null && <span>· {material.wordCount} words</span>}
                </div>
                <p className="text-sm font-medium text-foreground">{material.title}</p>
                {material.partialText && (
                  <p className="text-sm text-muted-foreground line-clamp-2">
                    {material.partialText}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {essayRequirements.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Essay Progress</h2>
          <p className="text-sm text-muted-foreground mb-3">
            Every college's actual essay requirement, tracked one at a time.
          </p>
          <RequirementsList
            requirements={essayRequirements}
            collegeName={(id) => collegeById[id]?.name ?? id}
            onProgressChange={handleProgressChange}
          />
        </div>
      )}

      {matches.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Suggested Matches</h2>
          <p className="text-sm text-muted-foreground mb-3">
            Where an existing material might fit a new prompt.
          </p>
          <div className="divide-y divide-border rounded-lg border border-border">
            {matches.map((match) => {
              const prompt = promptById[match.promptId];
              const material = materialById[match.materialId];
              const college = collegeById[match.collegeId];
              return (
                <div key={match.id} className="p-4 space-y-1.5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="text-xs text-muted-foreground">
                      {college && <span className="font-medium">{college.name}</span>}
                      {prompt && <span> · {prompt.text}</span>}
                    </div>
                    <Badge variant="outline">
                      {match.recommendation === "adapt" ? "Adapt existing" : "Write new"}
                    </Badge>
                  </div>
                  <p className="text-sm text-foreground">
                    {material?.title ?? "Material"} · {Math.round(match.matchScore)}% fit
                  </p>
                  <p className="text-sm text-muted-foreground">{match.reasoning}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <Card className="border-0 shadow-none bg-transparent">
        <CardContent className="px-0 text-xs text-muted-foreground">
          Collegentic never writes or edits your essay text, only reads it for reuse-fit.
        </CardContent>
      </Card>

      {colleges.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Essay Map</h2>
          <p className="text-sm text-muted-foreground mb-3">
            A network view of your materials, the prompts they match, and how strong each
            match is.
          </p>
          <EssayNetworkGraph
            colleges={colleges}
            prompts={prompts}
            materials={materials ?? []}
            matches={matches}
          />
        </div>
      )}
    </div>
  );
}
