import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { sendOrchestratorMessage } from "@/lib/api";

interface AddCollegeFormProps {
  onDone: () => void;
}

/**
 * Sends free text straight to the Orchestrator (app/sub_agents/orchestrator_agent.py)
 * — real web research runs synchronously behind this call, so it can take a
 * minute or two per college. No streaming/progress yet (that's the Agent
 * Activity page, Milestone 13); this just says so plainly while it waits.
 */
export function AddCollegeForm({ onDone }: AddCollegeFormProps) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim() || loading) return;
    setLoading(true);
    setError(null);
    setReply(null);
    try {
      const result = await sendOrchestratorMessage(message.trim());
      setReply(result.reply);
      setMessage("");
      onDone();
    } catch {
      setError("Something went wrong reaching Collegentic. Please try again.");
    } finally {
      setLoading(false);
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
                Real web research is running — this can take a minute or two per college.
              </p>
            )}
          </div>
        </form>
        {error && <p className="text-sm text-destructive">{error}</p>}
        {reply && (
          <div className="rounded-md border border-border bg-muted/50 p-3 text-sm whitespace-pre-wrap">
            {reply}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
