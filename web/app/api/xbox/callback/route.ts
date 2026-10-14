import { NextResponse, type NextRequest } from "next/server";
import {
  XBOX_LINK_COOKIE,
  XBOX_LINK_TTL_SECONDS,
  XBOX_STATE_COOKIE,
  XBOX_VERIFIER_COOKIE,
  XboxLinkError,
  exchangeCode,
  getXboxIdentity,
  parseXboxCallback,
  sealIdentity,
  xboxConfigFromEnv,
  xboxLinkedAccountsResult,
} from "@/lib/auth/xbox";
import { originFromRequest } from "@/lib/auth/request-origin";

/**
 * GameGPT · E2 Platform Linking & Library Sync
 * Xbox linking, second half. REQ014 · TM11-53.
 *
 * GET /api/xbox/callback is where Microsoft sends the user back. Every outcome, including a
 * cancel or an account Xbox Live refuses, ends in a redirect to /settings carrying a reason
 * the page turns into a message (AC2). On success the verified XUID and gamertag are sealed
 * into a short-lived signed cookie, never the URL, and the page finishes the link with
 * POST /api/xbox/link using its own session (AC1).
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function safeDecode(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const origin = originFromRequest(request);
  const params = request.nextUrl.searchParams;

  const rawState = params.get("state") ?? "";
  // state is "<uuid>" or "<uuid>.<encoded next>"; a UUID never contains a dot.
  const dot = rawState.indexOf(".");
  const returnedState = dot === -1 ? rawState : rawState.slice(0, dot);
  const next = dot === -1 ? null : safeDecode(rawState.slice(dot + 1));

  const finish = (path: string, sealed?: string) => {
    const response = NextResponse.redirect(new URL(path, origin));
    response.cookies.delete({ name: XBOX_STATE_COOKIE, path: "/api/xbox" });
    response.cookies.delete({ name: XBOX_VERIFIER_COOKIE, path: "/api/xbox" });
    if (sealed) {
      response.cookies.set(XBOX_LINK_COOKIE, sealed, {
        httpOnly: true,
        sameSite: "lax",
        secure: origin.startsWith("https://"),
        path: "/api/xbox",
        maxAge: XBOX_LINK_TTL_SECONDS,
      });
    }
    return response;
  };

  const config = xboxConfigFromEnv();
  if (!config) return finish(xboxLinkedAccountsResult("error", { reason: "config", next }));

  // Anti-CSRF: the state minted at /login must come back unchanged, with its verifier.
  const expectedState = request.cookies.get(XBOX_STATE_COOKIE)?.value;
  const verifier = request.cookies.get(XBOX_VERIFIER_COOKIE)?.value;
  if (!expectedState || !verifier || expectedState !== returnedState) {
    return finish(xboxLinkedAccountsResult("error", { reason: "state", next }));
  }

  const parsed = parseXboxCallback(params);
  if (parsed.status === "cancelled") {
    return finish(xboxLinkedAccountsResult("cancelled", { next }));
  }
  if (parsed.status === "error") {
    return finish(xboxLinkedAccountsResult("error", { reason: parsed.reason, next }));
  }

  try {
    const msToken = await exchangeCode({
      code: parsed.code,
      verifier,
      redirectUri: new URL("/api/xbox/callback", origin).toString(),
      config,
    });
    const identity = await getXboxIdentity(msToken);
    return finish(xboxLinkedAccountsResult("verified", { next }), sealIdentity(identity, config));
  } catch (err) {
    const reason = err instanceof XboxLinkError ? err.reason : "auth";
    if (!(err instanceof XboxLinkError)) {
      console.error("[xbox] unexpected callback failure", { message: String(err) });
    }
    return finish(xboxLinkedAccountsResult("error", { reason, next }));
  }
}
