"use client";

// Drives a background library import and exposes its live state (TM11-49).
// One import at a time per component; unmounting stops the polling, not the
// import itself, which carries on server-side.
import { useCallback, useEffect, useRef, useState } from "react";
import { runLibrarySync } from "../api/client";
import type { LibrarySyncJob } from "../api/types";

export interface LibrarySyncState {
  job: LibrarySyncJob | null;
  /** Set when the import could not be started or tracked (not when it ran and failed). */
  error: string | null;
  running: boolean;
  start: (steamId: string) => void;
}

export const TRACKING_ERROR =
  "We lost track of the import. Check your library, or try again.";

export function useLibrarySync(): LibrarySyncState {
  const [job, setJob] = useState<LibrarySyncJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const start = useCallback((steamId: string) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setError(null);
    setJob(null);
    setRunning(true);
    runLibrarySync(steamId, (j) => !controller.signal.aborted && setJob(j), {
      signal: controller.signal,
    })
      .catch(() => {
        if (!controller.signal.aborted) setError(TRACKING_ERROR);
      })
      .finally(() => {
        if (!controller.signal.aborted) setRunning(false);
      });
  }, []);

  return { job, error, running, start };
}
