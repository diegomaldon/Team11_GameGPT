// @vitest-environment jsdom

// TM11-75: one Discover result card. Each describe block is an acceptance criterion
// (AC-02, rank order, is covered across cards in the page test).

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Recommendation } from "@/lib/api/types";
import { RecommendationCard } from "./RecommendationCard";

// next/image needs Next's runtime; a plain element carrying the URL is enough to see
// which art the card asked for.
vi.mock("next/image", () => ({
  default: (props: { src: string; alt: string }) => (
    <span data-testid="cover-art" data-src={props.src} aria-label={props.alt} />
  ),
}));

const HADES: Recommendation = {
  rank: 1,
  game_id: "g-hades",
  title: "Hades",
  reason: "Fast runs you can finish in half an hour, with the story moving on every time.",
  steam_appid: 1145360,
  review_score: 0.98,
  platforms: ["xbox", "steam", "epic"],
};

const BARE: Recommendation = {
  rank: 2,
  game_id: "g-bare",
  title: "Unknown Indie Gem",
  reason: "Short, calm puzzles that match the relaxed evening you described.",
  steam_appid: null,
  review_score: null,
};

function renderCard(rec: Recommendation, overrides = {}) {
  const props = { rec, index: 0, onVote: vi.fn(), onOpen: vi.fn(), ...overrides };
  render(
    <ul>
      <RecommendationCard {...props} />
    </ul>,
  );
  return props;
}

const card = () => screen.getByTestId("recommendation-card");

afterEach(cleanup);

describe("AC-01: ranked card with title, art, platforms and explanation", () => {
  it("shows the rank, title, art, score and explanation", () => {
    renderCard(HADES);
    expect(within(card()).getByRole("heading", { name: /1\.\s*Hades/ })).toBeTruthy();
    expect(within(card()).getByTestId("cover-art").getAttribute("data-src")).toContain("1145360");
    expect(card().textContent).toContain("98%");
    expect(within(card()).getByText(HADES.reason)).toBeTruthy();
  });

  it("lists every platform, labelled, in badge order", () => {
    renderCard(HADES);
    const list = within(card()).getByRole("list", { name: "Platforms" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Steam",
      "Xbox",
      "Epic",
    ]);
  });

  it("marks the top pick", () => {
    renderCard(HADES);
    expect(within(card()).getByText("1", { selector: "span[aria-hidden]" })).toBeTruthy();
  });

  it("keeps the Steam link and the vote buttons", async () => {
    const user = userEvent.setup();
    const { onVote } = renderCard(HADES);
    expect(
      within(card()).getByRole("link", { name: /view on steam/i }).getAttribute("href"),
    ).toBe("https://store.steampowered.com/app/1145360");
    await user.click(within(card()).getByRole("button", { name: "Thumbs up Hades" }));
    expect(onVote).toHaveBeenCalledWith(HADES, "up");
  });

  it("shows the active vote", () => {
    renderCard(HADES, { vote: "down" });
    expect(
      within(card()).getByRole("button", { name: "Thumbs down Hades" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });
});

describe("AC-03: the card opens the detail panel", () => {
  it("opens it from the title, passing the button so focus can return", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderCard(HADES);
    const title = within(card()).getByRole("button", { name: "Hades, open details" });
    expect(title.getAttribute("aria-haspopup")).toBe("dialog");
    await user.click(title);
    expect(onOpen).toHaveBeenCalledWith(HADES, title);
  });

  it("opens it from the keyboard", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderCard(HADES);
    within(card()).getByRole("button", { name: /open details/ }).focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("AC-04: renders correctly with no art or scores", () => {
  it("shows the title's initials instead of a broken image", () => {
    renderCard(BARE);
    expect(within(card()).queryByTestId("cover-art")).toBeNull();
    expect(card().textContent).toContain("UI");
  });

  it("says there is no score instead of leaving a gap", () => {
    renderCard(BARE);
    expect(card().textContent).toContain("No score yet");
    expect(card().textContent).not.toMatch(/\d+%/);
  });

  it("says when no platforms are listed", () => {
    renderCard(BARE);
    expect(within(card()).getByRole("list", { name: "Platforms" }).textContent).toBe(
      "Platforms not listed",
    );
  });

  it("drops the Steam link when there's no app id, but keeps the votes", () => {
    renderCard(BARE);
    expect(within(card()).queryByRole("link")).toBeNull();
    expect(within(card()).getByRole("button", { name: "Thumbs up Unknown Indie Gem" })).toBeTruthy();
  });

  it("still shows the explanation", () => {
    renderCard(BARE);
    expect(within(card()).getByText(BARE.reason)).toBeTruthy();
  });
});
