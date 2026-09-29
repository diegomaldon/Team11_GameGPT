"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "../supabase";
import { publishAccessToken } from "./token";

/**
 * GameGPT · E2 Identity & Account Management
 * Session persistence and refresh. REQ001 / REQ002.
 *
 * This is the single source of truth for "is someone signed in". Nothing else in the app
 * should call supabase.auth.getSession() directly — two readers of the same session drift
 * apart the moment a token refreshes, and the one that missed the event starts sending a
 * stale JWT.
 *
 * Three behaviours are load-bearing:
 *
 *  1. The session outlives a reload and a browser restart. That comes from
 *     persistSession in lib/supabase.ts (localStorage), not from anything here. What
 *     this module adds is reading it back before the first paint decides anything.
 *  2. Expired access tokens refresh without the user noticing, via autoRefreshToken.
 *     We subscribe to the result rather than polling.
 *  3. Sign-out revokes server-side, not just locally. See `signOut`.
 */

/**
 * `loading` is a real state, not a detail to paper over. Treating "we haven't checked yet"
 * as "signed out" is what makes an auth gate flash the sign-in page at users who are in
 * fact signed in, and it is the single most common bug in this pattern.
 */
export type AuthStatus = "loading" | "authenticated" | "anonymous";

export type AuthContextValue = {
  status: AuthStatus;
  session: Session | null;
  user: User | null;
  /** Revokes the session everywhere and clears local storage. */
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  // getSession() resolves after onAuthStateChange has already fired in some orderings.
  // Without this guard the slower initial read can overwrite a newer event and sign the
  // user back out a tick after they signed out.
  const resolved = useRef(false);

  useEffect(() => {
    let active = true;

    function apply(next: Session | null) {
      if (!active) return;
      resolved.current = true;
      setSession(next);
      setStatus(next ? "authenticated" : "anonymous");
      // Mirror the token into a plain module so lib/api/client.ts can attach it
      // without becoming a second getSession() caller. This function is the only
      // place the session changes, so it is the only place that needs the line.
      publishAccessToken(next?.access_token ?? null);
    }

    // Reads the persisted session out of localStorage and refreshes it if the access
    // token has already expired — which is the browser-restart case (AC1).
    supabase.auth
      .getSession()
      .then(({ data, error }) => {
        if (error) {
          // A corrupt or revoked stored session lands here. Treat it as signed out
          // rather than leaving the app stuck on a loading screen forever.
          console.error("[auth] getSession failed", {
            name: error.name,
            message: error.message,
          });
          apply(null);
          return;
        }
        if (!resolved.current) apply(data.session);
      })
      .catch(() => {
        if (!resolved.current) apply(null);
      });

    // Fires on SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED, USER_UPDATED and on the PKCE
    // exchange in /auth/callback. TOKEN_REFRESHED is AC2: the refresh happens inside
    // supabase-js on its own timer and we just take the new session.
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, next) => {
      apply(next);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  const signOut = useCallback(async () => {
    // scope 'global' revokes every refresh token for this user, so a session copied to
    // another device dies too. The default ('local') only clears this browser, which
    // leaves a stolen refresh token valid — that is the AC4 "revokes the session" half.
    const { error } = await supabase.auth.signOut({ scope: "global" });

    if (error) {
      // Offline, or the refresh token was already revoked server-side. Either way the
      // local session is gone and keeping the user "signed in" would be wrong, so fall
      // through to the local clear rather than surfacing a failure they cannot act on.
      console.error("[auth] signOut failed, clearing locally", {
        name: error.name,
        message: error.message,
      });
    }

    // onAuthStateChange delivers SIGNED_OUT, but set it here too so callers can navigate
    // immediately without waiting for the event to land.
    setSession(null);
    setStatus("anonymous");
    publishAccessToken(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, session, user: session?.user ?? null, signOut }),
    [status, session, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
