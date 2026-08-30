import { useEffect, useRef, useState } from "react";
import { FilePlus2, Loader2, Plus, Save, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SectionCard } from "@/components/collegentic/SectionCard";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createMaterial, updateMaterial } from "@/lib/api";
import { extractMaterialFromPdf } from "@/lib/pdf";
import type { MaterialType, StudentMaterial } from "@/lib/types";

interface AddMaterialFormProps {
  onAdded: () => void;
  /** Pre-fills the form to edit this material instead of creating a new
   * one — set once, from Essays' edit icon navigating here with the
   * material in router state (see Progress.tsx). Nothing in "Your
   * Materials" changes until the student actually submits. */
  editingMaterial?: StudentMaterial | null;
  /** Called after a successful update, so the parent drops back to "add"
   * mode instead of staying on this same material indefinitely. */
  onEditComplete?: () => void;
}

const TYPE_OPTIONS: { value: MaterialType; label: string }[] = [
  { value: "CommonApp", label: "Common App Essay" },
  { value: "Supplemental", label: "Supplemental Essay" },
  { value: "ActivityDescription", label: "Activity Description" },
  { value: "Award", label: "Award / Honor" },
  { value: "Note", label: "Note" },
  { value: "Idea", label: "Idea" },
];

type InputMode = "manual" | "pdf";

/**
 * The only place a StudentMaterial comes into existence — metadata and the
 * student's own draft text only, never generated or edited by Collegentic
 * (.agents-cli-spec.md § Constraints: "never edited by agents"). Feeds
 * essay_analysis_agent (Milestone 11) as candidates to match against new
 * prompts.
 *
 * Adding a new material starts with nothing chosen in the "Upload type"
 * dropdown and nothing else on screen — picking Manual upload or PDF
 * upload is what reveals the matching fields, rather than showing both (or
 * defaulting to one) up front. Title/Topic only ever apply to the manual
 * path (each PDF gets its own title/topic parsed straight out of the file,
 * see handlePdfUpload below), so they're only ever shown there.
 */
