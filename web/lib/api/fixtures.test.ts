import { describe, it, expect } from "vitest";

import { ApiError } from "./apiError";
import { fixtureGetSyncJob, fixtureRecommend, fixtureStartSync } from "./fixtures";

/**
 * TM11-21 — fixture mode is the stub the frontend builds against, so it has to
 * follow docs/API.md where the generated types can't check it: value ranges
 * and error codes.
 */

describe("fixture stubs follow the API contract", () => {
  it("sends review_score as 0..1, like /api/recommend", () => {
    const { recommendations } = fixtureRecommend("cozy");

    for (const rec of recommendations) {
      expect(rec.review_score).toBeGreaterThanOrEqual(0);
      expect(rec.review_score).toBeLessThanOrEqual(1);
    }
  });

  it("answers an unknown sync job with 404 job_not_found, like the API", () => {
    let caught: unknown;
    try {
      fixtureGetSyncJob("no-such-job");
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught).toMatchObject({ status: 404, code: "job_not_found" });
  });

  it("still polls a known job to completion", () => {
    const { job_id } = fixtureStartSync("76561197960287930");

    let job = fixtureGetSyncJob(job_id);
    while (job.state !== "succeeded") job = fixtureGetSyncJob(job_id);

    expect(job.processed).toBe(job.total);
  });
});
