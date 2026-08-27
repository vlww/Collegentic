import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { MarkdownLite } from "@/components/MarkdownLite";
import { sendOrchestratorMessage } from "@/lib/api";

interface AddCollegeFormProps {
  /** Awaited before the loading indicator clears — Colleges.tsx uses this to
   * also refresh logos (with whatever the current picker logic is) after
   * every research pass, not just newly-added colleges, so there's no
   * separate manual "refresh logos" action. */
  onDone: () => void | Promise<void>;
  /** Fires around the request so a caller can poll for progress while it's
   * in flight — see CollegeTable's live-update polling in Colleges.tsx. */
  onLoadingChange?: (loading: boolean) => void;
}

/**
 * Sends free text straight to the Orchestrator (app/sub_agents/orchestrator_agent.py)
 * — real web research runs synchronously behind this call, so it can take a
 * minute or two per college. The Colleges page polls Firestore for the rows
 * this writes progressively while it waits (see `onLoadingChange`); the
 * Agent Activity page (Milestone 13) has the per-agent detail.
 */
export function AddCollegeForm({ onDone, onLoadingChange }: AddCollegeFormProps) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim() || loading) return;
    setLoading(true);
    onLoadingChange?.(true);
    setError(null);
    setReply(null);
    try {
      const result = await sendOrchestratorMessage(message.trim());
      setReply(result.reply);
      setMessage("");
      await onDone();
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Something went wrong reaching Collegentic. Please try again."
      );
    } finally {
      setLoading(false);
      onLoadingChange?.(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-3">
        <form onSubmit={handleSubmit} className="space-y-3">
          <label htmlFor="add-college" className="text-sm font-medium">
            What colleges are you applying to?
          </label>
          <Textarea
            id="add-college"
            placeholder="e.g. I'm applying to MIT, Princeton, and Rice University."
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={loading}
            rows={2}
          />
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={loading || !message.trim()}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Researching…
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" /> Research and add
                </>
              )}
            </Button>
            {loading && (
              <p className="text-xs text-muted-foreground">
                Real web research is running, this can take a minute or two.
              </p>
            )}
          </div>
        </form>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {reply && (
          <div className="rounded-md border border-border bg-muted/50 p-3 text-sm whitespace-pre-wrap">
            <MarkdownLite text={reply} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
