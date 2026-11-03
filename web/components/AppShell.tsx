"use client";

// The signed-in chrome (TM11-142): one header with the GameGPT wordmark, a centred pill
// for Discover · Library · Settings, and the account button showing the user's name.
// It replaces the old sidebar and the mobile top and bottom bars. Below 640px the pill
// moves to its own row under the wordmark and spreads across the screen.

import { useEffect, useId, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useMock } from "@/lib/mock/store";
import { useAuth } from "@/lib/auth/session";
import { Avatar, cx } from "./ui";
import { ChevronDown, Compass, Gear, Library, LogOut, Sliders } from "./icons";

const NAV = [
  { href: "/", label: "Discover", Icon: Compass },
  { href: "/library", label: "Library", Icon: Library },
  { href: "/settings", label: "Settings", Icon: Sliders },
] as const;

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

// user_metadata is provider-supplied JSON, so every field is unknown until checked.
// Blank strings count as absent — an empty full_name should fall through, not render.
function pickName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { state } = useMock();
  const { user, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  // No auth gate here any more: <RequireAuth> in app/(app)/layout.tsx owns that, and this
  // component never renders until it says the session is real.

  // Same coalesce order as handle_new_user() in migration 20260922120000: our own
  // registration form sends display_name, Google sends full_name and name. Checking only
  // display_name meant a Google user fell through to the mock profile and the header
  // showed a fake name next to their real email.
  const meta = user?.user_metadata as Record<string, unknown> | undefined;
  const displayName =
    pickName(meta?.display_name) ??
    pickName(meta?.full_name) ??
    pickName(meta?.name) ??
    state.profile.name;
  const email = user?.email ?? state.profile.email;

  async function handleSignOut() {
    await signOut();
    router.replace("/signin");
  }

  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex w-full max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-3 px-4 py-4 sm:flex-nowrap sm:px-8 sm:py-5 lg:px-12">
        <Link
          href="/"
          className="flex-1 font-display text-[26px] leading-none text-[var(--heading)] sm:basis-0"
        >
          GameGPT
        </Link>

        <nav
          aria-label="Main"
          className="order-3 flex w-full justify-between gap-1 rounded-full border border-[var(--border)] bg-[var(--surface)] p-[5px] sm:order-none sm:w-auto sm:justify-start"
        >
          {NAV.map(({ href, label, Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex min-h-10 flex-1 items-center justify-center gap-2 rounded-full px-4 text-sm transition-colors sm:flex-none",
                  active
                    ? "bg-[var(--accent)] font-semibold text-[var(--on-accent)]"
                    : "font-medium text-[var(--ink-faint)] hover:bg-[var(--raised)] hover:text-[var(--heading)]",
                )}
              >
                <Icon className="h-[18px] w-[18px] max-[389px]:hidden" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="flex flex-1 justify-end sm:basis-0">
          <AccountMenu name={displayName} email={email} onSignOut={handleSignOut} />
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-4 sm:px-8 lg:px-12">
        {children}
      </main>
    </div>
  );
}

/**
 * The account button at the top right: the user's name and initials. It opens a small
 * panel with their email, a Settings link and Sign out. A disclosure, not an ARIA menu:
 * the panel holds an ordinary link and button, so Tab moves through them as usual.
 */
function AccountMenu({
  name,
  email,
  onSignOut,
}: {
  name: string;
  email: string;
  onSignOut: () => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  // Close on navigation, on Escape, and on a click anywhere outside the menu.
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 items-center gap-3 rounded-full border border-[var(--border)] py-1 pl-4 pr-1 text-sm font-medium text-[var(--ink)] transition-colors hover:bg-[var(--raised)]"
      >
        <span className="max-w-[14ch] truncate">{name}</span>
        <ChevronDown className="h-4 w-4 text-[var(--ink-faint)]" />
        <Avatar name={name} size={34} />
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 top-[calc(100%+8px)] z-40 w-64 animate-fade-up rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-lift"
        >
          <div className="px-3 pb-3 pt-2">
            <p className="truncate text-sm font-semibold text-[var(--heading)]">{name}</p>
            <p className="truncate text-xs text-[var(--ink-faint)]">{email}</p>
          </div>
          <Link
            href="/settings"
            className="flex min-h-11 items-center gap-3 rounded-2xl px-3 text-sm text-[var(--ink)] hover:bg-[var(--raised)]"
          >
            <Gear className="h-[18px] w-[18px] text-[var(--ink-faint)]" />
            Account settings
          </Link>
          <button
            type="button"
            onClick={onSignOut}
            className="flex min-h-11 w-full items-center gap-3 rounded-2xl px-3 text-left text-sm text-[var(--ink)] hover:bg-[var(--raised)]"
          >
            <LogOut className="h-[18px] w-[18px] text-[var(--ink-faint)]" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
