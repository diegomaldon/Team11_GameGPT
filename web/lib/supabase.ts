import { createClient } from '@supabase/supabase-js';

// Next inlines these at build time only when written as full literal property accesses,
// so they cannot be destructured or built dynamically. (Vite's import.meta.env equivalent
// in the original draft of this file does not exist under Next.)
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// Fail at startup rather than at the first signup attempt. A missing env var that only
// surfaces as a runtime auth error costs an afternoon of debugging the wrong layer.
if (!url || !anonKey) {
  throw new Error(
    'Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY. Copy .env.example to .env.local.',
  );
}

export const supabase = createClient(url, anonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,

    // Off deliberately, and it used to be on (REQ001, when /auth/callback was a stub).
    //
    // When this is true the client spots `?code=` during construction and redeems it on
    // its own, in the background. The PKCE code is single-use, so that races the explicit
    // exchange in app/auth/callback: whichever call arrives second gets "invalid request:
    // code verifier should be non-empty" and the page reports a failed sign-in that
    // actually succeeded. Whether it happens depends on module import order, which is not
    // something to leave to chance.
    //
    // With it off, completeOAuthSignIn() in lib/auth/oauth.ts is the only thing that
    // redeems a code — for the Google flow and for email confirmation links, which land
    // on the same route. Errors are ours to map and to test.
    detectSessionInUrl: false,

    flowType: 'pkce',
  },
});
