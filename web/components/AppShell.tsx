"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect } from "react";
import { useMock } from "@/lib/mock/store";
import { Avatar, cx } from "./ui";
import { Compass, Controller, Gear, Library, LogOut } from "./icons";

const NAV = [
  { href: "/", label: "Discover", Icon: Compass },
  { href: "/library", label: "Library", Icon: Library },
  { href: "/settings", label: "Settings", Icon: Gear },
] as const;

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { state, hydrated, signOut } = useMock();
  const pathname = usePathname();
  const router = useRouter();

  // Client-side auth gate for the mock: bounce to sign-in when signed out.
  useEffect(() => {
    if (hydrated && !state.signedIn) router.replace("/signin");
  }, [hydrated, state.signedIn, router]);

  if (!hydrated || !state.signedIn) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-sm text-[var(--ink-faint)]">
        Loading…
      </div>
    );
  }

  function handleSignOut() {
    signOut();
    router.replace("/signin");
  }

  return (
    <div className="min-h-dvh">
      {/* ── Desktop sidebar ── */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-[var(--border)] bg-white px-3 py-5 md:flex">
        <Link href="/" className="mb-6 flex items-center gap-2.5 px-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--ink)] text-white">
            <Controller className="h-5 w-5" />
          </span>
          <span className="font-display text-lg font-bold tracking-tight">
            GameGPT
          </span>
        </Link>

        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ href, label, Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-accent-50 text-accent-700"
                    : "text-[var(--ink-soft)] hover:bg-neutral-100 hover:text-[var(--ink)]",
                )}
              >
                <Icon className="h-5 w-5" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-2 flex items-center gap-2.5 rounded-xl border border-[var(--border)] p-2.5">
          <Avatar name={state.profile.name} size={34} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold">{state.profile.name}</p>
            <p className="truncate text-xs text-[var(--ink-faint)]">
              {state.profile.email}
            </p>
          </div>
          <button
            type="button"
            onClick={handleSignOut}
            aria-label="Sign out"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-neutral-100 hover:text-[var(--ink)]"
          >
            <LogOut className="h-[18px] w-[18px]" />
          </button>
        </div>
      </aside>

      {/* ── Mobile top bar ── */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-[var(--border)] bg-white/90 px-5 py-3 backdrop-blur md:hidden">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--ink)] text-white">
            <Controller className="h-[18px] w-[18px]" />
          </span>
          <span className="font-display text-base font-bold tracking-tight">
            GameGPT
          </span>
        </Link>
        <Link href="/settings" aria-label="Account settings">
          <Avatar name={state.profile.name} size={32} />
        </Link>
      </header>

      {/* ── Content ── */}
      <main className="md:pl-60">
        <div className="mx-auto w-full max-w-3xl px-5 py-8 pb-28 sm:px-6 md:pb-14">
          {children}
        </div>
      </main>

      {/* ── Mobile bottom nav ── */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-[var(--border)] bg-white/95 backdrop-blur md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {NAV.map(({ href, label, Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cx(
                "flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors",
                active ? "text-accent-700" : "text-[var(--ink-faint)]",
              )}
            >
              <Icon className="h-[22px] w-[22px]" />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
