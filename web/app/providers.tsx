"use client";

import { useEffect } from "react";

import { MockProvider } from "@/lib/mock/store";
import { AuthProvider } from "@/lib/auth/session";
import { installGlobalErrorHandlers } from "@/lib/observability";

// AuthProvider is the real Supabase session (REQ001/REQ002). MockProvider is still the
// dummy data behind Library and Settings and now owns nothing auth-related — its signIn
// and signOut are dead weight until those screens get real backing.
export function Providers({ children }: { children: React.ReactNode }) {
  // On mount rather than at module scope: this file is imported during SSR too,
  // where `window` does not exist.
  useEffect(() => {
    installGlobalErrorHandlers();
  }, []);

  return (
    <AuthProvider>
      <MockProvider>{children}</MockProvider>
    </AuthProvider>
  );
}
