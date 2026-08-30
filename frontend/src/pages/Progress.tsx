import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { ChevronDown, GraduationCap, Loader2, Plus, Trash2, Users } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { AddMaterialForm } from "@/components/collegentic/AddMaterialForm";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/utils";
import {
  createRecommendation,
  deleteRecommendation,
  getColleges,
  getRecommendations,
  getTestScores,
  recomputeReadiness,
  updateRecommendation,
  updateTestScores,
} from "@/lib/api";
import type {
  College,
  Recommendation,
  RecommendationStatus,
  RecommenderType,
  StudentMaterial,
} from "@/lib/types";
import { RECOMMENDATION_ALL_COLLEGES } from "@/lib/types";

const RECOMMENDER_TYPE_LABEL: Record<RecommenderType, string> = {
  TeacherSTEM: "Teacher: STEM",
  TeacherHumanities: "Teacher: Humanities",
  Counselor: "Counselor",
  Employer: "Employer",
  Other: "Other",
};
const RECOMMENDER_TYPE_OPTIONS = Object.keys(RECOMMENDER_TYPE_LABEL) as RecommenderType[];

const RECOMMENDATION_STATUS_LABEL: Record<RecommendationStatus, string> = {
  NotRequested: "Not Requested Yet",
  Requested: "Requested",
  Submitted: "Submitted",
};
const RECOMMENDATION_STATUS_OPTIONS = Object.keys(
  RECOMMENDATION_STATUS_LABEL
) as RecommendationStatus[];

