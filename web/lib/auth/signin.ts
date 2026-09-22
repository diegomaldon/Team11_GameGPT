import { z } from "zod";
import type { AuthError } from "@supabase/supabase-js";
import { supabase } from "../supabase";
import { scrubError } from "./register";

/**
 * GameGPT · E2 Identity & Account Management
 * Email + password sign-in. REQ001.
 *
 * The counterpart to register.ts. It exists here rather than in a later story because the
 * auth gate needs some way to produce a real session — the mock sign-in it replaced set
 * local state only, which the gate correctly refused, leaving the app looping between
 * /signin and /.
 *
 * Same two rules as registration: the plaintext password never reaches a log (everything
 * goes through scrubError), and failures do not tell an attacker which half was wrong.
 */

export const signInSchema = z.object({
  email: z
    .string()
    .trim()
    .toLowerCase()
    .min(1, "Enter your email address.")
    .email("Enter a valid email address, like you@example.com."),
  // No complexity rules on the way in. They belong at registration; applying them here
  // would reject a legitimate older password and tell the visitor its shape besides.
  password: z.string().min(1, "Enter your password."),
});

export type SignInInput = z.infer<typeof signInSchema>;

export type SignInResult =
  | { status: "signed_in"; userId: string }
  /** Wrong password, unknown address, or a deleted account. Deliberately one case. */
  | { status: "invalid_credentials" }
  /** Account exists but the confirmation link has not been followed yet. */
  | { status: "email_not_confirmed" }
  | { status: "invalid"; fieldErrors: Record<string, string[]> }
  | { status: "rate_limited"; retryAfterSeconds: number | null }
  | { status: "error"; message: string };

export async function signInWithPassword(input: SignInInput): Promise<SignInResult> {
  const parsed = signInSchema.safeParse(input);
  if (!parsed.success) {
    return {
      status: "invalid",
      fieldErrors: parsed.error.flatten().fieldErrors as Record<string, string[]>,
    };
  }

  const { email, password } = parsed.data;

  try {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      // Distinguished from invalid_credentials on purpose: the account is confirmed to
      // exist either way (GoTrue only returns this code for a real unconfirmed user), so
      // saying so leaks nothing further, and "check your inbox" is the only useful advice.
      if (error.code === "email_not_confirmed") {
        return { status: "email_not_confirmed" };
      }

      if (error.status === 429 || error.code === "over_request_rate_limit") {
        return { status: "rate_limited", retryAfterSeconds: parseRetryAfter(error) };
      }

      // 400 with invalid_credentials covers wrong password AND unknown email. GoTrue
      // collapses them so the endpoint cannot be used to enumerate accounts; keep it
      // collapsed here rather than trying to be more helpful.
      if (error.status === 400 || error.code === "invalid_credentials") {
        return { status: "invalid_credentials" };
      }

      console.error("[auth] signInWithPassword failed", scrubError(error));
      return { status: "error", message: "We couldn't sign you in. Try again in a moment." };
    }

    if (!data.session || !data.user) {
      console.error("[auth] signInWithPassword returned no session and no error");
      return { status: "error", message: "We couldn't sign you in. Try again in a moment." };
    }

    // No navigation here. onAuthStateChange in lib/auth/session.tsx picks the session up
    // and the caller decides where to go, so this stays usable from anywhere.
    return { status: "signed_in", userId: data.user.id };
  } catch (thrown) {
    const error = thrown instanceof Error ? thrown : new Error("Unknown sign-in failure");
    console.error("[auth] signInWithPassword threw", scrubError(error));
    return { status: "error", message: "Check your connection and try again." };
  }
}

function parseRetryAfter(error: AuthError): number | null {
  const match = /(\d+)\s*second/i.exec(error.message);
  return match ? Number(match[1]) : null;
}
