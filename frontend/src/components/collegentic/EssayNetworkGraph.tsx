import { useEffect, useMemo, useRef, useState } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { collegeAccentColor, schoolAccentStyle } from "./CollegeAvatar";
import type { College, EssayMatch, EssayPrompt, StudentMaterial } from "@/lib/types";

interface EssayNetworkGraphProps {
  colleges: College[];
  prompts: EssayPrompt[];
  materials: StudentMaterial[];
  matches: EssayMatch[];
}

// Every real match gets a node — the old "top N" and "N per college" caps
// both ended up hiding matches the student actually wanted to see (found
// live: a genuinely-classified "greatest obstacle" essay just never
// appeared because its college already had 2-3 stronger matches taking its
// slots). This is a sanity ceiling only, nowhere near what a real account
// hits — the actual fan-out control lives on the backend now (see
// essay_matching.py's _RELATED_MATCH_CLOSE_FRACTION).
const MAX_VISIBLE_MATCHES = 60;

// Bubble sizes, spacing forces (below), and CANVAS_MARGIN were all trimmed
// down together — found live: the force-settled layout was routinely wider
// than the card, so render-time scale-to-fit (see `scale` below) was
// shrinking every node well below these nominal sizes just to fit. Smaller
// bubbles lower forceCollide's own hard floor on how close two nodes can
// sit (not just a spacing-force tweak, an actual smaller minimum distance),
// which is what let the tighter spacing forces below actually compact the
// layout instead of immediately hitting that collide floor — the two only
// compound this way if changed together.
//
// Trimmed a second time — found live (measured directly, not just by
// inspection): forceCollide's floor is `PROMPT_RADIUS + MATERIAL_RADIUS`,
// and for essentially every real match score, `linkDistance` below asked
// for something SHORTER than that floor — meaning collide, not the match
// score, was the thing actually deciding every link's length, and every
// match (a 95% fit and a 55% fit alike) settled at the exact same
// distance. The two levers: `PAD` (the invisible buffer added past each
// box's own half-WIDTH, not the box's visible size — see PROMPT_RADIUS/
// MATERIAL_RADIUS below), cut hard (10 -> 3); and WIDTH itself, trimmed
// more mildly to protect the line-clamped label text inside each bubble.
// HEIGHT is NOT part of this: the collision radius below is derived from
// WIDTH alone (both bubbles are treated as circles sized by their half-
// width for the physics, regardless of their actual box height), so a
// first attempt at also shrinking PROMPT_HEIGHT bought zero compaction
// and only cost text — a school name that wraps to 2 lines (e.g.
// "University of Texas at Austin") plus 2 lines of prompt text needs the
// original ~72px to not overflow its own box. Verified against both a
// small real profile (6 links: an 800x795 layout dropped to 564x497, and
// every link actually shortened instead of all landing on the same
// collide-floor distance) and a larger synthetic one (16 links, 6
// colleges: 797x910 -> 766x633).
const PROMPT_WIDTH = 138;
const PROMPT_HEIGHT = 72;
const MATERIAL_WIDTH = 116;
const MATERIAL_HEIGHT = 32;
const CANVAS_MARGIN = 24;
const NODE_RADIUS_PAD = 3;
const PROMPT_RADIUS = PROMPT_WIDTH / 2 + NODE_RADIUS_PAD;
const MATERIAL_RADIUS = MATERIAL_WIDTH / 2 + NODE_RADIUS_PAD;

// How far apart a match's two nodes settle, continuously across the whole
// score range — a 95% fit and a 5% fit are visibly different distances,
// not just "at the floor" vs "drifted out" (a two-tier version of this
// made every strong match sit at an identical distance, which read as
// static/artificial no matter how the rest of the layout varied). A d3
// force simulation (same idea as networkX's spring_layout: edges are
// springs whose rest length is set here, nodes repel each other, and the
// whole system relaxes into equilibrium) is what actually lets nodes land
// at these distances instead of forcing them onto a fixed ring — that's
// also what breaks up the "everything in a perfect circle" look a purely
// radial layout always has, since a node's final position depends on
// every match pulling on it, not just its own hub's ring math.
const MIN_LINK_DISTANCE = 25;
const MAX_LINK_DISTANCE = 95;

