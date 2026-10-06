// Live status of a library import (TM11-49): progress while it runs, the titles
// that could not be imported, and a clear "nothing changed" message on failure.
import type { LibrarySyncJob } from "../../lib/api/types";
import { Button, cx } from "../ui";
import { Check, Spinner } from "../icons";

export const FAILED_RUN_MESSAGE = "Import failed. Your previous library is unchanged.";

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function SyncProgress({
  job,
  error,
  onRetry,
}: {
  job: LibrarySyncJob | null;
  error?: string | null;
  onRetry?: () => void;
}) {
  if (!job && !error) return null;

  if (error || job?.state === "failed") {
    return (
      <div role="alert" className="mt-4 rounded-xl bg-rose-50 px-3 py-2.5 text-[13px] text-rose-700">
        {/* job.error is the server's user_message (e.g. a private Steam profile), safe to render as is. */}
        <p>{error ?? job?.error ?? FAILED_RUN_MESSAGE}</p>
        {onRetry && (
          <Button variant="secondary" size="sm" className="mt-2" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  const j = job!;
  const total = j.total ?? 0;
  const processed = j.processed ?? 0;
  const failed = j.failed ?? [];
  const done = j.state === "succeeded";
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  const label =
    j.state === "queued" || j.state === "fetching"
      ? "Fetching your library from Steam…"
      : done
        ? `Imported ${plural(j.synced ?? 0, "game")}.`
        : `Importing ${processed} of ${plural(total, "game")}…`;

  return (
    <div className="mt-4 rounded-xl bg-neutral-50 px-3 py-3 text-[13px]">
      <p role="status" aria-live="polite" className="flex items-center gap-2 font-medium">
        {done ? (
          <Check className="h-4 w-4 text-emerald-700" />
        ) : (
          <Spinner className="h-4 w-4 text-[var(--ink-soft)]" />
        )}
        {label}
      </p>
      {!done && (
        <div
          role="progressbar"
          aria-label="Library import progress"
          aria-valuemin={0}
          aria-valuemax={total || undefined}
          aria-valuenow={total ? processed : undefined}
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-neutral-200"
        >
          <div
            className={cx(
              "h-full rounded-full bg-accent-600 transition-[width] duration-300",
              !total && "w-1/4 animate-pulse",
            )}
            style={total ? { width: `${pct}%` } : undefined}
          />
        </div>
      )}
      {failed.length > 0 && (
        <details className="mt-2 text-[var(--ink-soft)]">
          <summary className="cursor-pointer">
            {plural(failed.length, "title")} couldn&apos;t be imported
            {done ? "" : " so far"}. The rest {done ? "were" : "are being"} imported.
          </summary>
          <ul className="mt-1.5 list-disc pl-5">
            {failed.map((f, i) => (
              <li key={`${f.steam_appid ?? "x"}-${i}`}>
                {f.title ?? (f.steam_appid != null ? `App ${f.steam_appid}` : "Unknown title")}
                <span className="text-[var(--ink-faint)]"> ({f.reason})</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
