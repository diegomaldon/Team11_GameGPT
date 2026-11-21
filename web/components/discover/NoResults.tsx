// The no-results state on Discover (TM11-77, CIS453 search rainy-day scenario): says
// nothing matched, suggests rephrasing or broadening, and offers the example queries.
// Picking one hands it back to fill the search field, the same as the examples under it.

import { EXAMPLE_PROMPTS } from "@/lib/discover/featured";
import { cx } from "../ui";

export function NoResults({
  message,
  onPick,
}: {
  /** Why nothing came back: the API's notice, or the generic rephrasing tip. */
  message: string;
  onPick: (prompt: string) => void;
}) {
  return (
    <div
      role="status"
      className={cx(
        "mb-5 rounded-3xl border border-[var(--border)] bg-[var(--surface)] px-6 py-8",
        "text-center",
      )}
    >
      <h2 className="font-display text-[28px]">No matches found</h2>
      <p className="mx-auto mt-2 max-w-md text-[15px] text-[var(--ink-soft)]">{message}</p>
      <p className="mt-5 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--label)]">
        Or try one of these
      </p>
      <ul className="mt-2.5 flex flex-wrap justify-center gap-2">
        {EXAMPLE_PROMPTS.map(({ prompt }) => (
          <li key={prompt}>
            <button
              type="button"
              onClick={() => onPick(prompt)}
              className={cx(
                "min-h-11 rounded-full border border-[var(--border-strong)] px-4 text-sm",
                "text-[var(--ink)] transition-colors hover:bg-[var(--raised-2)]",
              )}
            >
              {prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