function linkDistance(score: number): number {
  const t = Math.min(1, Math.max(0, (100 - score) / 100));
  return MIN_LINK_DISTANCE + t * (MAX_LINK_DISTANCE - MIN_LINK_DISTANCE);
}

function matchColor(score: number): string {
  if (score >= 70) return "var(--success)";
  if (score >= 40) return "var(--warning)";
  return "var(--destructive)";
}

function selectVisibleMatches(matches: EssayMatch[]): EssayMatch[] {
  return [...matches].sort((a, b) => b.matchScore - a.matchScore).slice(0, MAX_VISIBLE_MATCHES);
}

/** The short label a prompt is actually known by — real Requirement text
 * tends to read like `"Main Personal Statement: 'Tell us your story...'"`
 * or `"Major-Specific Supplemental Prompt (Arts, Entertainment...)"`, and a
 * word-limit annotation is almost always parenthetical too (`"...(150
 * words)"`). Cutting at the first `:` or `(` keeps just the label a student
 * would actually call this prompt — concise on purpose, the bubble has no
 * room for the quoted prompt text itself (hover still shows it in full via
 * the node's native title). Text with neither delimiter (a short prompt
 * with no label prefix) is kept as-is; line-clamp in the bubble handles it. */
function promptLabel(text: string): string {
  const cut = text.search(/[:(]/);
  const label = cut === -1 ? text : text.slice(0, cut);
  return label.trim() || text.trim();
}

interface GraphNode extends SimulationNodeDatum {
  id: string;
  radius: number;
  kind: "prompt" | "material";
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  match: EssayMatch;
}

interface Layout {
  width: number;
  height: number;
  positions: Map<string, { x: number; y: number }>;
}

// Two materials never share an edge (matches only ever run material <->
// prompt), so `forceManyBody`'s uniform repulsion is the only thing
// keeping them apart — not nearly enough once both have several matches
// pulling them toward the same neighborhood of prompts, which is exactly
// what read as "one big cluster" (found live: personal statement and
// greatest-challenge essays, each with their own prompts, still ended up
// nearly on top of each other). A dedicated force that only pushes
// material nodes away from *other* material nodes (ignored below this
// distance) fixes that specifically, without changing how tightly a
// prompt sits to the material it's actually connected to.
const MATERIAL_SEPARATION = 95;

function materialSeparationForce(nodes: GraphNode[]) {
  const materials = nodes.filter((n) => n.kind === "material");
  return (alpha: number) => {
    for (let i = 0; i < materials.length; i++) {
      for (let j = i + 1; j < materials.length; j++) {
        const a = materials[i];
        const b = materials[j];
        const dx = (b.x ?? 0) - (a.x ?? 0);
        const dy = (b.y ?? 0) - (a.y ?? 0);
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
        if (dist >= MATERIAL_SEPARATION) continue;
        const push = ((MATERIAL_SEPARATION - dist) / dist) * alpha * 0.6;
        const ox = dx * push;
        const oy = dy * push;
        a.x = (a.x ?? 0) - ox;
        a.y = (a.y ?? 0) - oy;
        b.x = (b.x ?? 0) + ox;
        b.y = (b.y ?? 0) + oy;
      }
    }
  };
}

/** Runs a force simulation (nodes repel each other via `forceManyBody`,
 * `forceCollide` keeps bubbles from overlapping, matched pairs are pulled
 * toward `linkDistance(score)` apart via `forceLink`) to equilibrium
 * synchronously — this isn't an animated graph, so ticking it out fully up
 * front and using the settled positions is simpler than driving a
 * requestAnimationFrame loop for something that has to be readable the
 * instant it renders. Initial positions are seeded on a deterministic ring
 * (by index, not Math.random) purely so the simulation has somewhere to
 * start from — the actual final layout comes entirely from the physics,
 * not the seed. */
function layoutGraph(
  promptNodes: { id: string }[],
  materialNodes: { id: string }[],
  links: { source: string; target: string; match: EssayMatch }[]
): Layout {
  const nodes: GraphNode[] = [
    ...promptNodes.map((p) => ({ id: p.id, radius: PROMPT_RADIUS, kind: "prompt" as const })),
    ...materialNodes.map((m) => ({ id: m.id, radius: MATERIAL_RADIUS, kind: "material" as const })),
  ];
  const seedRadius = Math.max(200, nodes.length * 22);
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, nodes.length);
    node.x = seedRadius * Math.cos(angle);
    node.y = seedRadius * Math.sin(angle);
  });

  const simLinks: GraphLink[] = links.map((l) => ({
    source: l.source,
    target: l.target,
    match: l.match,
  }));

  if (nodes.length === 0) {
    return { width: 0, height: 0, positions: new Map() };
  }

  const simulation = forceSimulation(nodes)
    // Less mutual repulsion than before — the whole point of this pass is a
    // denser layout: less repulsion means less distance for forceX/forceY
    // to have to fight down to zero once collide+link settle, so the graph
    // relaxes into a visibly tighter cluster instead of a wide-open one
    // scale-to-fit then has to shrink hard to make room for.
    .force("charge", forceManyBody().strength(-80))
    .force(
      "link",
      forceLink<GraphNode, GraphLink>(simLinks)
        .id((d) => d.id)
        .distance((d) => linkDistance(d.match.matchScore))
        .strength(0.9)
    )
    .force("collide", forceCollide<GraphNode>().radius((d) => d.radius).strength(1))
    // Pulling harder toward center horizontally than vertically still
    // biases the whole graph toward a taller, narrower shape (nodes that
    // don't have to stack side by side stack top to bottom instead, which
    // keeps this fitting the card's width — see the render-time
    // scale-to-fit below). But too weak a vertical pull leaves a
    // lightly-connected sub-cluster (an essay with just one or two
    // matches, nothing tying it back to the rest of the graph) drifting
    // far enough from everything else to read as empty space, not just a
    // taller layout — found live, a "why this major" essay's own small
    // cluster sat with a visible gap above the rest of the map. Strong
    // enough to close that gap, still well under the horizontal pull so
    // the shape doesn't go back to wide. Both raised alongside the lower
    // charge/link/separation values above, so the extra pull-to-center
    // compounds with the reduced repulsion rather than just compensating
    // for it back to the same size.
    .force("x", forceX(0).strength(0.13))
    .force("y", forceY(0).strength(0.11))
    .force("materialSeparation", materialSeparationForce(nodes))
    .stop();

  for (let i = 0; i < 400; i++) simulation.tick();

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    minX = Math.min(minX, x - node.radius);
    maxX = Math.max(maxX, x + node.radius);
    minY = Math.min(minY, y - node.radius);
    maxY = Math.max(maxY, y + node.radius);
  }

  const offsetX = CANVAS_MARGIN - minX;
  const offsetY = CANVAS_MARGIN - minY;
  const positions = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    positions.set(node.id, { x: (node.x ?? 0) + offsetX, y: (node.y ?? 0) + offsetY });
  }

  return {
    width: maxX - minX + CANVAS_MARGIN * 2,
    height: maxY - minY + CANVAS_MARGIN * 2,
    positions,
  };
}

