import { supabase } from "../supabase";
import type { RevokeOutcome } from "./revoke";

/**
 * GameGPT · E2 Identity & Account Management
 * Account deletion, client side. REQ005.
 *
 * Thin on purpose: the real work is in /api/account/delete, which revokes
 * platform tokens and calls the delete_my_account() function. This module
 * exists so the settings page never has to think about tokens or fetch
 * plumbing.
 */

/** Typed exactly as the user must type it. Case-sensitive, see below. */
export const DELETE_CONFIRMATION = "DELETE";

export type DeleteResult =
  | { status: "deleted"; revocations: RevokeOutcome[] }
  /** Session gone or never existed. Nothing was deleted. */
  | { status: "unauthenticated" }
  | { status: "error"; message: string };

/**
 * Whether the typed confirmation matches. Trimmed, because a trailing space
 * from a paste is not a reason to refuse someone; case-sensitive, because
 * having to produce capitals is most of what makes the gesture deliberate.
 */
export function confirmationMatches(typed: string): boolean {
  return typed.trim() === DELETE_CONFIRMATION;
}

export async function deleteMyAccount(): Promise<DeleteResult> {
  const { data, error } = await supabase.auth.getSession();

  if (error || !data.session) {
    return { status: "unauthenticated" };
  }

  try {
    const response = await fetch("/api/account/delete", {
      method: "POST",
      headers: { Authorization: `Bearer ${data.session.access_token}` },
    });

    if (response.status === 401) return { status: "unauthenticated" };

    const body = (await response.json().catch(() => null)) as
      | { deleted?: boolean; revocations?: RevokeOutcome[]; error?: string }
      | null;

    if (!response.ok || !body?.deleted) {
      return {
        status: "error",
        message: body?.error ?? "We couldn't delete your account. Try again.",
      };
    }

    return { status: "deleted", revocations: body.revocations ?? [] };
  } catch {
    // Ambiguous by nature: the request may have reached the server and
    // succeeded before the connection dropped. Say so rather than claiming
    // nothing happened, so the user reloads and checks instead of retrying
    // blind.
    return {
      status: "error",
      message:
        "Lost connection before we could confirm. Reload and check whether your account is gone before trying again.",
    };
  }
}
