// The error every API call throws on a non-2xx response.
//
// Its own module so fixtures.ts can throw the same error as the real client
// without importing client.ts, which imports fixtures.ts.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Quote this in a bug report; it matches a server log line. */
    readonly requestId: string | null = null,
    /** The server's stable `detail.error` code, when it sent one. */
    readonly code: string | null = null,
    /** The server's `detail.message`. Written for users, safe to show as is. */
    readonly userMessage: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** `{ detail: { error, message } }` from an error response, or nulls. Never throws. */
export async function readErrorDetail(
  res: Response,
): Promise<{ code: string | null; userMessage: string | null }> {
  try {
    const body: unknown = await res.json();
    const detail = (body as { detail?: { error?: unknown; message?: unknown } })?.detail;
    return {
      code: typeof detail?.error === "string" ? detail.error : null,
      userMessage: typeof detail?.message === "string" ? detail.message : null,
    };
  } catch {
    return { code: null, userMessage: null };
  }
}
