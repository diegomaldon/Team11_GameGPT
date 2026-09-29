"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/session";
import { signInUrlFor } from "@/lib/auth/redirect";

/**
 * GameGPT · E2 Identity & Account Management
 * Auth gate for the (app) route group. REQ001 / REQ002.
 *
 * Scope, so nobody mistakes this for more than it is: this is a client-side gate. It
 * decides what renders, not what the server will hand out. Anyone can bypass it with
 * devtools. The actual protection on user data is row level security in Postgres
 * (migration 20260915120300) — the gate exists so signed-out visitors get sent somewhere
 * useful instead of watching empty pages fail to load.
 *
 * Moving this to Next middleware would need the session in a cookie rather than
 * localStorage, i.e. swapping supabase-js for @supabase/ssr across the whole app. Worth
 * doing before launch; not worth coupling to this story. Noted in docs/auth-sessions.md.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status !== "anonymous") return;

    // Preserve the query string: /library?filter=steam should come back whole, not as
    // a bare /library. The guard runs on the page the user actually asked for, so
    // pathname is already the intended destination.
    const query = searchParams.toString();
    const intended = query ? `${pathname}?${query}` : pathname;

    // replace(), not push(): a signed-out visitor pressing Back should leave the way
    // they came, not bounce between the gate and the page it rejected.
    router.replace(signInUrlFor(intended));
  }, [status, router, pathname, searchParams]);

  // Render nothing decisive until the stored session has been read. Showing the app to
  // someone who turns out to be signed out flashes private-looking chrome; redirecting
  // someone who turns out to be signed in throws away where they were going.
  if (status !== "authenticated") {
    return (
      <div
        className="flex min-h-dvh items-center justify-center text-sm text-[var(--ink-faint)]"
        role="status"
      >
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}
