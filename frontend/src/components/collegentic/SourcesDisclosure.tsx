import { useState } from "react";
import { ExternalLink, ShieldCheck, ShieldQuestion } from "lucide-react";
import { getResearchSources } from "@/lib/api";
import type { ResearchSource } from "@/lib/types";

/**
 * "View Source" — .agents-cli-spec.md § Source Transparency: every
 * researched requirement should let the student see source, URL, date
 * researched, confidence, and whether it was official. Fetches lazily
 * (only once expanded) since most requirements are never inspected.
 */
export function SourcesDisclosure({ sourceIds }: { sourceIds: string[] }) {
  const [sources, setSources] = useState<ResearchSource[] | null>(null);
  const [loading, setLoading] = useState(false);

  if (sourceIds.length === 0) {
    return <span className="text-xs text-muted-foreground">No source on file</span>;
  }

  return (
    <details
      className="text-xs"
      onToggle={async (e) => {
        if (e.currentTarget.open && sources === null) {
          setLoading(true);
          try {
            setSources(await getResearchSources(sourceIds));
          } finally {
            setLoading(false);
          }
        }
      }}
    >
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">
        View source{sourceIds.length > 1 ? `s (${sourceIds.length})` : ""}
      </summary>
      <div className="mt-2 space-y-2 border-l-2 border-border pl-3">
        {loading && <p className="text-muted-foreground">Loading…</p>}
        {sources?.map((source) => (
          <div key={source.id} className="space-y-0.5">
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-medium text-foreground hover:underline"
            >
              {source.title}
              <ExternalLink className="h-3 w-3" />
            </a>
            <div className="flex items-center gap-2 text-muted-foreground">
              {source.official ? (
                <span className="inline-flex items-center gap-1 text-success">
                  <ShieldCheck className="h-3 w-3" /> Official source
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-warning">
                  <ShieldQuestion className="h-3 w-3" /> Secondary source
                </span>
              )}
              <span>·</span>
              <span>Researched {new Date(source.dateResearched).toLocaleDateString()}</span>
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
