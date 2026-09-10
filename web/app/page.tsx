"use client";

import { useState } from "react";
import {
  recommend,
  sendFeedback,
  syncLibrary,
} from "@/lib/api/client";
import type { Recommendation, RecommendResponse, Vote } from "@/lib/api/types";

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [voted, setVoted] = useState<Record<number, Vote>>({});

  // Steam library sync state.
  const [steamId, setSteamId] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setVoted({});
    try {
      setResult(await recommend(query.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function vote(rec: Recommendation, v: Vote) {
    if (!result) return;
    setVoted((prev) => ({ ...prev, [rec.rank]: v }));
    try {
      await sendFeedback({
        query_id: result.query_id,
        game_id: rec.game_id ?? null,
        title: rec.title,
        rank: rec.rank,
        vote: v,
      });
    } catch {
      // Best-effort in the skeleton; leave the optimistic UI in place.
    }
  }

  async function onSync(e: React.FormEvent) {
    e.preventDefault();
    if (!steamId.trim()) return;
    setSyncing(true);
    setSyncMsg(null);
    setSyncError(null);
    try {
      const res = await syncLibrary(steamId.trim());
      setSyncMsg(
        `Synced ${res.synced} game${res.synced === 1 ? "" : "s"} (source: ${res.source}).`,
      );
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <header>
        <h1 className="text-2xl font-semibold">GameGPT</h1>
        <p className="text-sm text-neutral-500">
          Describe a vibe. Get games from your library and beyond.
        </p>
      </header>

      <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="a chill game I can play while listening to a podcast"
          className="w-full flex-1 rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-neutral-500"
          aria-label="Describe the game you want"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {loading ? "Thinking…" : "Recommend"}
        </button>
      </form>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      {loading && (
        <div className="flex flex-col gap-3" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="flex flex-col gap-3 rounded-lg border border-neutral-200 bg-white p-4"
            >
              <div className="h-4 w-1/3 animate-pulse rounded bg-neutral-200" />
              <div className="h-3 w-full animate-pulse rounded bg-neutral-200" />
              <div className="h-3 w-4/5 animate-pulse rounded bg-neutral-200" />
            </div>
          ))}
        </div>
      )}

      {result && (
        <ol className="flex flex-col gap-3">
          {result.recommendations.map((rec) => (
            <li
              key={rec.rank}
              className="rounded-lg border border-neutral-200 bg-white p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="text-xs font-medium text-neutral-400">
                    #{rec.rank}
                  </span>
                  <h2 className="text-base font-semibold">{rec.title}</h2>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    onClick={() => vote(rec, "up")}
                    aria-label={`Thumbs up ${rec.title}`}
                    aria-pressed={voted[rec.rank] === "up"}
                    className={`rounded-md border px-2 py-1 text-sm ${
                      voted[rec.rank] === "up"
                        ? "border-green-500 bg-green-50"
                        : "border-neutral-200"
                    }`}
                  >
                    👍
                  </button>
                  <button
                    onClick={() => vote(rec, "down")}
                    aria-label={`Thumbs down ${rec.title}`}
                    aria-pressed={voted[rec.rank] === "down"}
                    className={`rounded-md border px-2 py-1 text-sm ${
                      voted[rec.rank] === "down"
                        ? "border-red-500 bg-red-50"
                        : "border-neutral-200"
                    }`}
                  >
                    👎
                  </button>
                </div>
              </div>
              <p className="mt-2 text-sm text-neutral-700">{rec.reason}</p>
            </li>
          ))}
        </ol>
      )}

      <section className="mt-2 flex flex-col gap-2 border-t border-neutral-200 pt-6">
        <h2 className="text-sm font-semibold">Link your Steam library</h2>
        <p className="text-xs text-neutral-500">
          Paste a public steamID64 to sync owned games. Synced games are dropped
          from future recommendations.
        </p>
        <form onSubmit={onSync} className="flex flex-col gap-2 sm:flex-row">
          <input
            value={steamId}
            onChange={(e) => setSteamId(e.target.value)}
            placeholder="76561197960287930"
            inputMode="numeric"
            className="w-full flex-1 rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm outline-none focus:border-neutral-500"
            aria-label="Public steamID64"
          />
          <button
            type="submit"
            disabled={syncing || !steamId.trim()}
            className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-900 disabled:opacity-40"
          >
            {syncing ? "Syncing…" : "Sync library"}
          </button>
        </form>
        {syncMsg && (
          <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">
            {syncMsg}
          </p>
        )}
        {syncError && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {syncError}
          </p>
        )}
      </section>
    </main>
  );
}
