// @vitest-environment jsdom

// TM11-74 (REQ011): the natural-language search on Discover. Each describe block is
// one acceptance criterion. The API is mocked; AC-04 answers with the same canned
// response NEXT_PUBLIC_USE_FIXTURES serves, so the page is proven against the stub.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, getGame, getHistory, recommend, REQUEST_TIMEOUT_CODE } from "@/lib/api/client";
import { fixtureGetGame, fixtureGetHistory, fixtureRecommend } from "@/lib/api/fixtures";
import { EXAMPLE_PROMPTS, NO_RESULTS_MESSAGE } from "@/lib/discover/featured";
import type { RecommendResponse } from "@/lib/api/types";
import DiscoverPage from "./page";

vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  recommend: vi.fn(),
  sendFeedback: vi.fn(),
  getHistory: vi.fn(),
  getGame: vi.fn(),
}));
// The featured strips and cover art aren't under test and pull in next/image.
vi.mock("@/components/discover/Spotlight", () => ({ Spotlight: () => null }));
vi.mock("@/components/discover/PopularStrip", () => ({ PopularStrip: () => null }));
vi.mock("@/components/discover/GameArt", () => ({ GameArt: () => null }));

const field = () => screen.getByRole("textbox", { name: "Describe the game you want" });
const submit = () => screen.getByRole("button", { name: /find games|thinking/i });
const searched = () => screen.queryByTestId("searched-query");

