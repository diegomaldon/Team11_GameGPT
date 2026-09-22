// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

/**
 * TM11-27 — session persistence, silent refresh and sign-out.
 * Grouped by acceptance criterion so the output reads as a checklist.
 */

const getSession = vi.fn();
const signOut = vi.fn();
const onAuthStateChange = vi.fn();

vi.mock("../supabase", () => ({
  supabase: { auth: { getSession, signOut, onAuthStateChange } },
}));

const { AuthProvider, useAuth } = await import("./session");

/** Hands back the listener the provider registered, so a test can fire events at it. */
let emit: (event: string, session: unknown) => void = () => {};

function session(accessToken: string, email = "diego@example.com") {
  return { access_token: accessToken, user: { id: "u1", email } };
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

beforeEach(() => {
  getSession.mockReset().mockResolvedValue({ data: { session: null }, error: null });
  signOut.mockReset().mockResolvedValue({ error: null });
  onAuthStateChange.mockReset().mockImplementation((cb) => {
    emit = cb;
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
describe("AC1 — the session survives a reload and a browser restart", () => {
  it("reads the stored session back and reports the user", async () => {
    getSession.mockResolvedValue({ data: { session: session("stored") }, error: null });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.user?.email).toBe("diego@example.com");
  });

  it("reports anonymous when nothing was stored", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    expect(result.current.user).toBeNull();
  });

  it("starts in loading, so the gate never guesses before the read finishes", () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.status).toBe("loading");
  });

  it("falls back to anonymous rather than hanging when the stored session is unreadable", async () => {
    getSession.mockResolvedValue({
      data: { session: null },
      error: { name: "AuthApiError", message: "refresh_token_not_found" },
    });

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("anonymous"));
  });
});

// ---------------------------------------------------------------------------
describe("AC2 — expired tokens refresh silently", () => {
  it("takes the new session on TOKEN_REFRESHED without dropping the user", async () => {
    getSession.mockResolvedValue({ data: { session: session("old") }, error: null });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));

    act(() => emit("TOKEN_REFRESHED", session("fresh")));

    await waitFor(() =>
      expect(result.current.session?.access_token).toBe("fresh"),
    );
    // The point of "silently": no trip through anonymous on the way.
    expect(result.current.status).toBe("authenticated");
  });

  it("picks up a sign-in that happened elsewhere, such as another tab", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("anonymous"));

    act(() => emit("SIGNED_IN", session("fresh")));

    await waitFor(() => expect(result.current.status).toBe("authenticated"));
  });
});

// ---------------------------------------------------------------------------
describe("AC4 — sign-out clears client state and revokes the session", () => {
  it("revokes globally, not just in this browser", async () => {
    getSession.mockResolvedValue({ data: { session: session("live") }, error: null });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));

    await act(async () => {
      await result.current.signOut();
    });

    expect(signOut).toHaveBeenCalledWith({ scope: "global" });
    expect(result.current.status).toBe("anonymous");
    expect(result.current.user).toBeNull();
  });

  it("still clears locally when the revoke call fails", async () => {
    getSession.mockResolvedValue({ data: { session: session("live") }, error: null });
    signOut.mockResolvedValue({ error: { name: "AuthRetryableFetchError", message: "offline" } });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));

    await act(async () => {
      await result.current.signOut();
    });

    // Leaving someone "signed in" because the network was down is the wrong failure mode.
    expect(result.current.status).toBe("anonymous");
  });
});

// ---------------------------------------------------------------------------
describe("wiring", () => {
  it("unsubscribes the listener on unmount", async () => {
    const unsubscribe = vi.fn();
    onAuthStateChange.mockImplementation((cb) => {
      emit = cb;
      return { data: { subscription: { unsubscribe } } };
    });

    const { unmount } = renderHook(() => useAuth(), { wrapper });
    unmount();

    expect(unsubscribe).toHaveBeenCalled();
  });

  it("refuses to be used outside the provider", () => {
    expect(() => renderHook(() => useAuth())).toThrow(/within <AuthProvider>/);
  });
});
