import type { NextRequest } from "next/server";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * REQ010 · TM11-44.
 *
 * The Steam OpenID realm and return_to must be absolute URLs on the host the user is
 * actually visiting. On Vercel the incoming request URL is the internal one, so behind the
 * proxy `request.nextUrl.origin` can be wrong — the forwarded headers carry the public
 * host. Reading them here is what lets the same code work on the deployed environment and on
 * localhost without a hardcoded base URL (AC4).
 */
export function originFromRequest(request: NextRequest): string {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (host) {
    const proto =
      request.headers.get("x-forwarded-proto") ??
      (host.startsWith("localhost") || host.startsWith("127.0.0.1") ? "http" : "https");
    return `${proto}://${host}`;
  }
  // No proxy in front (plain `next dev`): the request URL origin is already correct.
  return request.nextUrl.origin;
}
