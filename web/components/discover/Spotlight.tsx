"use client";

// The rotating featured game at the top of Discover (TM11-142). Advances every 6 seconds,
// and stops while the pointer or keyboard focus is on it, when the user presses Pause,
// or when they ask for reduced motion (WCAG 2.2.2: moving content can be paused).

import { useEffect, useState } from "react";
import { SPOTLIGHT } from "@/lib/discover/featured";
import { ChevronLeft, ChevronRight, Pause, Play } from "@/components/icons";
import { GameArt } from "./GameArt";

const ADVANCE_MS = 6000;

export function Spotlight({ onFindLike }: { onFindLike: (title: string) => void }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [held, setHeld] = useState(false); // pointer over it, or focus inside it
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const rotating = !paused && !held && !reducedMotion;
  useEffect(() => {
    if (!rotating) return;
    const id = window.setInterval(() => setIndex((i) => (i + 1) % SPOTLIGHT.length), ADVANCE_MS);
    return () => window.clearInterval(id);
  }, [rotating]);

  const game = SPOTLIGHT[index];
  const step = (by: number) =>
    setIndex((i) => (i + by + SPOTLIGHT.length) % SPOTLIGHT.length);

  return (
    <section
      aria-roledescription="carousel"
      aria-label="Featured games"
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHeld(false);
      }}
      className="relative h-[460px] overflow-hidden rounded-[28px] border border-[var(--border)] bg-[var(--surface)] sm:h-[560px]"
    >
      <div key={game.steamAppId} className="absolute inset-0 animate-fade-in">
        <GameArt
          appId={game.steamAppId}
          title={`${game.title} key art`}
          kind="hero"
          sizes="(min-width: 1440px) 1344px, 100vw"
          priority={index === 0}
        />
      </div>

      <div
        aria-roledescription="slide"
        aria-label={`${index + 1} of ${SPOTLIGHT.length}`}
        aria-live={rotating ? "off" : "polite"}
        className="absolute inset-x-4 bottom-4 max-w-[520px] rounded-[20px] border border-[var(--border)] bg-[rgb(5_10_24/0.9)] p-6 sm:inset-x-6 sm:bottom-6 sm:p-7"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--label)]">
          Popular now · {index + 1} of {SPOTLIGHT.length}
        </p>
        <h2 className="mt-2 font-display text-[38px] leading-[1.02] sm:text-[52px]">
          {game.title}
        </h2>
        <p className="mt-3 text-base leading-relaxed text-[var(--ink-soft)]">{game.blurb}</p>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => onFindLike(game.title)}
            className="inline-flex min-h-11 items-center rounded-full bg-[var(--accent)] px-5 text-[15px] font-semibold text-[var(--on-accent)] transition-colors hover:bg-[var(--accent-hover)]"
          >
            Find games like this
          </button>
          <div className="ml-auto flex gap-2">
            <RoundButton
              label={paused ? "Play featured games" : "Pause featured games"}
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? <Play className="h-[18px] w-[18px]" /> : <Pause className="h-[18px] w-[18px]" />}
            </RoundButton>
            <RoundButton label="Previous featured game" onClick={() => step(-1)}>
              <ChevronLeft className="h-[18px] w-[18px]" />
            </RoundButton>
            <RoundButton label="Next featured game" onClick={() => step(1)}>
              <ChevronRight className="h-[18px] w-[18px]" />
            </RoundButton>
          </div>
        </div>
      </div>
    </section>
  );
}

function RoundButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border-strong)] text-[var(--ink)] transition-colors hover:bg-[var(--raised-2)]"
    >
      {children}
    </button>
  );
}
