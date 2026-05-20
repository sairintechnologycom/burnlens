import { Fragment, type ReactNode } from "react";

export function slugify(heading: string): string {
  return heading
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function renderInline(line: string, key: number): ReactNode {
  const parts = line.split(/(`[^`]+`)/g);
  return (
    <Fragment key={key}>
      {parts.map((part, i) => {
        if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
          return <code key={i}>{part.slice(1, -1)}</code>;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </Fragment>
  );
}

export function renderChunkText(text: string): ReactNode[] {
  const blocks = text.split(/\n\n+/);
  return blocks.map((block, bi) => {
    const lines = block.split("\n");

    if (lines.every((l) => /^\s*-\s+/.test(l))) {
      return (
        <ul key={bi}>
          {lines.map((l, li) => (
            <li key={li}>{renderInline(l.replace(/^\s*-\s+/, ""), 0)}</li>
          ))}
        </ul>
      );
    }

    if (lines.every((l) => /^\s*\d+\.\s+/.test(l))) {
      return (
        <ol key={bi}>
          {lines.map((l, li) => (
            <li key={li}>{renderInline(l.replace(/^\s*\d+\.\s+/, ""), 0)}</li>
          ))}
        </ol>
      );
    }

    return (
      <p key={bi}>
        {lines.map((line, li) => (
          <Fragment key={li}>
            {li > 0 && <br />}
            {renderInline(line, li)}
          </Fragment>
        ))}
      </p>
    );
  });
}
