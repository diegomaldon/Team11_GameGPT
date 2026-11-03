// What the Library's Refresh is doing, platform by platform. REQ006 · TM11-60.
//
// Progress while a sync runs, what each finished one imported, and the failures with
// one Retry for just those platforms. When nothing has run yet, each platform's last
// sync time.
import type { LibraryRefresh, PlatformStatus } from "../../lib/library/useLibraryRefresh";
import type { RefreshPlatform } from "../../lib/library/libraryRefresh";
import { Button } from "../ui";
import { Check, Spinner } from "../icons";

const LABEL: Record<RefreshPlatform, string> = { steam: "Steam", xbox: "Xbox" };

export function RefreshStatus({ refresh }: { refresh: LibraryRefresh }) {
  const entries = Object.entries(refresh.statuses) as [RefreshPlatform, PlatformStatus][];
  if (entries.length === 0) {
    return refresh.lastSynced.length > 0 ? (
      <p className="-mt-3 mb-4 text-xs text-[var(--ink-faint)]">
        {refresh.lastSynced.map((line) => (
          <span key={line} className="mr-3 inline-block">
            {line}
          </span>
        ))}
      </p>
    ) : null;
  }

  const failed = entries.filter(([, s]) => s.state === "failed");
  const others = entries.filter(([, s]) => s.state !== "failed");

  return (
    <div className="mb-4 space-y-2 text-[13px]">
      {others.length > 0 && (
        <ul className="space-y-1.5 rounded-xl bg-neutral-50 px-3 py-2.5">
          {others.map(([platform, status]) =>
            status.state === "running" ? (
              <li
                key={platform}
                role="status"
                aria-live="polite"
                className="flex items-center gap-2"
              >
                <Spinner className="h-4 w-4 text-[var(--ink-soft)]" />
                {status.label}
              </li>
            ) : (
              <li key={platform} className="flex items-center gap-2">
                <Check className="h-4 w-4 text-emerald-700" />
                {status.state === "succeeded" && status.message}
              </li>
            ),
          )}
          {refresh.epicNote && <li className="text-[var(--ink-faint)]">{refresh.epicNote}</li>}
        </ul>
      )}
      {failed.length > 0 && (
        <div role="alert" className="rounded-xl bg-rose-50 px-3 py-2.5 text-rose-700">
          {failed.map(([platform, status]) => (
            <p key={platform}>{status.state === "failed" && status.message}</p>
          ))}
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            onClick={refresh.retry}
            disabled={refresh.refreshing}
          >
            Retry {failed.map(([platform]) => LABEL[platform]).join(" and ")}
          </Button>
        </div>
      )}
    </div>
  );
}
