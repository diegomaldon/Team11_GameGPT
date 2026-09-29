// Mock domain data for the dummy UI. No backend — everything here is seeded
// and mutated client-side, then persisted to localStorage by the store.

import {
  Epic,
  PlayStation,
  Steam,
  Xbox,
} from "@/components/icons";

export type Platform = "steam" | "xbox" | "epic" | "playstation";
export type GamePlatform = Platform | "other";

export type LinkedAccount = {
  platform: Platform;
  connected: boolean;
  handle?: string;
};

export type OwnedGame = {
  id: string;
  title: string;
  platform: GamePlatform;
  appid?: number;
};

export type Profile = {
  name: string;
  email: string;
};

export type Prefs = {
  emailUpdates: boolean;
  matureContent: boolean;
  autoSync: boolean;
};

export type MockState = {
  signedIn: boolean;
  profile: Profile;
  accounts: LinkedAccount[];
  games: OwnedGame[];
  prefs: Prefs;
};

// Presentation metadata for each platform (icon + brand-ish accent + label).
// Brand colors are used only on small logo tiles, as solid fills.
export const PLATFORMS: Record<
  Platform,
  { label: string; Icon: typeof Steam; tint: string; ring: string }
> = {
  steam: { label: "Steam", Icon: Steam, tint: "#1b2838", ring: "#334155" },
  xbox: { label: "Xbox", Icon: Xbox, tint: "#107C10", ring: "#107C10" },
  epic: { label: "Epic Games", Icon: Epic, tint: "#121212", ring: "#2b2b2b" },
  playstation: { label: "PlayStation", Icon: PlayStation, tint: "#0070D1", ring: "#0070D1" },
};

export const GAME_PLATFORM_LABEL: Record<GamePlatform, string> = {
  steam: "Steam",
  xbox: "Xbox",
  epic: "Epic",
  playstation: "PlayStation",
  other: "Other",
};

// A tiny catalog used by the "Add game" search/suggestions.
export const CATALOG: { title: string; appid?: number }[] = [
  { title: "Hades", appid: 1145360 },
  { title: "Hollow Knight", appid: 367520 },
  { title: "Celeste", appid: 504230 },
  { title: "Elden Ring", appid: 1245620 },
  { title: "Stardew Valley", appid: 413150 },
  { title: "Portal 2", appid: 620 },
  { title: "Baldur's Gate 3", appid: 1086940 },
  { title: "Slay the Spire", appid: 646570 },
  { title: "Disco Elysium", appid: 632470 },
  { title: "Cuphead", appid: 268910 },
  { title: "Dead Cells", appid: 588650 },
  { title: "The Witcher 3", appid: 292030 },
];

export const DEFAULT_STATE: MockState = {
  signedIn: false,
  profile: { name: "Alex Rivera", email: "alex@syr.edu" },
  accounts: [
    { platform: "steam", connected: true, handle: "alexr" },
    { platform: "xbox", connected: false },
    { platform: "epic", connected: false },
    { platform: "playstation", connected: false },
  ],
  games: [
    { id: "g1", title: "Half-Life 2", platform: "steam", appid: 220 },
    { id: "g2", title: "Hollow Knight", platform: "steam", appid: 367520 },
    { id: "g3", title: "Celeste", platform: "steam", appid: 504230 },
    { id: "g4", title: "Forza Horizon 5", platform: "xbox" },
  ],
  prefs: { emailUpdates: true, matureContent: false, autoSync: true },
};
