import { useMemo, useState } from "react";
import { cn } from "@/utils";
import type { College, EssayMatch, EssayPrompt, StudentMaterial } from "@/lib/types";

interface EssayNetworkGraphProps {
  colleges: College[];
  prompts: EssayPrompt[];
  materials: StudentMaterial[];
  matches: EssayMatch[];
}

const NODE_HEIGHT = 44;
const ROW_GAP = 14;
const COLUMN_WIDTH = { college: 200, prompt: 260, material: 200 };
const COLUMN_GAP = 90;
const MARGIN_X = 40;
const MARGIN_Y = 24;

const COL_X = {
  college: MARGIN_X,
  prompt: MARGIN_X + COLUMN_WIDTH.college + COLUMN_GAP,
  material:
    MARGIN_X + COLUMN_WIDTH.college + COLUMN_GAP + COLUMN_WIDTH.prompt + COLUMN_GAP,
};
const GRAPH_WIDTH = COL_X.material + COLUMN_WIDTH.material + MARGIN_X;

/** Total SVG height needed for `rowCount` nodes stacked with margins/gaps —
 * layoutY below distributes node centers within exactly this range, so the
 * two must stay in sync or the last row clips past the SVG's own height. */
function graphHeight(rowCount: number): number {
  return 2 * MARGIN_Y + rowCount * NODE_HEIGHT + Math.max(0, rowCount - 1) * ROW_GAP;
}

/** Even vertical distribution of `count` nodes across `totalHeight`, each
 * node's full height staying within [MARGIN_Y, totalHeight - MARGIN_Y]. */
function layoutY(index: number, count: number, totalHeight: number): number {
  const topY = MARGIN_Y + NODE_HEIGHT / 2;
  const bottomY = totalHeight - MARGIN_Y - NODE_HEIGHT / 2;
  if (count <= 1) return (topY + bottomY) / 2;
  return topY + (index / (count - 1)) * (bottomY - topY);
}

function matchColor(score: number): string {
  if (score >= 70) return "var(--success)";
  if (score >= 40) return "var(--warning)";
  return "var(--destructive)";
}

/**
 * A hand-rolled SVG network view rather than a charting dependency — the
 * graph is small (colleges/prompts/materials for one student), so a plain
 * three-column layout with `foreignObject` node labels keeps this
 * dependency-free and fully themeable, consistent with the rest of the app
 * (no visualization library elsewhere in package.json).
 *
 * Three node types, per EssayMap's own spec: College -> Essay Prompt
 * (structural, thin line) -> Student Material (an EssayMatch — line
 * thickness AND color both encode match strength, redundant encoding for
 * legibility, same 70/40 thresholds as ReadinessCard/PriorityBadge).
 */
