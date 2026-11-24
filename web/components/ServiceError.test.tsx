// @vitest-environment jsdom

// TM11-77: the "service unavailable" panel shared by search, detail and history.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ServiceError } from "./ServiceError";
import type { FailureState } from "@/lib/api/failureState";

afterEach(cleanup);

const FAILURE: FailureState = {
  title: "Search is unavailable right now",
  message: "We couldn't reach the recommender. Try again in about 30 seconds.",
  retryAfterSeconds: 30,
};

describe("ServiceError", () => {
  it("is an alert with the title and the message", () => {
    render(<ServiceError failure={FAILURE} onRetry={vi.fn()} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(FAILURE.title);
    expect(alert.textContent).toContain(FAILURE.message);
  });

  it("retries when Try again is clicked", async () => {
    const onRetry = vi.fn();
    render(<ServiceError failure={FAILURE} onRetry={onRetry} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
