// TM11-77: what the user is told when search, a game's details or their history
// can't be loaded, following the CIS453 rainy-day scenarios.

import { describe, expect, it } from "vitest";
import { ApiError, REQUEST_TIMEOUT_CODE } from "./apiError";
import { describeFailure, RETRY_ESTIMATE_SECONDS } from "./failureState";

const timedOut = new ApiError("POST /api/recommend timed out", 0, null, REQUEST_TIMEOUT_CODE);
const dbDown = new ApiError("GET /api/history failed", 503, "req-1", "db_unavailable");
const rankerDown = new ApiError(
  "POST /api/recommend failed",
  502,
  "req-2",
  "recommendation_failed",
);
const RETRY_HINT = `Try again in about ${RETRY_ESTIMATE_SECONDS} seconds.`;

describe("describeFailure: search", () => {
  it("says search is unavailable, with an estimated retry time", () => {
    const failure = describeFailure(rankerDown, "search");
    expect(failure.title).toBe("Search is unavailable right now");
    expect(failure.message).toBe(`We couldn't reach the recommender. ${RETRY_HINT}`);
    expect(failure.retryAfterSeconds).toBe(RETRY_ESTIMATE_SECONDS);
  });

  it("treats the API being unreachable the same way", () => {
    const failure = describeFailure(new TypeError("Failed to fetch"), "search");
    expect(failure.title).toBe("Search is unavailable right now");
  });

  it("says a search that ran out of time timed out", () => {
    const failure = describeFailure(timedOut, "search");
    expect(failure.title).toBe("Search timed out");
    expect(failure.message).toBe(`The recommender took too long to answer. ${RETRY_HINT}`);
  });
});

describe("describeFailure: history", () => {
  it("says history is temporarily unavailable and to try again shortly", () => {
    const failure = describeFailure(dbDown, "history");
    expect(failure.title).toBe("History is temporarily unavailable");
    expect(failure.message).toBe("We couldn't load your past searches. Try again shortly.");
  });

  it("says the same when the database doesn't answer in time", () => {
    expect(describeFailure(timedOut, "history")).toEqual(describeFailure(dbDown, "history"));
  });
});

describe("describeFailure: detail", () => {
  it("says the game's details couldn't be loaded", () => {
    const failure = describeFailure(dbDown, "detail");
    expect(failure.title).toBe("Couldn't load this game's details");
    expect(failure.message).toBe(
      `The game's details aren't available right now. ${RETRY_HINT}`,
    );
  });

  it("says the same when the database doesn't answer in time", () => {
    expect(describeFailure(timedOut, "detail")).toEqual(describeFailure(dbDown, "detail"));
  });
});

it("never repeats the error's own text to the user", () => {
  const leaky = new Error("connection to postgres://admin:secret@db.internal failed");
  for (const surface of ["search", "detail", "history"] as const) {
    const { title, message } = describeFailure(leaky, surface);
    expect(`${title} ${message}`).not.toMatch(/postgres|secret|db\.internal/);
  }
});
