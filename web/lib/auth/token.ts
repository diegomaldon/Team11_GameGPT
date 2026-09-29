// The current access token, readable from outside React.
//
// `lib/auth/session.tsx` is the single source of truth for the session and says
// so explicitly: nothing else should call `supabase.auth.getSession()`, because
// two readers drift apart the moment a token refreshes and the one that missed
// the event starts sending a stale JWT.
//
// `lib/api/client.ts` is not a component and cannot call `useAuth()`, but it
// needs a token to attach so server log lines can name the user (AC-1). This
// module is the bridge: AuthProvider publishes on every session change, the
// fetch client reads. Still one subscriber, still one source of truth.

let accessToken: string | null = null;

/** Called by AuthProvider on every session change. Do not call elsewhere. */
export function publishAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}
