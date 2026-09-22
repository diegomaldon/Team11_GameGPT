"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/session";
import { safeNext } from "@/lib/auth/redirect";
import { signInWithPassword } from "@/lib/auth/signin";
import { Button, Field, TextInput } from "@/components/ui";
import { Controller } from "@/components/icons";

/**
 * GameGPT · E2 Identity & Account Management
 * Sign-in. REQ001.
 *
 * Replaces the demo sign-in that set local state without a Supabase session. That version
 * stopped working the moment the auth gate became real: it marked you signed in, the gate
 * saw no session, and bounced you straight back here.
 */

function SignInForm() {
  const { status } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Validated on read, never trusted: see lib/auth/redirect.ts.
  const next = safeNext(searchParams.get("next"));

  // Covers both arriving here with a live session and the session landing while the form
  // is open (the sign-in itself, or another tab signing in).
  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, next, router]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFieldErrors({});
    setFormError(null);

    const result = await signInWithPassword({ email, password });

    switch (result.status) {
      case "signed_in":
        // Deliberately no router.replace here. The effect above fires when the session
        // lands, so navigating now would race it and sometimes double-navigate.
        return;

      case "invalid_credentials":
        setFormError("That email and password don't match an account.");
        break;

      case "email_not_confirmed":
        setFormError("Confirm your email first — check your inbox for the link.");
        break;

      case "invalid":
        setFieldErrors(result.fieldErrors);
        break;

      case "rate_limited":
        setFormError(
          result.retryAfterSeconds
            ? `Too many attempts. Try again in ${result.retryAfterSeconds} seconds.`
            : "Too many attempts. Try again shortly.",
        );
        break;

      default:
        setFormError(result.message);
    }

    setBusy(false);
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-5 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--ink)] text-white">
            <Controller className="h-6 w-6" />
          </span>
          <h1 className="mt-4 font-display text-2xl font-bold tracking-tight">
            Welcome to GameGPT
          </h1>
          <p className="mt-1.5 text-sm text-[var(--ink-soft)]">
            Sign in to link your libraries and get recommendations.
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-white p-6 shadow-card">
          {formError && (
            <p
              role="alert"
              className="mb-4 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-700"
            >
              {formError}
            </p>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-3" noValidate>
            <Field label="Email" htmlFor="email" error={fieldErrors.email?.[0]}>
              <TextInput
                id="email"
                type="email"
                autoComplete="email"
                inputMode="email"
                placeholder="you@school.edu"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>

            <Field label="Password" htmlFor="password" error={fieldErrors.password?.[0]}>
              <TextInput
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            <Button type="submit" size="md" loading={busy} disabled={busy} className="w-full">
              Sign in
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-sm text-[var(--ink-soft)]">
          No account?{" "}
          <Link href="/register" className="font-medium underline">
            Create one
          </Link>
        </p>
      </div>
    </main>
  );
}

// useSearchParams needs a Suspense boundary or Next refuses to prerender the route.
export default function SignInPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center text-sm text-[var(--ink-faint)]">
          Loading…
        </div>
      }
    >
      <SignInForm />
    </Suspense>
  );
}
