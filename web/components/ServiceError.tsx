// "Service unavailable" panel with a retry, for search, detail and history (TM11-77).
// The wording comes from lib/api/failureState.ts, never from the error itself.

import type { FailureState } from "@/lib/api/failureState";
import { Button, cx } from "./ui";

export function ServiceError({
  failure,
  onRetry,
}: {
  failure: FailureState;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className={cx(
        "flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-200",
        "bg-rose-50 px-5 py-4 text-sm text-rose-700",
      )}
    >
      <div className="min-w-0">
        <p className="font-semibold">{failure.title}</p>
        <p className="mt-0.5">{failure.message}</p>
      </div>
      <Button size="sm" variant="secondary" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
