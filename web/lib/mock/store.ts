"use client";

// A minimal client-side store for the dummy UI. State lives in React context
// and is mirrored to localStorage so it survives navigation and reloads.
// This stands in for a real backend/auth — nothing here hits the network.

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  DEFAULT_STATE,
  type GamePlatform,
  type MockState,
  type Platform,
  type Prefs,
  type Profile,
} from "./data";

const KEY = "gamegpt.mock.v1";

type Store = {
  state: MockState;
  hydrated: boolean;
  signIn: (email?: string) => void;
  signOut: () => void;
  updateProfile: (patch: Partial<Profile>) => void;
  linkAccount: (platform: Platform, handle: string) => void;
  unlinkAccount: (platform: Platform) => void;
  addGame: (game: { title: string; platform: GamePlatform; appid?: number }) => void;
  removeGame: (id: string) => void;
  updatePrefs: (patch: Partial<Prefs>) => void;
  resetAll: () => void;
};

const Ctx = createContext<Store | null>(null);

function load(): MockState | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as MockState) : null;
  } catch {
    return null;
  }
}

export function MockProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<MockState>(DEFAULT_STATE);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from localStorage after mount (avoids SSR/client mismatch).
  useEffect(() => {
    const saved = load();
    if (saved) setState({ ...DEFAULT_STATE, ...saved });
    setHydrated(true);
  }, []);

  // Persist on every change (once hydrated).
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch {
      /* ignore quota / private-mode errors in the mock */
    }
  }, [state, hydrated]);

  const uid = useCallback(
    () => `g${Math.random().toString(36).slice(2, 9)}`,
    [],
  );

  const store = useMemo<Store>(
    () => ({
      state,
      hydrated,
      signIn: (email) =>
        setState((s) => ({
          ...s,
          signedIn: true,
          profile: email ? { ...s.profile, email } : s.profile,
        })),
      signOut: () => setState((s) => ({ ...s, signedIn: false })),
      updateProfile: (patch) =>
        setState((s) => ({ ...s, profile: { ...s.profile, ...patch } })),
      linkAccount: (platform, handle) =>
        setState((s) => ({
          ...s,
          accounts: s.accounts.map((a) =>
            a.platform === platform ? { ...a, connected: true, handle } : a,
          ),
        })),
      unlinkAccount: (platform) =>
        setState((s) => ({
          ...s,
          accounts: s.accounts.map((a) =>
            a.platform === platform
              ? { platform, connected: false }
              : a,
          ),
        })),
      addGame: (game) =>
        setState((s) => ({
          ...s,
          games: [{ id: uid(), ...game }, ...s.games],
        })),
      removeGame: (id) =>
        setState((s) => ({ ...s, games: s.games.filter((g) => g.id !== id) })),
      updatePrefs: (patch) =>
        setState((s) => ({ ...s, prefs: { ...s.prefs, ...patch } })),
      resetAll: () => setState({ ...DEFAULT_STATE, signedIn: true }),
    }),
    [state, hydrated, uid],
  );

  return createElement(Ctx.Provider, { value: store }, children);
}

export function useMock(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useMock must be used within <MockProvider>");
  return ctx;
}
