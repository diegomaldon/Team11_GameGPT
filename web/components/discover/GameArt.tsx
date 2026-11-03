"use client";

// Steam art for a game by app id (TM11-142). Falls back to the title's initials on a
// navy tile when there is no app id or the image fails to load, so a missing cover
// never leaves a broken-image icon in a grid.

import Image from "next/image";
import { useState } from "react";
import { steamCoverUrl, steamHeroUrl } from "@/lib/discover/featured";
import { cx } from "@/components/ui";

export function GameArt({
  appId,
  title,
  kind = "cover",
  sizes,
  priority = false,
  decorative = false,
  className,
}: {
  appId?: number | null;
  title: string;
  kind?: "cover" | "hero";
  /** The rendered width, for the browser's choice of download (e.g. "156px"). */
  sizes: string;
  priority?: boolean;
  /** True when the title is already written next to the art. */
  decorative?: boolean;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const src = appId ? (kind === "hero" ? steamHeroUrl(appId) : steamCoverUrl(appId)) : null;

  if (!src || failed) {
    const initials = title
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join("")
      .toUpperCase();
    return (
      <div
        role={decorative ? undefined : "img"}
        aria-label={decorative ? undefined : title}
        aria-hidden={decorative || undefined}
        className={cx(
          "absolute inset-0 flex items-center justify-center bg-[var(--raised-2)] font-display text-3xl text-[var(--ink-faint)]",
          className,
        )}
      >
        {initials}
      </div>
    );
  }

  return (
    <Image
      src={src}
      alt={decorative ? "" : title}
      fill
      unoptimized
      priority={priority}
      sizes={sizes}
      onError={() => setFailed(true)}
      className={cx("object-cover", className)}
    />
  );
}
