import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  Loader2,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EssayEditor } from "@/components/collegentic/EssayEditor";
import { EssayNetworkGraph } from "@/components/collegentic/EssayNetworkGraph";
import { RequirementsList } from "@/components/collegentic/RequirementsList";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { collegeAccentColor } from "@/components/collegentic/CollegeAvatar";
import { cn } from "@/utils";
import {
  deleteMaterial,
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

// "Your Materials" and "Essay Progress" sit side by side and are meant to
// visually match up (same row height, same count) — a longer preview here
// would make that pairing pointless, and a "Show N more" still exists below
// for anyone who wants the rest.
const PREVIEW_COUNT = 2;

// Shared by each Materials row and RequirementsList's rowClassName below so
// a row in either column lines up against its counterpart in the other —
// tall enough for compact content (see RequirementsList's `compact`) without
// clipping mid-line under normal titles/descriptions.
const PREVIEW_ROW_CLASS = "h-36 overflow-hidden";

const TYPE_LABEL: Record<StudentMaterial["type"], string> = {
  CommonApp: "Common App Essay",
  Supplemental: "Supplemental Essay",
  ActivityDescription: "Activity Description",
  Award: "Award / Honor",
  Note: "Note",
  Idea: "Idea",
};

export function Essays() {
  const navigate = useNavigate();
  const [materials, setMaterials] = useState<StudentMaterial[] | null>(null);
  // null (not yet fetched) vs [] (fetched, genuinely no matches/prompts) has
  // to stay distinct — see the Essay Map's loading guard below, which is
  // exactly what stops it from flashing the "nothing shares a category"
  // empty state while these two are still mid-flight.
  const [matches, setMatches] = useState<EssayMatch[] | null>(null);
  const [prompts, setPrompts] = useState<EssayPrompt[] | null>(null);
  const [colleges, setColleges] = useState<College[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [materialsExpanded, setMaterialsExpanded] = useState(false);

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

  // The backend re-matches (or drops) any prompt that had pointed at this
  // material — refetch matches alongside removing the material locally
  // rather than a full `load()`, so Essay Progress/colleges don't reload
  // for something that can't have changed them.
  async function handleDeleteMaterial(materialId: string) {
    await deleteMaterial(materialId);
    setMaterials((prev) => (prev ?? []).filter((m) => m.id !== materialId));
    getEssayMatches().then(setMatches);
  }

  // Same reasoning as handleDeleteMaterial above: a saved essay's text can
  // change which category it falls into (update_material already
  // recomputes server-side — see app/api.py), so refetch matches alongside
  // updating the one changed material locally rather than a full `load()`.
  function handleEssaySaved(updated: StudentMaterial) {
    setMaterials((prev) =>
      (prev ?? []).map((m) => (m.id === updated.id ? updated : m))
    );
    getEssayMatches().then(setMatches);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Essays" />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {materials !== null && (
          <SectionCard
            title="Your Materials"
            icon={BookOpen}
            contentClassName={materials.length > 0 ? "" : "p-4"}
          >
            {materials.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Add an essay, activity, or note from My Progress to get started.
              </p>
            ) : (
              <div className="divide-y divide-border">
                {(materialsExpanded ? materials : materials.slice(0, PREVIEW_COUNT)).map(
                  (material) => (
                    <div
                      key={material.id}
                      className={cn(
                        PREVIEW_ROW_CLASS,
                        "school-tint border-l-4 border-orange p-4 flex items-start justify-between gap-3"
                      )}
                      // Reuses the same subtle college-color wash as Essay
                      // Progress's rows (.school-tint mixes --school-accent
                      // in at only 5% — see global.css) rather than the flat
                      // --orange-tint token, which read as a much stronger,
                      // more saturated fill at full-row size than it does on
                      // a small map bubble.
                      style={{ "--school-accent": "var(--orange)" } as React.CSSProperties}
                    >
                      <div className="min-w-0 space-y-1">
                        <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
                          <span className="font-medium uppercase tracking-wide shrink-0">
                            {TYPE_LABEL[material.type]}
                          </span>
                          {material.topic && <span className="truncate">· {material.topic}</span>}
                          {material.wordCount !== null && (
                            <span className="shrink-0">· {material.wordCount} words</span>
                          )}
                        </div>
                        <p className="text-sm font-medium text-foreground truncate">
                          {material.title}
                        </p>
                        {material.partialText && (
                          <p className="text-sm text-muted-foreground line-clamp-2">
                            {material.partialText}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 flex-col items-center gap-1">
                        <button
                          type="button"
                          onClick={() =>
                            navigate("/progress", { state: { editMaterial: material } })
                          }
                          title={`Edit ${material.title}`}
                          aria-label={`Edit ${material.title}`}
                          className="rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <DeleteMaterialButton
                          material={material}
                          onDelete={handleDeleteMaterial}
                        />
                      </div>
                    </div>
                  )
                )}
                {materials.length > PREVIEW_COUNT && (
                  <button
                    type="button"
                    onClick={() => setMaterialsExpanded((e) => !e)}
                    className="flex w-full items-center justify-center gap-1.5 px-4 py-2.5 text-xs font-medium text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                  >
                    {materialsExpanded ? (
                      <>
                        Show fewer <ChevronUp className="h-3.5 w-3.5" />
                      </>
                    ) : (
                      <>
                        Show {materials.length - PREVIEW_COUNT} more{" "}
                        <ChevronDown className="h-3.5 w-3.5" />
                      </>
                    )}
                  </button>
                )}
              </div>
            )}
          </SectionCard>
        )}

        {essayRequirements.length > 0 && (
          <SectionCard title="Essay Progress" icon={ClipboardCheck} contentClassName="">
            <RequirementsList
              requirements={essayRequirements}
              collegeName={(id) => collegeById[id]?.name ?? id}
              collegeAccent={(id) =>
                collegeById[id] ? collegeAccentColor(collegeById[id]) : "var(--navy)"
              }
              onProgressChange={handleProgressChange}
              initialCount={PREVIEW_COUNT}
              compact
              rowClassName={PREVIEW_ROW_CLASS}
            />
          </SectionCard>
        )}
      </div>

      {colleges.length > 0 && (
        <SectionCard title="Essay Map" icon={Share2}>
          <p className="mb-3 text-sm text-muted-foreground">
            The best-fit prompts across your colleges, clustered by school and connected to
            the material that fits each one. Hover a prompt for the match detail.
          </p>
          {materials === null || matches === null || prompts === null ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading essay map…
            </div>
          ) : (
            <EssayNetworkGraph
              colleges={colleges}
              prompts={prompts}
              materials={materials}
              matches={matches}
            />
          )}
        </SectionCard>
      )}

      {materials !== null && materials.length > 0 && (
        <EssayEditor materials={materials} onSaved={handleEssaySaved} />
      )}
    </div>
  );
}

/**
 * Trash icon under the edit icon -> a confirm dialog, same "deliberate
 * second action before losing data" shape as CollegeTable's DeleteCell —
 * a material can be the best-fit match behind an Essay Map connection, so
 * an accidental single click shouldn't be able to remove it.
 */
function DeleteMaterialButton({
  material,
  onDelete,
}: {
  material: StudentMaterial;
  onDelete: (materialId: string) => Promise<void>;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [failed, setFailed] = useState(false);

  async function handleConfirm() {
    setDeleting(true);
    setFailed(false);
    try {
      await onDelete(material.id);
      // Row unmounts once the parent's `materials` list no longer has it —
      // nothing left to reset here on success.
    } catch {
      setDeleting(false);
      setConfirmOpen(false);
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        title={`Remove ${material.title}`}
        aria-label={`Remove ${material.title}`}
        className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
      >
        <Trash2 className="h-4 w-4" />
      </button>
      {failed && <span className="text-xs text-destructive">Failed, try again</span>}
      <ConfirmDialog
        open={confirmOpen}
        message={`Are you sure you want to remove ${material.title} from your materials?`}
        loading={deleting}
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