function CollegeMultiSelect({
  colleges,
  selectedIds,
  onChange,
}: {
  colleges: College[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const isAll = selectedIds.includes(RECOMMENDATION_ALL_COLLEGES);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  function toggleCollege(id: string) {
    if (isAll) return;
    onChange(
      selectedIds.includes(id) ? selectedIds.filter((s) => s !== id) : [...selectedIds, id]
    );
  }

  const label = isAll
    ? "All colleges"
    : selectedIds.length === 0
      ? "No colleges yet"
      : `${selectedIds.length} college${selectedIds.length > 1 ? "s" : ""}`;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 w-40 items-center justify-between gap-2 rounded-md border border-input bg-transparent px-3 text-left text-xs shadow-xs"
      >
        {label}
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-50" />
      </button>
      {open && (
        <div className="absolute z-10 mt-1 w-52 rounded-md border border-border bg-popover p-2 text-popover-foreground shadow-md">
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {colleges.map((college) => (
              <label
                key={college.id}
                className={cn(
                  "flex items-center gap-2 rounded px-1 py-1 text-xs hover:bg-accent",
                  isAll && "opacity-50"
                )}
              >
                <input
                  type="checkbox"
                  checked={isAll || selectedIds.includes(college.id)}
                  disabled={isAll}
                  onChange={() => toggleCollege(college.id)}
                />
                {college.name}
              </label>
            ))}
          </div>
          <div className="mt-1 border-t border-border pt-1">
            <label className="flex items-center gap-2 rounded px-1 py-1 text-xs font-medium hover:bg-accent">
              <input
                type="checkbox"
                checked={isAll}
                onChange={() => onChange(isAll ? [] : [RECOMMENDATION_ALL_COLLEGES])}
              />
              All
            </label>
          </div>
        </div>
      )}
    </div>
  );
}

function RecommendationRow({
  recommendation,
  colleges,
  onChange,
  onDelete,
}: {
  recommendation: Recommendation;
  colleges: College[];
  onChange: (updated: Recommendation) => void;
  onDelete: (id: string) => void;
}) {
  const [name, setName] = useState(recommendation.recommenderName ?? "");
  const [deleting, setDeleting] = useState(false);

  async function save(patch: Partial<Recommendation>) {
    const updated = { ...recommendation, ...patch };
    onChange(updated);
    await updateRecommendation(recommendation.id, {
      recommenderName: updated.recommenderName,
      recommenderType: updated.recommenderType,
      status: updated.status,
      collegeIds: updated.collegeIds,
    });
    await recomputeReadiness();
  }

  function handleNameBlur() {
    const trimmed = name.trim();
    if (trimmed === (recommendation.recommenderName ?? "")) return;
    save({ recommenderName: trimmed || null });
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteRecommendation(recommendation.id);
      onDelete(recommendation.id);
      await recomputeReadiness();
    } catch {
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 p-3">
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={handleNameBlur}
        placeholder="Recommender's name"
        className="h-8 w-44 text-xs"
      />
      <Select
        value={recommendation.recommenderType}
        onValueChange={(value) => save({ recommenderType: value as RecommenderType })}
      >
        <SelectTrigger size="sm" className="h-8 w-40 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {RECOMMENDER_TYPE_OPTIONS.map((type) => (
            <SelectItem key={type} value={type}>
              {RECOMMENDER_TYPE_LABEL[type]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <CollegeMultiSelect
        colleges={colleges}
        selectedIds={recommendation.collegeIds}
        onChange={(collegeIds) => save({ collegeIds })}
      />
      <Select
        value={recommendation.status}
        onValueChange={(value) => save({ status: value as RecommendationStatus })}
      >
        <SelectTrigger size="sm" className="h-8 w-40 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {RECOMMENDATION_STATUS_OPTIONS.map((status) => (
            <SelectItem key={status} value={status}>
              {RECOMMENDATION_STATUS_LABEL[status]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <button
        type="button"
        onClick={handleDelete}
        disabled={deleting}
        title="Remove recommender"
        aria-label="Remove recommender"
        className="ml-auto rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
      >
        {deleting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Trash2 className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}

export function Progress() {
  const [colleges, setColleges] = useState<College[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [testScoresSubmitted, setTestScoresSubmitted] = useState(false);
  // Which test and what score — round-trips through Firestore alongside
  // testScoresSubmitted (see updateTestScores' docstring), but isn't read
  // by compute_readiness_score: readiness only cares whether scores are
  // submitted at all, not which test or what number.
  const [testKind, setTestKind] = useState<"SAT" | "ACT">("SAT");
  const [testScore, setTestScore] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [savingTestScores, setSavingTestScores] = useState(false);
  const [addingRecommender, setAddingRecommender] = useState(false);

  // Essays' edit icon navigates here with the material to edit tucked into
  // router state, rather than a query param + refetch — this page never
  // otherwise loads materials at all. Read once on mount: this state is
  // only ever set by that one navigation, never updated in place.
  const location = useLocation();
  const [editingMaterial, setEditingMaterial] = useState<StudentMaterial | null>(
    () => (location.state as { editMaterial?: StudentMaterial } | null)?.editMaterial ?? null
  );
  const addMaterialRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getColleges().then(setColleges);
    getRecommendations().then(setRecommendations);
    getTestScores().then((result) => {
      setTestScoresSubmitted(result.submitted);
      setTestKind(result.kind);
      setTestScore(result.score);
      setLoaded(true);
    });
  }, []);

  useEffect(() => {
    if (editingMaterial) {
      addMaterialRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    // Only ever needs to run once, for the material this page mounted with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleTestScoresChange(submitted: boolean) {
    if (submitted === testScoresSubmitted) return;
    setSavingTestScores(true);
    try {
      await updateTestScores({ submitted, kind: testKind, score: testScore });
      setTestScoresSubmitted(submitted);
      await recomputeReadiness();
    } finally {
      setSavingTestScores(false);
    }
  }

  // Saves kind/score as soon as either actually changes — a Select's
  // onValueChange fires once per real choice, so that one saves
  // immediately; the score Input instead saves on blur (see its onBlur
  // below) so typing a multi-digit score doesn't fire a request per
  // keystroke. Both always resend the full current state (including
  // `submitted`), same as handleTestScoresChange — the backend has no
  // notion of a partial update here (see TestScoresUpdate's docstring).
  async function handleTestKindChange(kind: "SAT" | "ACT") {
    setTestKind(kind);
    setSavingTestScores(true);
    try {
      await updateTestScores({ submitted: testScoresSubmitted, kind, score: testScore });
    } finally {
      setSavingTestScores(false);
    }
  }

  async function handleTestScoreBlur() {
    setSavingTestScores(true);
    try {
      await updateTestScores({
        submitted: testScoresSubmitted,
        kind: testKind,
        score: testScore,
      });
    } finally {
      setSavingTestScores(false);
    }
  }

  async function handleAddRecommender() {
    setAddingRecommender(true);
    try {
      const { id } = await createRecommendation({
        recommenderName: null,
        recommenderType: "Other",
        status: "NotRequested",
        collegeIds: [],
      });
      setRecommendations((prev) => [
        ...prev,
        {
          id,
          recommenderName: null,
          recommenderType: "Other",
          status: "NotRequested",
          collegeIds: [],
          requestedAt: null,
        },
      ]);
    } finally {
      setAddingRecommender(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="My Progress" />

      <SectionCard title="Standardized Test Scores" icon={GraduationCap}>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Select
              value={testKind}
              onValueChange={(value) => handleTestKindChange(value as "SAT" | "ACT")}
            >
              <SelectTrigger size="sm" className="h-8 w-24 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="SAT">SAT</SelectItem>
                <SelectItem value="ACT">ACT</SelectItem>
              </SelectContent>
            </Select>
            <Input
              value={testScore}
              onChange={(e) => setTestScore(e.target.value)}
              onBlur={handleTestScoreBlur}
              placeholder="Score"
              className="h-8 w-28 text-xs"
            />
          </div>
          <div className="flex items-center gap-3">
            {loaded && (
              <div className="inline-flex rounded-md border border-border p-0.5">
                <Button
                  type="button"
                  size="sm"
                  variant={testScoresSubmitted ? "ghost" : "secondary"}
                  onClick={() => handleTestScoresChange(false)}
                  disabled={savingTestScores}
                >
                  Not Submitted
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={testScoresSubmitted ? "secondary" : "ghost"}
                  onClick={() => handleTestScoresChange(true)}
                  disabled={savingTestScores}
                >
                  Submitted
                </Button>
              </div>
            )}
            {savingTestScores && (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Recommendations"
        icon={Users}
        action={
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleAddRecommender}
            disabled={addingRecommender}
            className="h-7 border-navy-foreground/30 bg-transparent text-navy-foreground hover:bg-navy-foreground/10 hover:text-navy-foreground"
          >
            <Plus className="h-4 w-4" /> Add Recommender
          </Button>
        }
        contentClassName={recommendations.length > 0 ? "" : "p-4"}
      >
        {recommendations.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No recommenders added yet, add one above.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {recommendations.map((rec) => (
              <RecommendationRow
                key={rec.id}
                recommendation={rec}
                colleges={colleges}
                onChange={(updated) =>
                  setRecommendations((prev) =>
                    prev.map((r) => (r.id === updated.id ? updated : r))
                  )
                }
                onDelete={(id) =>
                  setRecommendations((prev) => prev.filter((r) => r.id !== id))
                }
              />
            ))}
          </div>
        )}
      </SectionCard>

      <div ref={addMaterialRef}>
        <AddMaterialForm
          onAdded={() => {}}
          editingMaterial={editingMaterial}
          onEditComplete={() => setEditingMaterial(null)}
        />
      </div>
    </div>
  );
}
