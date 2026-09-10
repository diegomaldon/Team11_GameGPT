"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Recommendation = {
  rank: number;
  game_id?: string | null;
  title: string;
  reason: string;
  steam_appid?: number | null;
  review_score?: number | null;
};

type RecommendResponse = {
  query_id: string;
  query: string;
  recommendations: Recommendation[];
};

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [voted, setVoted] = useState<Record<number, "up" | "down">>({});

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setVoted({});
    try {
      const res = await fetch(`${API_URL}/api/recommend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) throw new Error(`API returned ${res.status}`);
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function vote(rec: Recommendation, v: "up" | "down") {
    if (!result) return;
    setVoted((prev) => ({ ...prev, [rec.rank]: v }));
    try {
      await fetch(`${API_URL}/api/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query_id: result.query_id,
          game_id: rec.game_id ?? null,
          title: rec.title,
          rank: rec.rank,
          vote: v,
        }),
      });
    } catch {
      // best-effort in the skeleton; leave the optimistic UI in place
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
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-neutral-200" />
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
    </main>
  );
}
