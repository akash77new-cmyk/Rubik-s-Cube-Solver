/** Validation issues list + the set of stickers to highlight on the net. */
import { IconAlert } from "@/components/Icons";
import type { ValidationIssue } from "@/lib/types";

/** Sticker keys like "U8" (face + 0-based index) for CubeNet's `flagged` prop. */
export function flaggedStickers(
  issues: ValidationIssue[] | undefined,
  selected: number | null,
): Set<string> {
  const all = issues ?? [];
  // Out-of-range selection (the issues changed) falls back to showing everything.
  const chosen = selected !== null && selected < all.length ? [all[selected]] : all;
  return new Set(chosen.flatMap((issue) => issue.stickers.map((s) => `${s.face}${s.index}`)));
}

export function ValidationIssueList({
  issues,
  selected,
  onSelect,
}: {
  issues: ValidationIssue[];
  selected: number | null;
  onSelect: (index: number | null) => void;
}) {
  return (
    <ul className="issue-list">
      {issues.map((issue, index) => (
        <li key={`${issue.code}-${index}`}>
          <button
            type="button"
            className="issue"
            data-selected={selected === index}
            data-located={issue.stickers.length > 0}
            onClick={() => onSelect(selected === index ? null : index)}
            title={issue.stickers.length ? "Show these stickers on the net" : undefined}
          >
            <IconAlert size={12} />
            <span>{issue.message}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
