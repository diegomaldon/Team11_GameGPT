// TM11-75: ordering, scores and platform labels for the Discover result cards.
import { describe, expect, it } from "vitest";
import type { Recommendation } from "@/lib/api/types";
import { MAX_CARDS, platformLabels, rankedCards, scorePct } from "./recommendations";

const rec = (rank: number, title = `Game ${rank}`): Recommendation => ({
  rank,
  title,
  reason: `Why ${title} fits.`,
});

describe("rankedCards (AC-02: rank order preserved from the pipeline)", () => {
  it("keeps an already-ranked list as is", () => {
    expect(rankedCards([rec(1), rec(2), rec(3)]).map((r) => r.rank)).toEqual([1, 2, 3]);
  });

  it("orders by the pipeline's rank, not the array order", () => {
    expect(rankedCards([rec(3), rec(1), rec(2)]).map((r) => r.rank)).toEqual([1, 2, 3]);
  });

  it("keeps the API's order for a tied rank", () => {
    const out = rankedCards([rec(1, "First"), rec(1, "Second")]);
    expect(out.map((r) => r.title)).toEqual(["First", "Second"]);
  });

  it("shows at most five cards (REQ015's 3 to 5)", () => {
    const six = [1, 2, 3, 4, 5, 6].map((n) => rec(n));
    expect(rankedCards(six).map((r) => r.rank)).toEqual([1, 2, 3, 4, 5]);
    expect(MAX_CARDS).toBe(5);
  });

  it("does not change the list it was given", () => {
    const input = [rec(2), rec(1)];
    rankedCards(input);
    expect(input.map((r) => r.rank)).toEqual([2, 1]);
  });
});

describe("scorePct (AC-04: games with no score)", () => {
  it("turns a 0-1 score into a percentage", () => {
    expect(scorePct(0.975)).toBe(98);
  });

  it("keeps a 0-100 score as a percentage", () => {
    expect(scorePct(87)).toBe(87);
  });

  it("is null for a missing score, so the card can say so", () => {
    expect(scorePct(null)).toBeNull();
    expect(scorePct(undefined)).toBeNull();
    expect(scorePct(Number.NaN)).toBeNull();
  });
});

describe("platformLabels (AC-01: platforms on the card)", () => {
  it("labels known stores in the library's badge order", () => {
    expect(platformLabels(["epic", "steam", "xbox"])).toEqual(["Steam", "Xbox", "Epic"]);
  });

  it("ignores case, blanks and repeats", () => {
    expect(platformLabels(["STEAM", " steam ", "", "Xbox"])).toEqual(["Steam", "Xbox"]);
  });

  it("keeps an unknown store, after the known ones", () => {
    expect(platformLabels(["gog", "steam"])).toEqual(["Steam", "Gog"]);
  });

  it("is empty when the API sends none", () => {
    expect(platformLabels(undefined)).toEqual([]);
    expect(platformLabels(null)).toEqual([]);
    expect(platformLabels([])).toEqual([]);
  });
});
