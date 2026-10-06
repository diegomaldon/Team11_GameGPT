// @vitest-environment jsdom

import { describe, expect, it, afterEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LibrarySyncJob } from "../../lib/api/types";
import { FAILED_RUN_MESSAGE, SyncProgress } from "./SyncProgress";

afterEach(cleanup);

function job(over: Partial<LibrarySyncJob> = {}): LibrarySyncJob {
  return {
    job_id: "job-1",
    state: "importing",
    total: 500,
    processed: 120,
    synced: 120,
    failed: [],
    source: "steam",
    error: null,
    started_at: "2026-10-06T14:00:00Z",
    finished_at: null,
    ...over,
  };
}

describe("SyncProgress (TM11-49)", () => {
  it("renders nothing before an import starts", () => {
    const { container } = render(<SyncProgress job={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows determinate progress while importing", () => {
    render(<SyncProgress job={job()} />);
    expect(screen.getByRole("status").textContent).toContain("Importing 120 of 500 games");
    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).toBe("120");
    expect(bar.getAttribute("aria-valuemax")).toBe("500");
  });

  it("shows an indeterminate bar while Steam is being fetched", () => {
    render(<SyncProgress job={job({ state: "fetching", total: 0, processed: 0 })} />);
    expect(screen.getByRole("status").textContent).toContain("Fetching your library");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();
  });

  it("lists per-title failures next to a successful import", () => {
    render(
      <SyncProgress
        job={job({
          state: "succeeded",
          processed: 500,
          synced: 498,
          failed: [
            { steam_appid: 7, title: "Broken Game", reason: "DataError: integer out of range" },
            { steam_appid: -5, title: null, reason: "invalid appid -5" },
          ],
        })}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("Imported 498 games");
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByText(/2 titles couldn.t be imported/)).toBeTruthy();
    expect(screen.getByText("Broken Game")).toBeTruthy();
    expect(screen.getByText("App -5")).toBeTruthy();
  });

  it("says the previous library is unchanged when the run fails, and offers a retry", async () => {
    const onRetry = vi.fn();
    render(<SyncProgress job={job({ state: "failed" })} onRetry={onRetry} />);
    expect(screen.getByRole("alert").textContent).toContain(FAILED_RUN_MESSAGE);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("shows a tracking error even with no job", () => {
    render(<SyncProgress job={null} error="We lost track of the import." />);
    expect(screen.getByRole("alert").textContent).toContain("We lost track of the import.");
  });
});
