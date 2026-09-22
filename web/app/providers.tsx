"use client";

import { MockProvider } from "@/lib/mock/store";
import { AuthProvider } from "@/lib/auth/session";

// AuthProvider is the real Supabase session (REQ001/REQ002). MockProvider is still the
// dummy data behind Library and Settings and now owns nothing auth-related — its signIn
// and signOut are dead weight until those screens get real backing.
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <MockProvider>{children}</MockProvider>
    </AuthProvider>
  );
}
