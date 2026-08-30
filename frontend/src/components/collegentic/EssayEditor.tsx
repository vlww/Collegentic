import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Pencil, Save, SpellCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SectionCard } from "@/components/collegentic/SectionCard";
import { GrammarCheckProgressBar } from "@/components/collegentic/GrammarCheckProgressBar";
import { checkGrammar, updateMaterial } from "@/lib/api";
import type { GrammarIssue, StudentMaterial } from "@/lib/types";

interface EssayEditorProps {
  materials: StudentMaterial[];
  /** Called after a successful save so the parent (Essays.tsx) can refresh
   * whatever else depends on material text — e.g. the Essay Map's
   * best-fit matches, which read StudentMaterial.partialText indirectly
   * via the categorizer. */
  onSaved: (material: StudentMaterial) => void;
}

interface TextSegment {
  text: string;
  issue?: GrammarIssue;
}

/**
 * Locates each flagged issue's exact text within the essay, left to right,
 * skipping any issue whose `original` can no longer be found (already
 * fixed) and any overlap past an earlier match. Recomputed from scratch off
 * `text` + `issues` on every render — no stored character offsets to drift
 * out of sync after a fix is applied.
 */
function buildSegments(text: string, issues: GrammarIssue[]): TextSegment[] {
  const matches: { start: number; end: number; issue: GrammarIssue }[] = [];
  for (const issue of issues) {
    if (!issue.original) continue;
    const start = text.indexOf(issue.original);
    if (start === -1) continue;
    matches.push({ start, end: start + issue.original.length, issue });
  }
  matches.sort((a, b) => a.start - b.start);

  const segments: TextSegment[] = [];
  let pos = 0;
  for (const match of matches) {
    if (match.start < pos) continue;
    if (match.start > pos) segments.push({ text: text.slice(pos, match.start) });
    segments.push({ text: text.slice(match.start, match.end), issue: match.issue });
    pos = match.end;
  }
  if (pos < text.length) segments.push({ text: text.slice(pos) });
  return segments;
}

/**
 * A minimal, focused grammar checker for one essay at a time — select a
 * material, run a quick grammar-only pass (Gemma finds the mistakes,
 * Gemini validates/structures them — see agent/app/tools/grammar_check.py),
 * then hover a flagged span for the fix and click to accept it. Grammar/
 * spelling/punctuation only, never tone or content feedback — this doesn't
 * "coach" the essay, matching .agents-cli-spec.md's essay-content-reasoning
 * constraint in spirit.
 *
 * Deliberately swaps between two plain modes rather than overlaying
 * highlights on a live-editable surface: a `<Textarea>` for free typing, and
 * a read-only highlighted view for reviewing/accepting flagged mistakes.
 * Editing switches back to the textarea (and drops any remaining issues,
 * since further typing can move or remove the text they point at) rather
 * than trying to keep highlight positions valid against concurrent edits.
 */
