// What to tell the user when a surface can't load (TM11-77).
//
// The wording follows the CIS453 rainy-day scenarios:
// - Search: "display an error message with an estimated retry time and allow the user
//   to try again". A timeout is named as one, since the user waited for it.
// - History: "history temporarily unavailable", and "suggest trying again shortly".
//   The database retries twice before failing, so a timeout reads the same.
// - Detail: the game's data couldn't be retrieved, so say so and offer a retry.
//
// The error's own text is never shown: it can carry hosts, URLs or keys.

import { ApiError, REQUEST_TIMEOUT_CODE } from "./apiError";

export type FailureSurface = "search" | "detail" | "history";

export interface FailureState {
  title: string;
  /** A sentence for the user. Never taken from the error itself. */
  message: string;
  /** The estimated wait before trying again is worth it. */
  retryAfterSeconds: number;
}

/**
 * A fixed estimate, since the API sends no Retry-After header. The user can retry at
 * any time.
 */
export const RETRY_ESTIMATE_SECONDS = 30;

const RETRY_HINT = `Try again in about ${RETRY_ESTIMATE_SECONDS} seconds.`;

type FailureCopy = Pick<FailureState, "title" | "message">;

const UNAVAILABLE: Record<FailureSurface, FailureCopy> = {
  search: {
    title: "Search is unavailable right now",
    message: `We couldn't reach the recommender. ${RETRY_HINT}`,
  },
  detail: {
    title: "Couldn't load this game's details",
    message: `The game's details aren't available right now. ${RETRY_HINT}`,
  },
  history: {
    title: "History is temporarily unavailable",
    message: "We couldn't load your past searches. Try again shortly.",
  },
};

const SEARCH_TIMED_OUT: FailureCopy = {
  title: "Search timed out",
  message: `The recommender took too long to answer. ${RETRY_HINT}`,
};

/** The title and message for `error` on `surface`. */
export function describeFailure(error: unknown, surface: FailureSurface): FailureState {
  const isTimeout = error instanceof ApiError && error.code === REQUEST_TIMEOUT_CODE;
  const copy = surface === "search" && isTimeout ? SEARCH_TIMED_OUT : UNAVAILABLE[surface];
  return { ...copy, retryAfterSeconds: RETRY_ESTIMATE_SECONDS };
}
