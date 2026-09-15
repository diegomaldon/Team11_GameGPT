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
    // Required for the email-confirmation callback route to pick up the session.
    detectSessionInUrl: true,
    flowType: 'pkce',
  },
});