export function EssayEditor({ materials, onSaved }: EssayEditorProps) {
  const editable = useMemo(
    () => materials.filter((m) => (m.partialText ?? "").trim().length > 0),
    [materials]
  );
  // "" means nothing selected — deliberately never auto-picks an essay, and
  // never falls back to some OTHER essay on its own either (see the reset
  // effect below): a silent fallback is exactly what let deleting the
  // selected essay leave this component showing one essay's stale text
  // under a dropdown that had already jumped to a different one.
  const [materialId, setMaterialId] = useState<string>("");
  const material = materialId ? editable.find((m) => m.id === materialId) ?? null : null;

  const [text, setText] = useState("");
  const [mode, setMode] = useState<"edit" | "review">("edit");
  const [issues, setIssues] = useState<GrammarIssue[]>([]);
  const [checkedOnce, setCheckedOnce] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    setText(material?.partialText ?? "");
    setMode("edit");
    setIssues([]);
    setCheckedOnce(false);
    setError(null);
    setSavedAt(null);
    // Only reset when the SELECTED essay id actually changes — `material`
    // itself is a fresh object every render (derived from `materials`), so
    // keying off `materialId` avoids wiping in-progress edits on every
    // parent refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [materialId]);

  // The selected essay can disappear out from under the dropdown — deleted
  // via "Your Materials", or edited down to empty text — without the
  // dropdown's own value ever changing. Clearing back to "nothing
  // selected" (not silently jumping to some other essay) is what the reset
  // effect above then picks up to blank the editor out cleanly.
  useEffect(() => {
    if (materialId && !editable.some((m) => m.id === materialId)) {
      setMaterialId("");
    }
  }, [materialId, editable]);

  const segments = useMemo(() => buildSegments(text, issues), [text, issues]);

  async function handleCheckGrammar() {
    if (!text.trim() || analyzing) return;
    setAnalyzing(true);
    setError(null);
    try {
      const result = await checkGrammar(text);
      setIssues(result);
      setCheckedOnce(true);
      setMode(result.length > 0 ? "review" : "edit");
    } catch {
      setError("Grammar check hit an error. Please try again.");
    } finally {
      setAnalyzing(false);
    }
  }

  function applyIssue(issue: GrammarIssue) {
    const start = text.indexOf(issue.original);
    if (start === -1) return;
    setText(
      text.slice(0, start) + issue.suggestion + text.slice(start + issue.original.length)
    );
    setIssues((prev) => prev.filter((i) => i !== issue));
  }

  function backToEditing() {
    setMode("edit");
    setIssues([]);
  }

  async function handleSave() {
    if (!material || saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMaterial(material.id, {
        title: material.title,
        type: material.type,
        topic: material.topic ?? undefined,
        partialText: text,
        wordCount: text.trim() ? text.trim().split(/\s+/).length : undefined,
      });
      setSavedAt(Date.now());
      onSaved(updated);
    } catch {
      setError("Couldn't save the essay. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (editable.length === 0) {
    return (
      <SectionCard title="Essay Editor" icon={SpellCheck}>
        <p className="text-sm text-muted-foreground">
          Add an essay with some draft text from My Progress to check it for grammar
          mistakes.
        </p>
      </SectionCard>
    );
  }

  return (
    <SectionCard title="Essay Editor" icon={SpellCheck}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Select value={materialId} onValueChange={setMaterialId}>
            <SelectTrigger className="w-full sm:w-72">
              <SelectValue placeholder="Select an essay" />
            </SelectTrigger>
            <SelectContent>
              {editable.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {mode === "review" ? (
            <Button type="button" variant="secondary" onClick={backToEditing}>
              <Pencil className="h-4 w-4" /> Edit essay
            </Button>
          ) : (
            <Button
              type="button"
              onClick={handleCheckGrammar}
              disabled={analyzing || !material || !text.trim()}
            >
              <SpellCheck className="h-4 w-4" />
              {analyzing ? "Checking grammar…" : "Check grammar"}
            </Button>
          )}

          {checkedOnce && !analyzing && mode === "edit" && issues.length === 0 && (
            <span className="flex items-center gap-1.5 text-sm text-success">
              <CheckCircle2 className="h-4 w-4" /> No grammar issues found.
            </span>
          )}
          {mode === "review" && (
            <span className="text-xs text-muted-foreground">
              {issues.length === 0
                ? "All flagged mistakes fixed."
                : `${issues.length} issue${issues.length === 1 ? "" : "s"} found. Hover a highlight for the fix.`}
            </span>
          )}
        </div>

        {analyzing && <GrammarCheckProgressBar />}

        {mode === "edit" ? (
          <Textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setCheckedOnce(false);
              setIssues([]);
            }}
            disabled={analyzing || !material}
            placeholder={material ? undefined : "Select an essay above to begin editing."}
            rows={14}
            className="font-normal leading-6"
          />
        ) : (
          <div className="min-h-[18rem] whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-sm leading-6">
            {segments.map((seg, i) =>
              seg.issue ? (
                <GrammarHighlight
                  key={i}
                  segment={seg}
                  issue={seg.issue}
                  onApply={() => applyIssue(seg.issue!)}
                />
              ) : (
                <span key={i}>{seg.text}</span>
              )
            )}
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={handleSave}
            disabled={saving || !material}
          >
            <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save essay"}
          </Button>
          {savedAt && <span className="text-xs text-muted-foreground">Saved.</span>}
        </div>
      </div>
    </SectionCard>
  );
}

function GrammarHighlight({
  segment,
  issue,
  onApply,
}: {
  segment: TextSegment;
  issue: GrammarIssue;
  onApply: () => void;
}) {
  return (
    <span className="group relative rounded-sm bg-[color-mix(in_srgb,var(--orange)_35%,transparent)] underline decoration-orange decoration-2 underline-offset-2">
      {segment.text}
      <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 hidden w-max max-w-xs -translate-x-1/2 flex-col items-start gap-1 rounded-md border border-border bg-popover p-2 text-xs shadow-md group-hover:flex group-focus-within:flex">
        <button
          type="button"
          onClick={onApply}
          className="pointer-events-auto rounded bg-navy px-2 py-1 text-left font-medium text-navy-foreground hover:opacity-90"
        >
          {issue.suggestion}
        </button>
        <span className="text-left text-muted-foreground">{issue.explanation}</span>
      </span>
    </span>
  );
}
