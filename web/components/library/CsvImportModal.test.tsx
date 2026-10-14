// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CsvPreviewResponse } from "@/lib/api/types";
import { ApiError } from "@/lib/api/apiError";
import { commitCsvImport, previewCsvImport } from "@/lib/api/client";
import { CsvImportModal } from "./CsvImportModal";

vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  previewCsvImport: vi.fn(),
  commitCsvImport: vi.fn(),
}));

const CSV = "title\nHades\nMystery Game\nHalo Infinite\n";

const PREVIEW: CsvPreviewResponse = {
  platform: "epic",
  matched: 1,
  needs_review: 1,
  skipped: 1,
  rows: [
    { row_number: 2, title: "Hades", status: "matched", game_id: "g1", game_title: "Hades",
      message: null },
    { row_number: 3, title: "Mystery Game", status: "unmatched", game_id: null, game_title: null,
      message: "No game found with this title. Saved for review." },
    { row_number: 4, title: "Halo Infinite", status: "already_owned", game_id: "g2",
      game_title: "Halo Infinite", message: "Already in your library." },
  ],
};

const onImported = vi.fn();

function renderModal() {
  return render(<CsvImportModal open onClose={vi.fn()} onImported={onImported} />);
}

async function pickFile(name = "library.csv", text = CSV, user = userEvent.setup()) {
  const file = new File([text], name, { type: "text/csv" });
  await user.upload(screen.getByLabelText("CSV file"), file);
  await user.click(screen.getByRole("button", { name: "Review file" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(previewCsvImport).mockResolvedValue(PREVIEW);
  vi.mocked(commitCsvImport).mockResolvedValue({
    added: 1, needs_review: 1, skipped: 1, import_id: null,
  });
});
afterEach(cleanup);

describe("CsvImportModal: per-row match results and a review step (TM11-55)", () => {
  it("shows every row's outcome before anything is saved", async () => {
    renderModal();
    await pickFile();

    expect(previewCsvImport).toHaveBeenCalledWith("epic", CSV);
    const rows = within(await screen.findByRole("list", { name: "CSV rows" })).getAllByRole(
      "listitem",
    );
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Will be added"),
      expect.stringContaining("No game found with this title"),
      expect.stringContaining("Already in your library"),
    ]);
    expect(commitCsvImport).not.toHaveBeenCalled();
  });

  it("sends the chosen platform", async () => {
    const user = userEvent.setup();
    renderModal();
    await user.selectOptions(screen.getByLabelText(/Platform/), "xbox");
    await pickFile("library.csv", CSV, user);
    expect(previewCsvImport).toHaveBeenCalledWith("xbox", CSV);
  });

  it("only adds after confirming, and leaves out unticked rows", async () => {
    renderModal();
    const user = await pickFile();

    await user.click(await screen.findByLabelText("Keep row 3: Mystery Game"));
    await user.click(screen.getByRole("button", { name: "Add 1 game" }));

    expect(commitCsvImport).toHaveBeenCalledWith("epic", CSV, [3]);
    expect(await screen.findByText("Added 1 game to your library.")).toBeTruthy();
    expect(onImported).toHaveBeenCalledOnce();
  });

  it("can't untick rows that are skipped anyway", async () => {
    renderModal();
    await pickFile();
    await screen.findByRole("list", { name: "CSV rows" });
    expect(screen.queryByLabelText("Keep row 4: Halo Infinite")).toBeNull();
  });

  it("offers to save for review when nothing matched", async () => {
    vi.mocked(previewCsvImport).mockResolvedValue({
      ...PREVIEW, matched: 0, rows: [PREVIEW.rows[1]],
    });
    renderModal();
    await pickFile();
    expect(await screen.findByRole("button", { name: "Save for review" })).toBeTruthy();
  });
});

describe("CsvImportModal: unmatched rows reported back (TM11-55)", () => {
  it("says how many were saved for review", async () => {
    renderModal();
    const user = await pickFile();
    await user.click(await screen.findByRole("button", { name: "Add 1 game" }));
    expect((await screen.findByRole("status")).textContent).toContain("1 saved for review");
  });
});

describe("CsvImportModal: malformed file rejected with a useful message (TM11-55)", () => {
  it("shows the server's message for a bad file", async () => {
    const message = 'The first row must be a header with a "title" column, separated by commas.';
    vi.mocked(previewCsvImport).mockRejectedValue(
      new ApiError("POST failed", 422, null, "missing_title_column", message),
    );
    renderModal();
    await pickFile();
    expect((await screen.findByRole("alert")).textContent).toBe(message);
  });

  it("refuses a file that isn't a CSV without sending it", async () => {
    renderModal();
    await pickFile("library.xlsx", CSV, userEvent.setup({ applyAccept: false }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose a .csv file.");
    expect(previewCsvImport).not.toHaveBeenCalled();
  });

  it("asks for a file when none was picked", async () => {
    const user = userEvent.setup();
    renderModal();
    await user.click(screen.getByRole("button", { name: "Review file" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose a CSV file first.");
  });

  it("never shows raw error text from an unexpected failure", async () => {
    vi.mocked(previewCsvImport).mockRejectedValue(new Error("TypeError at fetch: 10.0.0.5"));
    renderModal();
    await pickFile();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Something went wrong. Nothing was changed.",
    );
  });
});