/** A promise the test resolves itself, to look at the page mid-search. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(recommend).mockImplementation(async (q) => fixtureRecommend(q));
  vi.mocked(getHistory).mockImplementation(async (limit) => fixtureGetHistory(limit));
  vi.mocked(getGame).mockImplementation(async (id) => fixtureGetGame(id));
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(min-width: 640px)",
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(cleanup);

describe("AC-01: prominent freeform input with submit and keyboard support", () => {
  it("has a labelled text field and a submit button inside a search landmark", () => {
    render(<DiscoverPage />);
    const form = screen.getByRole("search", { name: "Find games" });
    expect(within(form).getByRole("textbox", { name: "Describe the game you want" })).toBeTruthy();
    expect(within(form).getByRole("button", { name: /find games/i })).toBeTruthy();
  });

  it("keeps submit disabled until something other than spaces is typed", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    await user.type(field(), "   ");
    expect((submit() as HTMLButtonElement).disabled).toBe(true);
    await user.type(field(), "roguelike");
    expect((submit() as HTMLButtonElement).disabled).toBe(false);
  });

  it("searches when the button is clicked", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "a chill puzzle game");
    await user.click(submit());
    expect(recommend).toHaveBeenCalledWith("a chill puzzle game");
  });

  it("searches on Enter, trimmed", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "  metroidvania with a big map  {Enter}");
    expect(recommend).toHaveBeenCalledWith("metroidvania with a big map");
  });

  it("does not start a second search when Enter is pressed again mid-search", async () => {
    const pending = deferred<RecommendResponse>();
    vi.mocked(recommend).mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "cozy{Enter}");
    await user.type(field(), "{Enter}");
    expect(recommend).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(fixtureRecommend("cozy")));
  });

  it("clears the field on Escape", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "something scary");
    await user.keyboard("{Escape}");
    expect((field() as HTMLInputElement).value).toBe("");
  });

  it("jumps to the field when / is pressed elsewhere on the page", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("/");
    expect(document.activeElement).toBe(field());
    // The slash is a shortcut, not typed into the field.
    expect((field() as HTMLInputElement).value).toBe("");
  });

  it("types a / normally when already in the field", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "PC/Xbox co-op");
    expect((field() as HTMLInputElement).value).toBe("PC/Xbox co-op");
  });

  it("limits the query to the API's 500 characters", () => {
    render(<DiscoverPage />);
    expect((field() as HTMLInputElement).maxLength).toBe(500);
  });
});

describe("AC-02: three example prompts that populate the field on click", () => {
  it("shows exactly three examples", () => {
    render(<DiscoverPage />);
    const list = screen.getByRole("list", { name: "Example searches" });
    expect(within(list).getAllByRole("button")).toHaveLength(3);
  });

  it.each(EXAMPLE_PROMPTS.map((e) => [e.label, e.prompt]))(
    "%s: clicking it fills the field and focuses it without searching",
    async (_label, prompt) => {
      const user = userEvent.setup();
      render(<DiscoverPage />);
      await user.click(screen.getByRole("button", { name: new RegExp(prompt) }));
      expect((field() as HTMLInputElement).value).toBe(prompt);
      expect(document.activeElement).toBe(field());
      expect(recommend).not.toHaveBeenCalled();
    },
  );

  it("replaces whatever was typed, and Enter then searches the example", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "half-typed");
    const [first] = EXAMPLE_PROMPTS;
    await user.click(screen.getByRole("button", { name: new RegExp(first.prompt) }));
    await user.keyboard("{Enter}");
    expect(recommend).toHaveBeenCalledWith(first.prompt);
  });
});

describe("AC-03: the previous query stays visible with the results", () => {
  it("shows the searched query above the results", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "a chill game for a podcast night{Enter}");
    await screen.findByText(/picks for your vibe/);
    expect(searched()?.textContent).toContain("a chill game for a podcast night");
  });

  it("shows it while the search is still running", async () => {
    const pending = deferred<RecommendResponse>();
    vi.mocked(recommend).mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "space sim{Enter}");
    expect(searched()?.textContent).toMatch(/Searching for.*space sim/);
    await act(async () => pending.resolve(fixtureRecommend("space sim")));
    expect(searched()?.textContent).toMatch(/You searched for.*space sim/);
  });

  it("keeps showing what was searched while a new query is typed", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "horror{Enter}");
    await screen.findByText(/picks for your vibe/);
    await user.clear(field());
    await user.type(field(), "something else");
    expect(searched()?.textContent).toContain("horror");
    expect(searched()?.textContent).not.toContain("something else");
  });

  it("puts the previous query back in the field from Edit this search", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "horror{Enter}");
    await screen.findByText(/picks for your vibe/);
    await user.clear(field());
    await user.click(screen.getByRole("button", { name: "Edit this search" }));
    expect((field() as HTMLInputElement).value).toBe("horror");
    expect(document.activeElement).toBe(field());
  });

  it("shows it next to an error, too", async () => {
    vi.mocked(recommend).mockRejectedValueOnce(new Error("down"));
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "racing{Enter}");
    await screen.findByRole("alert");
    expect(searched()?.textContent).toContain("racing");
  });

  it("shows it next to a TM11-66 all-owned notice with no results", async () => {
    vi.mocked(recommend).mockResolvedValueOnce({
      query_id: "q-1",
      query: "cozy farming",
      recommendations: [],
      notice: { code: "all_owned", message: "You already own every game that matches." },
    });
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "cozy farming{Enter}");
    await screen.findByText("You already own every game that matches.");
    expect(searched()?.textContent).toContain("cozy farming");
    expect(screen.queryByText(/picks for your vibe/)).toBeNull();
  });

  it("says so when the API returns no results and no notice", async () => {
    vi.mocked(recommend).mockResolvedValueOnce({
      query_id: "q-2",
      query: "obscure thing",
      recommendations: [],
      notice: null,
    });
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "obscure thing{Enter}");
    await screen.findByText(NO_RESULTS_MESSAGE);
    expect(searched()?.textContent).toContain("obscure thing");
    expect(screen.queryByText(/picks for your vibe/)).toBeNull();
  });

  it("shows the API's notice instead of the generic message when there is one", async () => {
    vi.mocked(recommend).mockResolvedValueOnce({
      query_id: "q-3",
      query: "cozy farming",
      recommendations: [],
      notice: { code: "all_owned", message: "You already own every game that matches." },
    });
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "cozy farming{Enter}");
    await screen.findByText("You already own every game that matches.");
    expect(screen.queryByText(NO_RESULTS_MESSAGE)).toBeNull();
  });

  it("shows nothing before the first search", () => {
    render(<DiscoverPage />);
    expect(searched()).toBeNull();
  });
});

describe("AC-04: works against the stubbed response", () => {
  it("renders the fixture's ranked picks with their reasons", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "a chill game{Enter}");
    const expected = fixtureRecommend("a chill game");
    await screen.findByText(`${expected.recommendations.length} picks for your vibe`);
    for (const rec of expected.recommendations) {
      expect(screen.getByRole("heading", { name: new RegExp(rec.title) })).toBeTruthy();
      expect(screen.getByText(rec.reason)).toBeTruthy();
    }
  });

  it("re-enables the field's submit once the stub answers", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "a chill game{Enter}");
    await waitFor(() => expect(submit().textContent).toMatch(/find games/i));
    fireEvent.change(field(), { target: { value: "next one" } });
    expect((submit() as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("TM11-76: the search's loading state", () => {
  afterEach(() => vi.useRealTimers());

  it("shows placeholder cards and says how far the search has got", async () => {
    vi.useFakeTimers();
    const pending = deferred<RecommendResponse>();
    vi.mocked(recommend).mockReturnValueOnce(pending.promise);
    render(<DiscoverPage />);
    fireEvent.change(field(), { target: { value: "space sim" } });
    fireEvent.click(submit());

    expect(screen.getAllByTestId("result-skeleton-card")).toHaveLength(3);
    expect(screen.getByText("Reading your request…")).toBeTruthy();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("Searching the catalogue…")).toBeTruthy();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("Ranking the best matches…")).toBeTruthy();
    act(() => vi.advanceTimersByTime(8000));
    expect(screen.getByText("This is taking longer than usual. Still working…")).toBeTruthy();

    await act(async () => pending.resolve(fixtureRecommend("space sim")));
    expect(screen.queryByTestId("result-skeleton-card")).toBeNull();
    expect(screen.getByText(/picks for your vibe/)).toBeTruthy();
  });

  it("starts the progress message over for the next search", async () => {
    vi.useFakeTimers();
    const first = deferred<RecommendResponse>();
    const second = deferred<RecommendResponse>();
    vi.mocked(recommend).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(<DiscoverPage />);
    fireEvent.change(field(), { target: { value: "space sim" } });
    fireEvent.click(submit());
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByText("Ranking the best matches…")).toBeTruthy();
    await act(async () => first.resolve(fixtureRecommend("space sim")));

    fireEvent.change(field(), { target: { value: "racing" } });
    fireEvent.click(submit());
    expect(screen.getByText("Reading your request…")).toBeTruthy();
    await act(async () => second.resolve(fixtureRecommend("racing")));
  });
});

describe("TM11-77: no-results and error states from the rainy-day scenarios", () => {
  const empty = (notice: RecommendResponse["notice"] = null): RecommendResponse => ({
    query_id: "q-9",
    query: "obscure thing",
    recommendations: [],
    notice,
  });
  const noResults = () =>
    screen.getByRole("heading", { name: "No matches found" }).closest<HTMLElement>("[role=status]")!;

  it("suggests rephrasing and offers example queries when nothing matches", async () => {
    vi.mocked(recommend).mockResolvedValueOnce(empty());
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "obscure thing{Enter}");

    await screen.findByRole("heading", { name: "No matches found" });
    expect(noResults().textContent).toContain(NO_RESULTS_MESSAGE);
    for (const { prompt } of EXAMPLE_PROMPTS) {
      expect(within(noResults()).getByRole("button", { name: prompt })).toBeTruthy();
    }
  });

  it("fills the field from an example without searching, ready to tweak", async () => {
    vi.mocked(recommend).mockResolvedValueOnce(empty());
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "obscure thing{Enter}");
    await screen.findByRole("heading", { name: "No matches found" });

    const example = EXAMPLE_PROMPTS[1].prompt;
    await user.click(within(noResults()).getByRole("button", { name: example }));
    expect((field() as HTMLInputElement).value).toBe(example);
    expect(document.activeElement).toBe(field());
    expect(recommend).toHaveBeenCalledTimes(1);
  });

  it("offers the same examples when everything that matched is already owned", async () => {
    const message = "You already own every game that matches.";
    vi.mocked(recommend).mockResolvedValueOnce(empty({ code: "all_owned", message }));
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "cozy farming{Enter}");

    await screen.findByRole("heading", { name: "No matches found" });
    expect(noResults().textContent).toContain(message);
    expect(noResults().textContent).not.toContain(NO_RESULTS_MESSAGE);
  });

  it("says search is unavailable, gives a retry time and retries the same query", async () => {
    vi.mocked(recommend).mockRejectedValueOnce(
      new ApiError("POST /api/recommend failed", 502, "req-1", "recommendation_failed"),
    );
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "racing{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Search is unavailable right now");
    expect(alert.textContent).toMatch(/Try again in about \d+ seconds/);
    await user.clear(field());
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(recommend).toHaveBeenLastCalledWith("racing");
    expect(await screen.findByText(/picks for your vibe/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says when the search timed out", async () => {
    vi.mocked(recommend).mockRejectedValueOnce(
      new ApiError("POST /api/recommend timed out", 0, null, REQUEST_TIMEOUT_CODE),
    );
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await user.type(field(), "racing{Enter}");

    expect((await screen.findByRole("alert")).textContent).toContain("Search timed out");
  });
});

describe("TM11-75: result cards on the page", () => {
  const shuffled: RecommendResponse = {
    query_id: "q-75",
    query: "roguelike",
    recommendations: [
      { rank: 3, title: "Third Pick", reason: "Third reason.", platforms: ["steam"] },
      { rank: 1, title: "First Pick", reason: "First reason.", platforms: ["xbox"] },
      { rank: 2, title: "Second Pick", reason: "Second reason.", platforms: [] },
    ],
  };

  async function search(user: ReturnType<typeof userEvent.setup>, q = "roguelike") {
    await user.type(field(), `${q}{Enter}`);
    await screen.findByText(/picks for your vibe/);
  }

  it("AC-02: shows the cards in the pipeline's rank order", async () => {
    vi.mocked(recommend).mockResolvedValueOnce(shuffled);
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user);
    const titles = screen
      .getAllByTestId("recommendation-card")
      .map((c) => within(c).getByRole("heading").textContent);
    expect(titles).toEqual([
      expect.stringContaining("First Pick"),
      expect.stringContaining("Second Pick"),
      expect.stringContaining("Third Pick"),
    ]);
  });

  it("AC-01: every fixture pick gets a card with its platforms", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user, "a chill game");
    const cards = screen.getAllByTestId("recommendation-card");
    expect(cards).toHaveLength(fixtureRecommend("x").recommendations.length);
    expect(within(cards[0]).getByRole("list", { name: "Platforms" }).textContent).toContain("Steam");
  });

  it("AC-03: a card's title opens the detail panel, and closing returns focus to it", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user, "a chill game");
    const [first] = fixtureRecommend("x").recommendations;
    const opener = screen.getByRole("button", { name: `${first.title}, open details` });

    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: first.title });
    expect(within(dialog).getByText(first.reason)).toBeTruthy();
    expect(within(dialog).getByText("Steam, Xbox")).toBeTruthy();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("AC-04: the panel says what's missing for a game with no art, score or store data", async () => {
    vi.mocked(recommend).mockResolvedValueOnce({
      query_id: "q-bare",
      query: "obscure",
      recommendations: [{ rank: 1, title: "Bare Game", reason: "A quiet fit for your evening." }],
    });
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user, "obscure");
    await user.click(screen.getByRole("button", { name: "Bare Game, open details" }));
    const dialog = screen.getByRole("dialog", { name: "Bare Game" });
    // No game_id, so nothing to fetch (TM11-78): every field says it's unavailable.
    expect(getGame).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain("isn't in our catalogue yet");
    expect(within(dialog).getAllByText("Unavailable").length).toBeGreaterThanOrEqual(5);
    expect(within(dialog).queryByRole("link")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("TM11-78 AC2: the detail panel opens from a card and from history", () => {
  async function search(user: ReturnType<typeof userEvent.setup>, q = "a chill game") {
    await user.type(field(), `${q}{Enter}`);
    await screen.findByText(/picks for your vibe/);
  }

  it("a card fetches its game's full details into the panel", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user);
    const [first] = fixtureRecommend("x").recommendations;

    await user.click(screen.getByRole("button", { name: `${first.title}, open details` }));

    const dialog = screen.getByRole("dialog", { name: first.title });
    expect(getGame).toHaveBeenCalledWith(first.game_id);
    expect(await within(dialog).findByText(/inherited your grandfather's old farm plot/)).toBeTruthy();
    expect(within(dialog).getByText("89 / 100")).toBeTruthy(); // critic score, not on the card
  });

  it("lists recent searches, and any of their games opens the panel", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    const recent = await screen.findByRole("region", { name: "Recent searches" });
    const [entry] = fixtureGetHistory(1).items;
    expect(within(recent).getByText(entry.query)).toBeTruthy();

    const opener = within(recent).getByRole("button", { name: "Dorfromantik" });
    await user.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Dorfromantik" });
    expect(getGame).toHaveBeenCalledWith("22222222-2222-4222-8222-222222222222");
    expect(await within(dialog).findByText(/ever-growing village landscape/)).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(opener);
  });

  it("reloads recent searches after a new search, so it shows up", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await screen.findByRole("region", { name: "Recent searches" });
    expect(getHistory).toHaveBeenCalledTimes(1);

    await search(user);

    await waitFor(() => expect(getHistory).toHaveBeenCalledTimes(2));
  });

  it("says history is unavailable when it can't be read, with a retry", async () => {
    vi.mocked(getHistory).mockRejectedValueOnce(new ApiError("GET /api/history failed", 503));
    const user = userEvent.setup();
    render(<DiscoverPage />);
    const recent = await screen.findByRole("region", { name: "Recent searches" });

    const alert = await within(recent).findByRole("alert");
    expect(alert.textContent).toContain("History is temporarily unavailable");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await within(recent).findByText(fixtureGetHistory(1).items[0].query)).toBeTruthy();
  });

  it("a click anywhere on a card opens its panel too", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user);
    const [first] = fixtureRecommend("x").recommendations;

    await user.click(screen.getByText(first.reason));

    const dialog = screen.getByRole("dialog", { name: first.title });
    expect(await within(dialog).findByTestId("game-detail")).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: `${first.title}, open details` }),
    );
  });

  it("doesn't jump to the search field on / while the panel is open", async () => {
    const user = userEvent.setup();
    render(<DiscoverPage />);
    await search(user);
    const [first] = fixtureRecommend("x").recommendations;
    await user.click(screen.getByRole("button", { name: `${first.title}, open details` }));
    await screen.findByTestId("game-detail");

    await user.keyboard("/");

    expect(document.activeElement).not.toBe(field());
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
