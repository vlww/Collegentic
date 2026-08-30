import type * as PdfJsLib from "pdfjs-dist";

/** What AddMaterialForm needs to create a StudentMaterial straight from an
 * uploaded PDF — no manual entry required. */
export interface ExtractedMaterial {
  title: string;
  topic: string | null;
  text: string;
  wordCount: number;
}

function stripLabel(line: string, label: "title" | "topic"): string {
  return line.replace(new RegExp(`^${label}\\s*[:\\-]\\s*`, "i"), "").trim();
}

interface PdfLine {
  /** The line's y-coordinate on its page (PDF space — larger is higher up
   * the page), rounded for stable row-grouping. Only comparable to another
   * line's `y` on the SAME page; `newPage` is what marks the boundary
   * where that comparison stops applying. */
  y: number;
  text: string;
  /** Rightmost x-extent reached by this line's text (x of the last run
   * plus its width). This is the signal that actually distinguishes a
   * mid-paragraph line wrap from a real paragraph end — see joinParagraphs. */
  rightEdge: number;
  /** True for the first line of every page after the first — a page break
   * carries no usable y-coordinate relationship to the previous page's
   * last line, so paragraph reconstruction (see joinParagraphs) never
   * compares gaps or right-edges across one. */
  newPage: boolean;
}

/** Reassembles a page's text items into visual lines by grouping items that
 * share a y-coordinate (pdf.js's `getTextContent` returns text runs, not
 * lines — there's no line break in the data itself, just each run's
 * position on the page). Runs sharing a row are then ordered left to right. */
function linesFromTextContent(
  content: Awaited<ReturnType<PdfJsLib.PDFPageProxy["getTextContent"]>>
): { y: number; text: string; rightEdge: number }[] {
  const rows = new Map<number, { x: number; str: string; width: number }[]>();
  for (const item of content.items) {
    if (!("str" in item) || !item.str.trim()) continue;
    const y = Math.round(item.transform[5]);
    const run = { x: item.transform[4], str: item.str, width: item.width ?? 0 };
    const row = rows.get(y);
    if (row) row.push(run);
    else rows.set(y, [run]);
  }
  return [...rows.entries()]
    .sort(([a], [b]) => b - a)
    .map(([y, row]) => {
      const sorted = [...row].sort((a, b) => a.x - b.x);
      const last = sorted[sorted.length - 1];
      return {
        y,
        text: sorted.map((r) => r.str).join(" ").trim(),
        rightEdge: last.x + last.width,
      };
    })
    .filter((row) => row.text);
}

/**
 * Turns a flat list of visual lines back into real paragraphs. PDF text
 * extraction has no notion of "paragraph" — only where each line sits on
 * the page — so a student's essay wrapping across several lines within one
 * paragraph looks, positionally, almost identical to consecutive lines:
 * both are just "the next line down." Found live: a pure vertical-gap
 * heuristic (treat a bigger-than-normal gap as a paragraph break) isn't
 * enough on its own — plenty of real essay PDFs are single-spaced with NO
 * extra blank-line gap between paragraphs at all, so every line-wrap looks
 * identical to a paragraph break by vertical gap alone, and the essay still
 * came out one line per "paragraph."
 *
 * The reliable signal instead is how far each line's text reaches across
 * the page. A line that's part of a paragraph and about to wrap fills as
 * much of the column as it can before word-wrapping to the next line — its
 * right edge lands close to the document's full text width. A line that
 * ends a paragraph almost never does (the last line of a paragraph is
 * usually well short of the margin, since only whatever text remains
 * flows onto it) — that's true even for fully justified text, since
 * justification never stretches a paragraph's final line. So: a line whose
 * right edge falls short of the document's typical full-line width is
 * treated as ending its paragraph; the line after it starts a new one.
 * The vertical-gap check runs too, as a second, independent signal (still
 * catches things like a centered heading or an extra blank line) — either
 * one alone is enough to call a paragraph break.
 *
 * "Full line width" is the MAX right-edge seen anywhere in the document
 * (not an average/median, which paragraph-ending short lines would pull
 * down) — any line reaching within 8% of that max is "full," anything
 * short of it ends its paragraph. A page boundary always just continues
 * the current paragraph with a space, since neither signal is comparable
 * across two different pages' coordinate spaces.
 *
 * Neither signal alone is sufficient, though — found live: a short line OR
 * gap can land mid-sentence too (e.g. a short line right before a dash or
 * an em-dash-interrupted clause), which broke a paragraph apart mid-thought
 * ("I would memorize every" / "sentence, terrified..."). A paragraph can
 * only genuinely end where a SENTENCE ends, so a break additionally
 * requires the previous line's text to end in terminal punctuation
 * (./!/?, optionally followed by a closing quote/paren) — this is an AND
 * with the gap/width signal above, not an OR, since terminal punctuation
 * alone is common mid-paragraph too (most sentences in a paragraph end
 * with a period without starting a new paragraph).
 *
 * A single "\n" marks the break, not a blank line — the essay text field
 * renders with `white-space: pre-wrap`, where "\n\n" reads as an extra
 * blank line between paragraphs; the student's own PDF only ever had one.
 */
