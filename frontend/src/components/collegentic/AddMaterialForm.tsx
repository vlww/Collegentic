import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createMaterial } from "@/lib/api";
import type { MaterialType } from "@/lib/types";

interface AddMaterialFormProps {
  onAdded: () => void;
}

const TYPE_OPTIONS: { value: MaterialType; label: string }[] = [
  { value: "CommonApp", label: "Common App Essay" },
  { value: "Supplemental", label: "Supplemental Essay" },
  { value: "ActivityDescription", label: "Activity Description" },
  { value: "Award", label: "Award / Honor" },
  { value: "Note", label: "Note" },
  { value: "Idea", label: "Idea" },
];

/**
 * The only place a StudentMaterial comes into existence — metadata and the
 * student's own draft text only, never generated or edited by Collegentic
 * (.agents-cli-spec.md § Constraints: "never edited by agents"). Feeds
 * essay_analysis_agent (Milestone 11) as candidates to match against new
 * prompts.
 */
export function AddMaterialForm({ onAdded }: AddMaterialFormProps) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<MaterialType>("CommonApp");
  const [topic, setTopic] = useState("");
  const [partialText, setPartialText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      await createMaterial({
        title: title.trim(),
        type,
        topic: topic.trim() || undefined,
        partialText: partialText.trim() || undefined,
        wordCount: partialText.trim() ? partialText.trim().split(/\s+/).length : undefined,
      });
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

  return (
    <Card>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="material-title" className="text-sm font-medium">
                Title
              </label>
              <Input
                id="material-title"
                placeholder="e.g. Why I love robotics"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
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
          </div>
          <div className="space-y-1.5">
            <label htmlFor="material-topic" className="text-sm font-medium">
              Topic <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <Input
              id="material-topic"
              placeholder="e.g. Overcoming stage fright before a debate final"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="material-text" className="text-sm font-medium">
              Draft or excerpt{" "}
              <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <Textarea
              id="material-text"
              placeholder="Paste what you have so far. Collegentic only reads it, never edits it."
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
              ) : (
                <>
                  <Plus className="h-4 w-4" /> Add material
                </>
              )}
            </Button>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </form>
      </CardContent>
    </Card>
  );
}
