"use client";

// Last-resort boundary: catches errors thrown by the root layout, which
// app/error.tsx cannot because it renders inside that layout. Must ship its
// own <html>/<body> — at this point the real ones failed to render.

import { useEffect } from "react";
import { reportClientError } from "@/lib/observability";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportClientError(error, "react-boundary");
  }, [error]);

  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui", padding: "3rem", textAlign: "center" }}>
        <h1 style={{ fontSize: "1.25rem" }}>GameGPT failed to load</h1>
        <p style={{ color: "#666", fontSize: "0.875rem" }}>
          The error has been reported.
        </p>
        <button onClick={reset} style={{ marginTop: "1rem" }}>
          Reload
        </button>
      </body>
    </html>
  );
}
