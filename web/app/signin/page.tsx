"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/session";
import { safeNext } from "@/lib/auth/redirect";
import { signInWithPassword } from "@/lib/auth/signin";
import { startGoogleSignIn } from "@/lib/auth/oauth";
import { Button, Field, TextInput } from "@/components/ui";
import { Google } from "@/components/icons";
import { AuthLayout } from "@/components/auth/AuthLayout";

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
  const [busy, setBusy] = useState<null | "google" | "password">(null);

  // Validated on read, never trusted: see lib/auth/redirect.ts.
  const next = safeNext(searchParams.get("next"));

  // Covers both arriving here with a live session and the session landing while the form
  // is open (the sign-in itself, or another tab signing in).
  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, next, router]);

  async function handleGoogle() {
    setBusy("google");
    setFormError(null);

    const result = await startGoogleSignIn(searchParams.get("next"));

    // On success the browser is already navigating to Google and nothing below matters.
    // Only a failure comes back, and it leaves the user on this page needing the button.
    if (result.status === "error") {
      setFormError(result.message);
      setBusy(null);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy("password");
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

    setBusy(null);
  }

  return (
    <AuthLayout>
      <div>
        <h1 className="font-display text-[48px] leading-[1.05]">Welcome back.</h1>
        <p className="mt-2.5 text-base leading-relaxed text-[var(--ink-faint)]">
          Sign in to pick up your library and recommendations.
        </p>
      </div>

      {formError && (
        <p
          role="alert"
          className="rounded-2xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {formError}
        </p>
      )}

      <Button
        variant="secondary"
        size="md"
        loading={busy === "google"}
        disabled={busy !== null}
        onClick={handleGoogle}
        className="w-full"
      >
        {busy !== "google" && <Google className="h-[18px] w-[18px]" />}
        Continue with Google
      </Button>

      <div className="flex items-center gap-3 text-xs uppercase tracking-[0.1em] text-[var(--ink-faint)]">
        <span className="h-px flex-1 bg-[var(--border)]" />
        or
        <span className="h-px flex-1 bg-[var(--border)]" />
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
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

        <Button
          type="submit"
          size="md"
          loading={busy === "password"}
          disabled={busy !== null}
          className="mt-2 w-full"
        >
          Sign in
        </Button>
      </form>

      <p className="text-sm text-[var(--ink-faint)]">
        New to GameGPT?{" "}
        <Link href="/register" className="font-medium text-[var(--heading)] underline-offset-4 hover:underline">
          Create an account
        </Link>
      </p>
    </AuthLayout>
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