/**
 * A hand-rolled SVG force-directed graph rather than a charting dependency
 * beyond d3-force itself (small, headless — it computes positions only, no
 * rendering/DOM opinions of its own) — the graph is small (a handful of
 * matches for one student), so this stays fully themeable and consistent
 * with the rest of the app while getting real physics-based layout instead
 * of hand-rolled ring math. Same idea as networkX's spring_layout: every
 * EssayMatch is a spring between its prompt and material node, whose rest
 * length encodes the match score (see linkDistance) — a strong fit settles
 * close, a weak one settles far, continuously, not in two visual tiers.
 * Nodes that aren't connected to each other repel, so unrelated
 * prompt/material pairs never drift near enough to look connected.
 *
 * A prompt bubble is still color-coded to its own college (see
 * CollegeAvatar's collegeAccentColor) with the school's name on it — that
 * identity doesn't drive placement, only its match distances do. A line
 * from material to prompt is an EssayMatch: thickness AND color both
 * encode match strength (redundant encoding for legibility, same 70/40
 * thresholds as ReadinessCard/PriorityBadge).
 */
export function EssayNetworkGraph({
  colleges,
  prompts,
  materials,
  matches,
}: EssayNetworkGraphProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  // The graph's natural (force-settled) size is whatever the physics needs
  // — often wider than the card. Scaling the whole thing down to fit the
  // card's actual width (see `scale` below) is what keeps every node on
  // screen with no horizontal scrollbar, instead of clipping or requiring
  // a scroll to see the rest of the map.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setContainerWidth(width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // `materials`/`matches` come from two separate fetches (see Essays.tsx's
  // handleDeleteMaterial: `materials` updates synchronously, `matches` only
  // catches up once its own refetch resolves) — for one render after a
  // delete, `matches` can still reference a materialId that's already gone
  // from `materials`. Grounding against the CURRENT id sets before a match
  // is ever used to build a d3-force link is what stops that stale
  // reference from reaching forceLink at all. Found live: forceLink's own
  // `find()` throws a synchronous "node not found" the instant a link
  // points at an id missing from `nodes` — an uncaught render-time
  // exception with no recovery but a full reload. Same "never trust a
  // reference id without confirming the referenced thing still exists"
  // discipline the backend already applies to LLM-emitted ids (see e.g.
  // conflict_agent.py/essay_matching_agent.py), just applied here against
  // ordinary fetch staleness instead.
  const materialIds = useMemo(() => new Set(materials.map((m) => m.id)), [materials]);
  const promptIds = useMemo(() => new Set(prompts.map((p) => p.id)), [prompts]);
  const groundedMatches = useMemo(
    () => matches.filter((m) => materialIds.has(m.materialId) && promptIds.has(m.promptId)),
    [matches, materialIds, promptIds]
  );

  // Only a fair, capped slice of matches makes the map at all (see
  // selectVisibleMatches) — a prompt or material with no match among them
  // just isn't drawn, same "no connection yet = not worth showing" idea as
  // before, now also the mechanism that keeps a big college list legible
  // without starving any one school out of the map entirely.
  const visibleMatches = useMemo(() => selectVisibleMatches(groundedMatches), [groundedMatches]);
  const visiblePromptIds = useMemo(
    () => new Set(visibleMatches.map((m) => m.promptId)),
    [visibleMatches]
  );
  const visibleMaterialIds = useMemo(
    () => new Set(visibleMatches.map((m) => m.materialId)),
    [visibleMatches]
  );
  // A prompt can have more than one match now — its own category plus any
  // related one (see essay_matching.py's recompute_essay_matches) — so a
  // hovered prompt's detail popover lists all of them, strongest first.
  const matchesByPrompt = useMemo(() => {
    const map = new Map<string, EssayMatch[]>();
    for (const match of visibleMatches) {
      const list = map.get(match.promptId);
      if (list) list.push(match);
      else map.set(match.promptId, [match]);
    }
    for (const list of map.values()) list.sort((a, b) => b.matchScore - a.matchScore);
    return map;
  }, [visibleMatches]);
  const materialById = useMemo(
    () => Object.fromEntries(materials.map((m) => [m.id, m])),
    [materials]
  );
  const collegeById = useMemo(() => Object.fromEntries(colleges.map((c) => [c.id, c])), [colleges]);
  const visiblePrompts = useMemo(
    () => prompts.filter((p) => visiblePromptIds.has(p.id)),
    [prompts, visiblePromptIds]
  );
  const visibleMaterials = useMemo(
    () => materials.filter((m) => visibleMaterialIds.has(m.id)),
    [materials, visibleMaterialIds]
  );

  const layout = useMemo(
    () =>
      layoutGraph(
        visiblePrompts.map((p) => ({ id: p.id })),
        visibleMaterials.map((m) => ({ id: m.id })),
        visibleMatches.map((match) => ({
          source: match.materialId,
          target: match.promptId,
          match,
        }))
      ),
    [visiblePrompts, visibleMaterials, visibleMatches]
  );
  const scale =
    containerWidth > 0 && layout.width > 0 ? Math.min(1, containerWidth / layout.width) : 1;

  if (visiblePrompts.length === 0 && visibleMaterials.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {materials.length === 0
          ? "Add materials to see how they connect."
          : "None of your materials share a category with a college's essay prompt yet. Try editing one from My Progress, or add a new one for that category."}
      </p>
    );
  }

  // Hovering a prompt node (not a material one) surfaces its match detail
  // right there instead of a separate "Suggested Matches" table — `hovered`
  // only ever equals a prompt's own id while a prompt node is moused over
  // (see Node's onMouseEnter below), so this is naturally empty otherwise.
  const hoveredPrompt = visiblePrompts.find((p) => p.id === hovered);
  const hoveredMatches = hoveredPrompt ? matchesByPrompt.get(hoveredPrompt.id) : undefined;
  const hoveredPromptPos = hoveredPrompt ? layout.positions.get(hoveredPrompt.id) : undefined;

  return (
    <div className="space-y-3">
      {/* No horizontal scroll — the whole graph is scaled down (via CSS
          transform, so the SVG *and* the HTML tooltip inside it stay in
          sync) to fit the card's actual width, see `scale` above. The
          outer ref div is what ResizeObserver measures; its height is
          pinned to the *scaled* size so the shrunk content doesn't leave
          blank space below it. */}
      <div ref={containerRef} className="overflow-hidden rounded-md border border-border/60">
        <div
          className="relative mx-auto"
          style={{ width: layout.width * scale, height: layout.height * scale }}
        >
          <div
            style={{
              width: layout.width,
              height: layout.height,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          >
            <svg
              width={layout.width}
              height={layout.height}
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              className="block"
            >
              {/* Material -> Prompt match edges */}
              {visibleMatches.map((match) => {
                const mp = layout.positions.get(match.materialId);
                const pp = layout.positions.get(match.promptId);
                if (!mp || !pp) return null;
                const dimmed =
                  hovered !== null && hovered !== match.promptId && hovered !== match.materialId;
                return (
                  <line
                    key={match.id}
                    x1={mp.x}
                    y1={mp.y}
                    x2={pp.x}
                    y2={pp.y}
                    stroke={matchColor(match.matchScore)}
                    strokeWidth={1 + (match.matchScore / 100) * 5}
                    opacity={dimmed ? 0.15 : 0.85}
                  />
                );
              })}

              {/* Prompt bubbles */}
              {visiblePrompts.map((prompt) => {
                const pos = layout.positions.get(prompt.id);
                const college = collegeById[prompt.collegeId];
                if (!pos || !college) return null;
                const accent = collegeAccentColor(college);
                return (
                  <Node
                    key={prompt.id}
                    x={pos.x}
                    y={pos.y}
                    width={PROMPT_WIDTH}
                    height={PROMPT_HEIGHT}
                    onHover={setHovered}
                    id={prompt.id}
                    title={`${college.name}: ${prompt.text}`}
                  >
                    <div
                      className="school-tint flex h-full w-full flex-col overflow-hidden rounded-xl border-2 shadow-sm"
                      style={{ borderColor: accent, ...schoolAccentStyle(college) }}
                    >
                      <div
                        className="line-clamp-2 px-2.5 pt-1.5 text-[10px] font-bold uppercase leading-tight tracking-wide"
                        style={{ color: accent }}
                      >
                        {college.name}
                      </div>
                      <div className="flex-1 overflow-hidden px-2.5 pb-1.5 pt-0.5 text-[11px] font-medium leading-tight text-foreground">
                        <span className="line-clamp-2">{promptLabel(prompt.text)}</span>
                      </div>
                    </div>
                  </Node>
                );
              })}

              {/* Material bubbles */}
              {visibleMaterials.map((material) => {
                const pos = layout.positions.get(material.id);
                if (!pos) return null;
                return (
                  <Node
                    key={material.id}
                    x={pos.x}
                    y={pos.y}
                    width={MATERIAL_WIDTH}
                    height={MATERIAL_HEIGHT}
                    onHover={setHovered}
                    id={material.id}
                    title={material.title}
                  >
                    <div
                      className="school-tint flex h-full w-full items-center justify-center overflow-hidden rounded-full border-2 border-orange/40 px-3 shadow-sm"
                      style={{ "--school-accent": "var(--orange)" } as React.CSSProperties}
                    >
                      <span className="truncate text-center text-xs font-medium text-foreground">
                        {material.title}
                      </span>
                    </div>
                  </Node>
                );
              })}
            </svg>

            {hoveredPrompt && hoveredMatches && hoveredPromptPos && (
              <PromptMatchTooltip
                x={hoveredPromptPos.x}
                y={hoveredPromptPos.y}
                canvasWidth={layout.width}
                canvasHeight={layout.height}
                matches={hoveredMatches}
                materialById={materialById}
              />
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-full" style={{ background: "var(--success)" }} />
          Strong reuse fit
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-full" style={{ background: "var(--warning)" }} />
          Partial fit
        </span>
      </div>
    </div>
  );
}

interface NodeProps {
  x: number;
  y: number;
  width: number;
  height: number;
  id: string;
  title?: string;
  onHover: (id: string | null) => void;
  children: React.ReactNode;
}

function Node({ x, y, width, height, id, title, onHover, children }: NodeProps) {
  return (
    <g onMouseEnter={() => onHover(id)} onMouseLeave={() => onHover(null)}>
      {title && <title>{title}</title>}
      <foreignObject x={x - width / 2} y={y - height / 2} width={width} height={height}>
        <div className="h-full w-full">{children}</div>
      </foreignObject>
    </g>
  );
}

const TOOLTIP_WIDTH = 240;

interface PromptMatchTooltipProps {
  x: number;
  y: number;
  canvasWidth: number;
  canvasHeight: number;
  matches: EssayMatch[];
  materialById: Record<string, StudentMaterial>;
}

/**
 * Replaces the old standalone "Suggested Matches" table — hovering a
 * prompt bubble is now the only place to see its match detail, right next
 * to the connection(s) it explains instead of a separate list to
 * cross-reference. A prompt can have more than one match now (its own
 * category plus a related one — see essay_matching.py), so this lists all
 * of them, strongest first. Force layout puts bubbles anywhere on the
 * canvas (not just around fixed hubs), so this clamps horizontally to the
 * canvas bounds and flips above/below based on which half of the canvas
 * the bubble sits in, rather than a single fixed offset direction.
 */
function PromptMatchTooltip({
  x,
  y,
  canvasWidth,
  canvasHeight,
  matches,
  materialById,
}: PromptMatchTooltipProps) {
  const left = Math.min(Math.max(x - TOOLTIP_WIDTH / 2, 8), canvasWidth - TOOLTIP_WIDTH - 8);
  const placeAbove = y > canvasHeight / 2;
  return (
    <div
      className="absolute z-10 divide-y divide-border rounded-md border border-border bg-popover p-3 text-xs shadow-lg pointer-events-none"
      style={{
        left,
        width: TOOLTIP_WIDTH,
        top: placeAbove ? undefined : y + PROMPT_HEIGHT / 2 + 10,
        bottom: placeAbove ? canvasHeight - (y - PROMPT_HEIGHT / 2 - 10) : undefined,
      }}
    >
      {matches.map((match) => {
        const material = materialById[match.materialId];
        if (!material) return null;
        return (
          <div key={match.id} className="py-1.5 first:pt-0 last:pb-0">
            <p className="font-medium text-popover-foreground">
              {Math.round(match.matchScore)}% fit with {material.title}
            </p>
            <p className="mt-1 font-medium" style={{ color: matchColor(match.matchScore) }}>
              {match.recommendation === "adapt" ? "Adapt existing" : "Write new"}
            </p>
            <p className="mt-1 text-muted-foreground">{match.reasoning}</p>
          </div>
        );
      })}
    </div>
  );
}
