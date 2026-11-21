// What the Discover page says while a search runs (TM11-76, REQ040).
//
// The API answers in one response, so the browser can't see which stage it is on.
// The message follows the elapsed time instead, using the stage budgets the API is
// held to (STAGE_BUDGET_MS in api/observability/stage_timings.py): parse and embed
// take about 500 ms, retrieve and filter end by about 1,750 ms, and ranking uses the
// rest of the 10 second budget. Past that, the message says the search is slow.

/** Elapsed milliseconds at which each message starts, latest first. */
const PROGRESS_STEPS: readonly { fromMs: number; message: string }[] = [
  { fromMs: 10_000, message: "This is taking longer than usual. Still working…" },
  { fromMs: 1_750, message: "Ranking the best matches…" },
  { fromMs: 500, message: "Searching the catalogue…" },
];

const FIRST_MESSAGE = "Reading your request…";

/** The progress message for a search that started `elapsedMs` ago. */
export function searchProgressMessage(elapsedMs: number): string {
  const step = PROGRESS_STEPS.find((s) => elapsedMs >= s.fromMs);
  return step?.message ?? FIRST_MESSAGE;
}