const _SENTENCE_END_RE = /[.!?]["'’”)]*$/;

function joinParagraphs(lines: PdfLine[]): string {
  if (lines.length === 0) return "";

  const gaps: number[] = [];
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].newPage) continue;
    gaps.push(lines[i - 1].y - lines[i].y);
  }
  const sortedGaps = [...gaps].sort((a, b) => a - b);
  const medianGap = sortedGaps.length > 0 ? sortedGaps[Math.floor(sortedGaps.length / 2)] : 0;
  const gapThreshold = medianGap * 1.5;

  const maxRightEdge = Math.max(...lines.map((l) => l.rightEdge));
  const fullLineThreshold = maxRightEdge * 0.92;

  let result = lines[0].text;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    const prev = lines[i - 1];
    if (line.newPage) {
      result += " " + line.text;
      continue;
    }
    const gap = prev.y - line.y;
    const gapBreak = medianGap > 0 && gap > gapThreshold;
    const shortLineBreak = prev.rightEdge < fullLineThreshold;
    const sentenceEnded = _SENTENCE_END_RE.test(prev.text);
    const isParagraphBreak = (gapBreak || shortLineBreak) && sentenceEnded;
    result += (isParagraphBreak ? "\n" : " ") + line.text;
  }
  return result;
}

/**
 * Pulls a title, topic, and body out of an uploaded essay PDF. Assumes the
 * student's PDF puts the title and topic each on their own line at the top
 * of the document (optionally prefixed "Title:"/"Topic:") — the first
 * non-blank line is the title, the second is the topic, everything after is
 * the draft text (reconstructed into real paragraphs — see joinParagraphs).
 * Throws if the PDF has no extractable text at all.
 */
export async function extractMaterialFromPdf(file: File): Promise<ExtractedMaterial> {
  // Dynamically imported (rather than at module load) so pdf.js — over a
  // megabyte of parser plus its worker — only ever ends up in a chunk the
  // browser fetches when a student actually uploads a PDF, not in the main
  // bundle every visitor downloads on page load.
  const [pdfjsLib, { default: pdfWorkerUrl }] = await Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
  ]);
  pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

  const buffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;

  const lines: PdfLine[] = [];
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum);
    const content = await page.getTextContent();
    linesFromTextContent(content).forEach((row, i) => {
      lines.push({ ...row, newPage: i === 0 && pageNum > 1 });
    });
  }

  if (lines.length === 0) {
    throw new Error(`${file.name} has no extractable text`);
  }

  const title = stripLabel(lines[0].text, "title");
  const topicLine = lines[1] ? stripLabel(lines[1].text, "topic") : "";
  const text = joinParagraphs(lines.slice(2));

  return {
    title,
    topic: topicLine || null,
    text,
    wordCount: text ? text.split(/\s+/).filter(Boolean).length : 0,
  };
}
