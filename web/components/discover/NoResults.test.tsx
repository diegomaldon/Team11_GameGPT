// @vitest-environment jsdom

// TM11-77: the no-results state suggests rephrasing and offers example queries.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EXAMPLE_PROMPTS } from "@/lib/discover/featured";
import { NoResults } from "./NoResults";

afterEach(cleanup);

describe("NoResults", () => {
  it("says nothing matched and shows the reason it is given", () => {
    render(<NoResults message="Try describing it differently." onPick={vi.fn()} />);
    const state = screen.getByRole("status");
    expect(within(state).getByRole("heading", { name: "No matches found" })).toBeTruthy();
    expect(state.textContent).toContain("Try describing it differently.");
  });

  it("offers every example query", () => {
    render(<NoResults message="x" onPick={vi.fn()} />);
    for (const { prompt } of EXAMPLE_PROMPTS) {
      expect(screen.getByRole("button", { name: prompt })).toBeTruthy();
    }
  });

  it("hands back the example that was picked", async () => {
    const onPick = vi.fn();
    render(<NoResults message="x" onPick={onPick} />);
    await userEvent.setup().click(screen.getByRole("button", { name: EXAMPLE_PROMPTS[0].prompt }));
    expect(onPick).toHaveBeenCalledWith(EXAMPLE_PROMPTS[0].prompt);
  });
});
