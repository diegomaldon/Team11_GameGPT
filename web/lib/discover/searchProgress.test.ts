// TM11-76 (REQ040): what the Discover page says while a search runs.

import { describe, expect, it } from "vitest";
import { searchProgressMessage } from "./searchProgress";

describe("searchProgressMessage", () => {
  it("starts by reading the request", () => {
    expect(searchProgressMessage(0)).toBe("Reading your request…");
    expect(searchProgressMessage(499)).toBe("Reading your request…");
  });

  it("moves on to searching once parse and embed would be done", () => {
    expect(searchProgressMessage(500)).toBe("Searching the catalogue…");
    expect(searchProgressMessage(1749)).toBe("Searching the catalogue…");
  });

  it("says it is ranking for the rest of the 10 second budget", () => {
    expect(searchProgressMessage(1750)).toBe("Ranking the best matches…");
    expect(searchProgressMessage(9999)).toBe("Ranking the best matches…");
  });

  it("admits a search that runs past the budget is slow", () => {
    expect(searchProgressMessage(10_000)).toBe("This is taking longer than usual. Still working…");
    expect(searchProgressMessage(60_000)).toBe("This is taking longer than usual. Still working…");
  });

  it("treats a clock that went backwards as the start", () => {
    expect(searchProgressMessage(-50)).toBe("Reading your request…");
    expect(searchProgressMessage(Number.NaN)).toBe("Reading your request…");
  });
});
