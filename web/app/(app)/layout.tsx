import { Suspense } from "react";
import { AppShell } from "@/components/AppShell";
import { RequireAuth } from "@/components/auth/RequireAuth";

// Wraps the authenticated pages (Discover, Library, Settings) in the auth gate and then
// the app shell. The route group "(app)" keeps URLs clean: /, /library, /settings.
//
// The Suspense boundary is required, not stylistic: RequireAuth reads useSearchParams,
// and Next refuses to prerender a page that does so outside one.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-dvh items-center justify-center text-sm text-[var(--ink-faint)]">
          Loading…
        </div>
      }
    >
      <RequireAuth>
        <AppShell>{children}</AppShell>
      </RequireAuth>
    </Suspense>
  );
}
