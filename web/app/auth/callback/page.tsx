import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Confirming your email — GameGPT',
};

// TODO: E2 — placeholder. This route exists so the confirmation link in the signup email
// resolves instead of 404ing; it does not yet complete the flow.
//
// What it still needs: read the PKCE `code` query param, call
// supabase.auth.exchangeCodeForSession(code), then redirect to `/` on success or surface
// the error. The client in lib/supabase.ts is already configured with
// detectSessionInUrl and flowType: 'pkce' for exactly this.
//
// The URL must also be on the Supabase redirect allowlist
// (http://localhost:3000/auth/callback) or GoTrue refuses to send the user here at all.
export default function AuthCallbackPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-5 py-10">
      <div className="mx-auto max-w-sm space-y-3 text-center" role="status">
        <h1 className="text-xl font-semibold">Email confirmed</h1>
        <p className="text-sm text-neutral-600">
          Your address is verified. Session handling for this route lands with the rest of
          E2 — for now, sign in to continue.
        </p>
        <p className="text-sm">
          <Link href="/signin" className="underline">
            Go to sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
