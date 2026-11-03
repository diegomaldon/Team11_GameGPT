// The signed-out pages' layout (TM11-142): a wall of popular game covers scrolling on the
// left, the form on the right. Below 768px the wall is hidden and the form fills the
// screen. The wall is decoration only, so it is hidden from assistive tech.

import Link from "next/link";
import { POPULAR, type FeaturedGame } from "@/lib/discover/featured";
import { GameArt } from "@/components/discover/GameArt";

// Three columns, each a different slice of the list so neighbours don't repeat.
const COLUMNS: { games: FeaturedGame[]; animation: string }[] = [
  { games: pick([0, 3, 6, 9, 2]), animation: "animate-wall-up" },
  { games: pick([1, 4, 7, 5]), animation: "animate-wall-down" },
  { games: pick([8, 2, 5, 0, 6]), animation: "animate-wall-up-slow" },
];

function pick(indexes: number[]): FeaturedGame[] {
  return indexes.map((i) => POPULAR[i % POPULAR.length]);
}

export function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh">
      <div
        aria-hidden
        className="hidden h-dvh flex-1 grid-cols-3 gap-4 overflow-hidden bg-[#070e22] px-4 [mask-image:linear-gradient(180deg,transparent,#000_10%,#000_90%,transparent)] md:sticky md:top-0 md:grid"
      >
        {COLUMNS.map((col, c) => (
          <div key={c} className={`flex flex-col gap-4 ${col.animation}`}>
            {[...col.games, ...col.games].map((g, i) => (
              <div
                key={`${g.steamAppId}-${i}`}
                className="relative aspect-[2/3] shrink-0 overflow-hidden rounded-[18px] opacity-75"
              >
                <GameArt appId={g.steamAppId} title={g.title} sizes="(min-width: 768px) 16vw, 0px" decorative />
              </div>
            ))}
          </div>
        ))}
      </div>

      <main className="flex min-h-dvh flex-1 items-center justify-center px-4 py-12 sm:px-8">
        <div className="flex w-full max-w-[400px] flex-col gap-6">
          <Link href="/" className="font-display text-[26px] leading-none text-[var(--heading)]">
            GameGPT
          </Link>
          {children}
        </div>
      </main>
    </div>
  );
}
