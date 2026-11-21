// What the Discover page shows before anyone types (TM11-142).
//
// There is no popularity endpoint yet, so these are a curated set of well-known games
// that are all in the seed catalogue (scripts/fixtures/games.json), identified by their
// Steam app id. Art comes from Steam's public CDN by that id. Replace this list with an
// API call once one exists; nothing else on the page needs to change.

export type FeaturedGame = {
  title: string;
  steamAppId: number;
};

export type SpotlightGame = FeaturedGame & {
  /** One or two plain sentences about the game itself. No ratings or sales claims. */
  blurb: string;
};

export const SPOTLIGHT: readonly SpotlightGame[] = [
  {
    title: "Elden Ring",
    steamAppId: 1245620,
    blurb:
      "A vast, punishing open world from FromSoftware. Explore at your own pace, then earn every boss.",
  },
  {
    title: "Baldur's Gate 3",
    steamAppId: 1086940,
    blurb:
      "A party-based, turn-based RPG where your choices reshape the story. Play it solo or in co-op.",
  },
  {
    title: "Hades",
    steamAppId: 1145360,
    blurb:
      "A fast action roguelike. Fight your way out of the underworld, with the story moving on every run.",
  },
];

export const POPULAR: readonly FeaturedGame[] = [
  { title: "Hades", steamAppId: 1145360 },
  { title: "Elden Ring", steamAppId: 1245620 },
  { title: "Stardew Valley", steamAppId: 413150 },
  { title: "Hollow Knight", steamAppId: 367520 },
  { title: "Baldur's Gate 3", steamAppId: 1086940 },
  { title: "Cyberpunk 2077", steamAppId: 1091500 },
  { title: "Celeste", steamAppId: 504230 },
  { title: "Red Dead Redemption 2", steamAppId: 1174180 },
  { title: "The Witcher 3: Wild Hunt", steamAppId: 292030 },
  { title: "Portal 2", steamAppId: 620 },
];

/**
 * The three example prompts under "Describe a vibe" (TM11-74). Clicking one fills the
 * search field so the player can tweak it before searching. One per way players
 * tend to ask: how it should feel, a game they love, and where they play.
 */
export const EXAMPLE_PROMPTS: readonly { label: string; prompt: string }[] = [
  { label: "Mood", prompt: "Calm and low stress, to unwind after work" },
  { label: "Like a game you love", prompt: "Like Stardew Valley, but with more crafting" },
  { label: "Where you play", prompt: "A co-op shooter I can play with friends on Steam" },
];

/**
 * Shown under "No matches found" when a search comes back empty and the API sent no
 * notice saying why (TM11-74), so the page is never blank. TM11-77 adds the example
 * queries under it (components/discover/NoResults.tsx).
 */
export const NO_RESULTS_MESSAGE =
  "Try describing it differently, or more broadly: a mood, a genre or a game you like.";

/** The prompt a featured game's "Find games like this" sends. */
export function promptLike(title: string): string {
  return `Games like ${title}`;
}

const STEAM_ART = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps";

/** Portrait box art, 600×900. */
export function steamCoverUrl(appId: number): string {
  return `${STEAM_ART}/${appId}/library_600x900.jpg`;
}

/** Wide key art for a hero, 1920×620. */
export function steamHeroUrl(appId: number): string {
  return `${STEAM_ART}/${appId}/library_hero.jpg`;
}
