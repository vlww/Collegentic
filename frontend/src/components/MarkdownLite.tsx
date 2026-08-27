import { Fragment } from "react";

/** Renders **bold**, *italic*, and `code` spans as real elements instead of
 * literal asterisks/backticks — a safety net for agent replies that are
 * meant to be plain prose but occasionally slip in markdown syntax. */
const INLINE_TOKEN = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`/g;

export function MarkdownLite({ text }: { text: string }) {
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  INLINE_TOKEN.lastIndex = 0;
  while ((match = INLINE_TOKEN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(<Fragment key={key++}>{text.slice(lastIndex, match.index)}</Fragment>);
    }
    const [, bold, italic, code] = match;
    if (bold !== undefined) {
      nodes.push(<strong key={key++}>{bold}</strong>);
    } else if (italic !== undefined) {
      nodes.push(<em key={key++}>{italic}</em>);
    } else if (code !== undefined) {
      nodes.push(
        <code key={key++} className="rounded bg-secondary px-1 py-0.5 text-xs">
          {code}
        </code>
      );
    }
    lastIndex = INLINE_TOKEN.lastIndex;
  }
  if (lastIndex < text.length) {
    nodes.push(<Fragment key={key++}>{text.slice(lastIndex)}</Fragment>);
  }

  return <>{nodes}</>;
}
