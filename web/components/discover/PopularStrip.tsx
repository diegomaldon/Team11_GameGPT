"use client";

// A sideways-scrolling row of popular games under the spotlight (TM11-142). Each cover
// asks for games like that one.

import { POPULAR } from "@/lib/discover/featured";
import { GameArt } from "./GameArt";

export function PopularStrip({ onFindLike }: { onFindLike: (title: string) => void }) {
  return (
    <section aria-labelledby="popular-heading" className="mt-10">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 id="popular-heading" className="font-display text-[28px]">
          Popular games
        </h2>
        <span className="hidden text-[13px] text-[var(--ink-faint)] sm:inline">
          Pick one to find more like it
        </span>
      </div>
      <ul className="-mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto px-1 pb-3 [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin]">
        {POPULAR.map((g) => (
          <li key={g.steamAppId} className="shrink-0 snap-start">
            <button
              type="button"
              onClick={() => onFindLike(g.title)}
              aria-label={`Find games like ${g.title}`}
              className="group block w-[156px] text-left"
            >
              <span className="relative block h-[234px] overflow-hidden rounded-2xl border border-[var(--border)] transition-colors group-hover:border-[var(--accent)]">
                <GameArt
                  appId={g.steamAppId}
                  title={g.title}
                  sizes="156px"
                  decorative
                  className="transition-transform duration-300 group-hover:scale-[1.03]"
                />
              </span>
              <span className="mt-2.5 block text-sm font-medium text-[var(--ink)]">{g.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
