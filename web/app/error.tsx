"use client";

// Route-level error boundary. (AC-2)
//
// React render errors never reach window.onerror, so without this file a
// crashed page shows Next's default screen and reports nothing. `global-error.tsx`
// sits above it and catches failures in the root layout itself.

import { useEffect } from "react";
import { getLastRequestId, reportClientError } from "@/lib/observability";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportClientError(error, "react-boundary");
  }, [error]);

  const requestId = getLastRequestId();

  return (
    <main className="mx-auto flex min-h-[60vh] max-w-md flex-col justify-center gap-4 px-6 text-center">
      <h1 className="font-display text-2xl font-semibold">Something broke</h1>
      <p className="text-sm text-neutral-600">
        The page hit an error. Trying again often works.
      </p>
      {requestId && (
        // Give the user something to quote. It matches a server log line and a
        // sink event, which turns "it broke" into a searchable id.
        <p className="font-mono text-xs text-neutral-400">ref {requestId}</p>
      )}
      <button
        onClick={reset}
        className="mx-auto rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white"
      >
        Try again
      </button>
    </main>
  );
}