export function EssayNetworkGraph({
  colleges,
  prompts,
  materials,
  matches,
}: EssayNetworkGraphProps) {
  const [hovered, setHovered] = useState<string | null>(null);

  const rowCount = Math.max(colleges.length, prompts.length, materials.length, 1);
  const height = graphHeight(rowCount);

  const collegeY = useMemo(
    () => Object.fromEntries(colleges.map((c, i) => [c.id, layoutY(i, colleges.length, height)])),
    [colleges, height]
  );
  const promptY = useMemo(
    () => Object.fromEntries(prompts.map((p, i) => [p.id, layoutY(i, prompts.length, height)])),
    [prompts, height]
  );
  const materialY = useMemo(
    () =>
      Object.fromEntries(materials.map((m, i) => [m.id, layoutY(i, materials.length, height)])),
    [materials, height]
  );

  if (prompts.length === 0 && materials.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Add colleges (for essay prompts) and materials to see how they
        connect.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <svg
          width={GRAPH_WIDTH}
          height={height}
          viewBox={`0 0 ${GRAPH_WIDTH} ${height}`}
          className="block"
          style={{ minWidth: GRAPH_WIDTH }}
        >
          {/* College -> Prompt structural connectors */}
          {prompts.map((prompt) => {
            const cy = collegeY[prompt.collegeId];
            const py = promptY[prompt.id];
            if (cy === undefined) return null;
            return (
              <line
                key={`college-${prompt.id}`}
                x1={COL_X.college + COLUMN_WIDTH.college}
                y1={cy}
                x2={COL_X.prompt}
                y2={py}
                stroke="var(--border)"
                strokeWidth={1}
                opacity={hovered && hovered !== prompt.id && hovered !== prompt.collegeId ? 0.15 : 0.6}
              />
            );
          })}

          {/* Prompt -> Material match edges */}
          {matches.map((match) => {
            const py = promptY[match.promptId];
            const my = materialY[match.materialId];
            if (py === undefined || my === undefined) return null;
            const dimmed =
              hovered !== null && hovered !== match.promptId && hovered !== match.materialId;
            return (
              <line
                key={match.id}
                x1={COL_X.prompt + COLUMN_WIDTH.prompt}
                y1={py}
                x2={COL_X.material}
                y2={my}
                stroke={matchColor(match.matchScore)}
                strokeWidth={1 + (match.matchScore / 100) * 5}
                opacity={dimmed ? 0.15 : 0.85}
              />
            );
          })}

          {/* College nodes */}
          {colleges.map((college) => (
            <Node
              key={college.id}
              x={COL_X.college}
              y={collegeY[college.id]}
              width={COLUMN_WIDTH.college}
              onHover={setHovered}
              id={college.id}
              title={college.name}
              className="border-navy/30 bg-navy/5"
            >
              <span className="text-sm font-medium text-foreground truncate block">
                {college.name}
              </span>
            </Node>
          ))}

          {/* Prompt nodes */}
          {prompts.map((prompt) => (
            <Node
              key={prompt.id}
              x={COL_X.prompt}
              y={promptY[prompt.id]}
              width={COLUMN_WIDTH.prompt}
              onHover={setHovered}
              id={prompt.id}
              title={prompt.text}
              className="border-border bg-secondary/50"
            >
              <span className="text-xs text-foreground line-clamp-2 leading-tight">
                {prompt.text}
                {prompt.wordLimit && (
                  <span className="text-muted-foreground"> ({prompt.wordLimit}w)</span>
                )}
              </span>
            </Node>
          ))}

          {/* Material nodes */}
          {materials.map((material) => (
            <Node
              key={material.id}
              x={COL_X.material}
              y={materialY[material.id]}
              width={COLUMN_WIDTH.material}
              onHover={setHovered}
              id={material.id}
              title={material.title}
              className="border-orange/30 bg-orange-tint"
            >
              <span className="text-sm font-medium text-foreground truncate block">
                {material.title}
              </span>
            </Node>
          ))}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-border" /> College → prompt
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-full" style={{ background: "var(--success)" }} />
          Strong reuse fit
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-full" style={{ background: "var(--warning)" }} />
          Partial fit
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-full" style={{ background: "var(--destructive)" }} />
          Weak fit
        </span>
      </div>
    </div>
  );
}

interface NodeProps {
  x: number;
  y: number;
  width: number;
  id: string;
  title?: string;
  className?: string;
  onHover: (id: string | null) => void;
  children: React.ReactNode;
}

function Node({ x, y, width, id, title, className, onHover, children }: NodeProps) {
  return (
    <g onMouseEnter={() => onHover(id)} onMouseLeave={() => onHover(null)}>
      {title && <title>{title}</title>}
      <foreignObject x={x} y={y - NODE_HEIGHT / 2} width={width} height={NODE_HEIGHT}>
        <div
          className={cn(
            "h-full w-full rounded-md border px-2.5 py-1.5 flex items-center overflow-hidden",
            className
          )}
        >
          {children}
        </div>
      </foreignObject>
    </g>
  );
}
