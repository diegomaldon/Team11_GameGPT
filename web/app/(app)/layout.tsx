import { AppShell } from "@/components/AppShell";

// Wraps the authenticated pages (Discover, Library, Settings) in the app shell.
// The route group "(app)" keeps URLs clean: /, /library, /settings.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