export function AddMaterialForm({
  onAdded,
  editingMaterial,
  onEditComplete,
}: AddMaterialFormProps) {
  const [title, setTitle] = useState(editingMaterial?.title ?? "");
  const [type, setType] = useState<MaterialType>(editingMaterial?.type ?? "CommonApp");
  const [topic, setTopic] = useState(editingMaterial?.topic ?? "");
  const [partialText, setPartialText] = useState(editingMaterial?.partialText ?? "");
  // "" means nothing chosen yet — editing an existing material only ever
  // means editing its text directly (there's no "replace this material's
  // text with a new PDF" flow), so the dropdown itself only renders while
  // adding new; editingMaterial short-circuits straight to manual below.
  const [inputMode, setInputMode] = useState<InputMode | "">("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResults, setUploadResults] = useState<
    { name: string; status: "ok" | "error"; detail: string }[]
  >([]);
  const pdfInputRef = useRef<HTMLInputElement>(null);

  // editingMaterial only ever changes once in practice (arrives via router
  // state on mount) — this just keeps the form in sync if it does.
  useEffect(() => {
    if (!editingMaterial) return;
    setTitle(editingMaterial.title);
    setType(editingMaterial.type);
    setTopic(editingMaterial.topic ?? "");
    setPartialText(editingMaterial.partialText ?? "");
  }, [editingMaterial]);

  const manualMode = Boolean(editingMaterial) || inputMode === "manual";
  const pdfMode = !editingMaterial && inputMode === "pdf";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const input = {
        title: title.trim(),
        type,
        topic: topic.trim() || undefined,
        partialText: partialText.trim() || undefined,
        wordCount: partialText.trim() ? partialText.trim().split(/\s+/).length : undefined,
      };
      if (editingMaterial) {
        await updateMaterial(editingMaterial.id, input);
        onEditComplete?.();
      } else {
        await createMaterial(input);
      }
      setTitle("");
      setTopic("");
      setPartialText("");
      onAdded();
    } catch {
      setError("Something went wrong saving this. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  /** Lets a student drop in several essay PDFs at once instead of retyping
   * each one — each file becomes its own StudentMaterial via createMaterial
   * (see .agents-cli-spec.md § Constraints: materials are still only ever
   * created by the student, just from a PDF instead of the form fields),
   * with title/topic pulled straight out of the PDF's own first two lines
   * (see lib/pdf.ts) rather than asked for again. All files in one batch
   * share whatever Type is currently selected above.
   */
  async function handlePdfUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    setUploading(true);
    setUploadResults([]);
    const results: typeof uploadResults = [];
    for (const file of files) {
      try {
        const extracted = await extractMaterialFromPdf(file);
        if (!extracted.title) {
          throw new Error("couldn't find a title on the first line");
        }
        await createMaterial({
          title: extracted.title,
          type,
          topic: extracted.topic ?? undefined,
          partialText: extracted.text || undefined,
          wordCount: extracted.wordCount || undefined,
        });
        results.push({ name: file.name, status: "ok", detail: extracted.title });
      } catch (err) {
        results.push({
          name: file.name,
          status: "error",
          detail: err instanceof Error ? err.message : "Something went wrong",
        });
      }
    }
    setUploadResults(results);
    setUploading(false);
    if (results.some((r) => r.status === "ok")) onAdded();
  }

  const typeField = (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium">Type</label>
      <Select value={type} onValueChange={(v) => setType(v as MaterialType)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {TYPE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <SectionCard
      title={editingMaterial ? "Edit Essay or Material" : "Add an Essay or Material"}
      icon={FilePlus2}
    >
      <form onSubmit={handleSubmit} className="space-y-2.5">
        {!editingMaterial && (
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">Upload type</label>
            <Select
              value={inputMode}
              onValueChange={(v) => setInputMode(v as InputMode)}
            >
              <SelectTrigger className="sm:w-56">
                <SelectValue placeholder="Select upload type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="manual">Manual upload</SelectItem>
                <SelectItem value="pdf">PDF upload</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        {manualMode && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="material-title" className="text-sm font-medium">
                  Title
                </label>
                <Input
                  id="material-title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={loading}
                />
              </div>
              {typeField}
            </div>

            <div className="space-y-1.5">
              <label htmlFor="material-topic" className="text-sm font-medium">
                Topic <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <Input
                id="material-topic"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="material-text" className="text-sm font-medium">
                Essay Draft{" "}
                <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <Textarea
                id="material-text"
                value={partialText}
                onChange={(e) => setPartialText(e.target.value)}
                disabled={loading}
                rows={4}
              />
            </div>

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={loading || !title.trim()}>
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Saving…
                  </>
                ) : editingMaterial ? (
                  <>
                    <Save className="h-4 w-4" /> Update material
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4" /> Add material
                  </>
                )}
              </Button>
            </div>
          </>
        )}

        {pdfMode && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              {typeField}
              <Button
                type="button"
                variant="secondary"
                disabled={uploading}
                onClick={() => pdfInputRef.current?.click()}
                className="h-9 hover:bg-[color-mix(in_srgb,var(--secondary)_85%,black)]"
              >
                <Upload className="h-3.5 w-3.5" /> Upload files here
              </Button>
              <input
                ref={pdfInputRef}
                id="material-pdf-upload"
                type="file"
                accept="application/pdf"
                multiple
                className="hidden"
                disabled={uploading}
                onChange={handlePdfUpload}
              />
            </div>
            {(uploading || uploadResults.length > 0) && (
              <div className="space-y-0.5">
                {uploading && (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> Reading and adding…
                  </p>
                )}
                {uploadResults.length > 0 && (
                  <ul className="space-y-0.5 text-sm">
                    {uploadResults.map((r, i) => (
                      <li
                        key={i}
                        className={
                          r.status === "ok" ? "text-muted-foreground" : "text-destructive"
                        }
                      >
                        {r.status === "ok"
                          ? `Added "${r.detail}" (${r.name})`
                          : `${r.name}: ${r.detail}`}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </SectionCard>
  );
}
