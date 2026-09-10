"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMock } from "@/lib/mock/store";
import { Button, Field, TextInput } from "@/components/ui";
import { Controller, Google } from "@/components/icons";

export default function SignInPage() {
  const { state, hydrated, signIn } = useMock();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState<null | "google" | "email">(null);

  // Already signed in? Skip straight to the app.
  useEffect(() => {
    if (hydrated && state.signedIn) router.replace("/");
  }, [hydrated, state.signedIn, router]);

  function finish(method: "google" | "email") {
    setBusy(method);
    // Simulate an auth round-trip for the mock.
    window.setTimeout(() => {
      signIn(method === "email" && email ? email : undefined);
      router.replace("/");
    }, 700);
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
          <Button
            variant="secondary"
            size="md"
            loading={busy === "google"}
            disabled={busy !== null}
            onClick={() => finish("google")}
            className="w-full"
          >
            {busy !== "google" && <Google className="h-[18px] w-[18px]" />}
            Continue with Google
          </Button>

          <div className="my-5 flex items-center gap-3 text-xs text-[var(--ink-faint)]">
            <span className="h-px flex-1 bg-[var(--border)]" />
            or
            <span className="h-px flex-1 bg-[var(--border)]" />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              finish("email");
            }}
            className="flex flex-col gap-3"
          >
            <Field label="Email" htmlFor="email">
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
            <Button
              type="submit"
              size="md"
              loading={busy === "email"}
              disabled={busy !== null}
              className="w-full"
            >
              Continue with email
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-xs text-[var(--ink-faint)]">
          Demo sign-in — no real authentication. Any details work.
        </p>
      </div>
    </main>
  );
}
