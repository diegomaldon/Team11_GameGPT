// Client-side observability. (AC-2)
//
// Browser errors are POSTed to the API's /api/client-error, which feeds the
// same sink as server errors. That is what makes "one place" true without
// giving the frontend its own Sentry DSN: one config value, set once, on the
// server, and nothing secret in the client bundle.
//
// Correlation works because the API echoes `x-request-id` back on every
// response and `lib/api/client.ts` generates one per call. A client error that
// followed a failed request carries that same id, so both sides of the failure
// line up in the sink.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** The id of the most recent API call, attached to whatever fails next. */
let lastRequestId: string | null = null;

export function newRequestId(): string {
  // randomUUID needs a secure context; plain http://<lan-ip>:3000 on a phone
  // (REQ039 tests this) is not one, so the fallback is load-bearing.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return Array.from({ length: 32 }, () =>
    Math.floor(Math.random() * 16).toString(16),
  ).join("");
}

export function setLastRequestId(id: string | null): void {
  lastRequestId = id;
}

export function getLastRequestId(): string | null {
  return lastRequestId;
}

// A tight loop that throws would otherwise DOS our own API with reports.
let reportsThisSession = 0;
const MAX_REPORTS = 25;
const recentlySeen = new Set<string>();

type ReportKind = "error" | "unhandledrejection" | "react-boundary";

export function reportClientError(
  error: unknown,
  kind: ReportKind = "error",
): void {
  const err = error instanceof Error ? error : new Error(String(error));
  const fingerprint = `${kind}:${err.message}`;

  if (reportsThisSession >= MAX_REPORTS || recentlySeen.has(fingerprint)) return;
  reportsThisSession += 1;
  recentlySeen.add(fingerprint);

  const body = JSON.stringify({
    message: err.message.slice(0, 1000),
    stack: err.stack?.slice(0, 8000) ?? null,
    kind,
    // Query strings can carry auth fragments from OAuth callbacks; path only.
    url: typeof location !== "undefined" ? location.pathname : null,
    user_agent:
      typeof navigator !== "undefined" ? navigator.userAgent.slice(0, 500) : null,
  });

  // keepalive so a report survives the navigation that an error often causes.
  // Never await, never throw: reporting a failure must not create one.
  void fetch(`${API_URL}/api/client-error`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-request-id": lastRequestId ?? newRequestId(),
    },
    body,
    keepalive: true,
  }).catch(() => {
    /* API unreachable — the console still has it */
  });
}

let installed = false;

/** Catch what React's error boundaries cannot: async throws and rejections. */
export function installGlobalErrorHandlers(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  window.addEventListener("error", (event) => {
    reportClientError(event.error ?? event.message, "error");
  });

  window.addEventListener("unhandledrejection", (event) => {
    reportClientError(event.reason, "unhandledrejection");
  });
}
