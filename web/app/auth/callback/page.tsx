"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { completeOAuthSignIn } from "@/lib/auth/oauth";
import { Button } from "@/components/ui";

/**
 * GameGPT · E2 Identity & Account Management
 * OAuth and email-confirmation landing route. REQ002.
 *
 * Everything arrives here as a normal page load, including the failures — Google sends
 * back `?error=access_denied` rather than an HTTP error — so the refusal paths need real
 * UI, not a thrown exception. That is AC4.
 */

type View =
  | { state: "working" }
  | { state: "failed"; message: string; canRetry: boolean };

function Callback() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [view, setView] = useState<View>({ state: "working" });

  // React 18+ mounts effects twice in development. The PKCE code is single-use, so
  // without this guard the second run redeems an already-spent code and overwrites a
  // successful sign-in with an error.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    let active = true;

    completeOAuthSignIn(searchParams).then((result) => {
      if (!active) return;

      if (result.status === "signed_in") {
        // replace(), so Back does not return to a URL whose code is now spent.
        router.replace(result.next);
        return;
      }

      setView({
        state: "failed",
        message: result.message,
        // A cancelled or refused sign-in is worth retrying. A spent or malformed link
        // is not: the same URL will fail the same way every time.
        canRetry: result.status === "denied",
      });
    });

    return () => {
      active = false;
    };
  }, [searchParams, router]);

  if (view.state === "working") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center px-5 py-10">
        <p className="text-sm text-[var(--ink-faint)]" role="status">
          Signing you in…
        </p>
      </main>
    );
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-5 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-white p-6 text-center shadow-card">
        <h1 className="font-display text-xl font-bold tracking-tight">
          Sign-in didn&apos;t finish
        </h1>
        <p className="mt-2 text-sm text-[var(--ink-soft)]" role="alert">
          {view.message}
        </p>
        <Button
          size="md"
          className="mt-5 w-full"
          onClick={() => router.replace("/signin")}
        >
          {view.canRetry ? "Try again" : "Back to sign in"}
        </Button>
        <p className="mt-4 text-xs text-[var(--ink-faint)]">
          Still stuck?{" "}
          <Link href="/register" className="underline">
            Create an account
          </Link>{" "}
          with an email and password instead.
        </p>
      </div>
    </main>
  );
}

// useSearchParams needs a Suspense boundary or Next refuses to prerender the route.
export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center text-sm text-[var(--ink-faint)]">
          Signing you in…
        </div>
      }
    >
      <Callback />
    </Suspense>
  );
}
