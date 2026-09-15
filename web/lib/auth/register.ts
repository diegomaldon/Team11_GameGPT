import { z } from 'zod';
import type { AuthError } from '@supabase/supabase-js';
import { supabase } from '../supabase';

/**
 * GameGPT · E2 Identity & Account Management
 * Email + password registration. REQ001.
 *
 * Three things in here are load-bearing and should survive refactors:
 *
 *  1. Nothing in this module logs, returns, or embeds the raw password. The only place the
 *     plaintext exists is the function argument and the request body. See `scrubError`.
 *  2. Duplicate email is detected two different ways because GoTrue behaves differently
 *     depending on whether email confirmation is enabled. See `REVEAL_DUPLICATE_EMAIL`.
 *  3. This module does NOT insert a profile row. That is a Postgres trigger's job
 *     (migration 20260914120000). Adding an insert here breaks AC4.
 */

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/**
 * bcrypt, which GoTrue uses, silently truncates at 72 bytes. Capping here means a user
 * whose 80-character passphrase gets cut can't end up locked out by the difference.
 */
const BCRYPT_MAX_BYTES = 72;

export const registerSchema = z
  .object({
    email: z
      .string()
      .trim()
      .toLowerCase()
      .min(1, 'Enter your email address.')
      .email('Enter a valid email address, like you@example.com.')
      .max(254, 'That email address is too long.'),

    password: z
      .string()
      .min(12, 'Use at least 12 characters.')
      .max(BCRYPT_MAX_BYTES, `Keep it to ${BCRYPT_MAX_BYTES} characters or fewer.`)
      .regex(/[a-z]/, 'Include a lowercase letter.')
      .regex(/[A-Z]/, 'Include an uppercase letter.')
      .regex(/[0-9]/, 'Include a number.'),

    confirmPassword: z.string().min(1, 'Re-enter your password.'),

    displayName: z
      .string()
      .trim()
      .max(40, 'Keep your display name under 40 characters.')
      .optional(),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ['confirmPassword'],
    message: "Passwords don't match.",
  });

export type RegisterInput = z.infer<typeof registerSchema>;

// ---------------------------------------------------------------------------
// Result shape
// ---------------------------------------------------------------------------

export type RegisterResult =
  /** Account created. `hasSession` is false when email confirmation is enabled. */
  | { status: 'created'; userId: string; hasSession: boolean }
  /** Address already registered. Only surfaced to the UI when REVEAL_DUPLICATE_EMAIL is true. */
  | { status: 'duplicate_email' }
  /** Server-side schema rejection. Keyed by field name so the form can map it. */
  | { status: 'invalid'; fieldErrors: Record<string, string[]> }
  /** GoTrue rate limit. Usually hit in local dev by resending confirmations. */
  | { status: 'rate_limited'; retryAfterSeconds: number | null }
  /** Anything else: network, 5xx, misconfiguration. */
  | { status: 'error'; message: string };

// ---------------------------------------------------------------------------
// Duplicate-email policy
// ---------------------------------------------------------------------------

/**
 * Whether to tell the visitor an email is already taken.
 *
 * `true`  — friendlier. Also a user-enumeration oracle: anyone can probe which addresses
 *           have GameGPT accounts. Fine locally, a finding in the E8 security review.
 * `false` — duplicate signups render the same neutral "check your email" state as a fresh
 *           one. This is what GoTrue itself does when confirmation is on, so with
 *           confirmation enabled we cannot reliably reveal it anyway.
 *
 * Default to the honest setting: reveal in dev, stay quiet everywhere else.
 *
 * Next has no import.meta.env.DEV; NODE_ENV is 'production' for `next build`/`next start`
 * and 'development' under `next dev`, which is the same distinction.
 */
export const REVEAL_DUPLICATE_EMAIL = process.env.NODE_ENV !== 'production';

// ---------------------------------------------------------------------------
// Logging safety
// ---------------------------------------------------------------------------

/**
 * Supabase AuthError objects are safe to log, but the temptation is to log the caught error
 * alongside the input that caused it. This returns the only shape allowed near a logger.
 * AC2 asserts the plaintext password never appears in any captured log argument.
 */
export function scrubError(error: AuthError | Error): Record<string, unknown> {
  const base: Record<string, unknown> = {
    name: error.name,
    message: error.message,
  };
  if ('status' in error) base.status = (error as AuthError).status;
  if ('code' in error) base.code = (error as AuthError).code;
  return base;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export async function registerWithEmail(input: RegisterInput): Promise<RegisterResult> {
  const parsed = registerSchema.safeParse(input);
  if (!parsed.success) {
    return {
      status: 'invalid',
      fieldErrors: parsed.error.flatten().fieldErrors as Record<string, string[]>,
    };
  }

  const { email, password, displayName } = parsed.data;

  try {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        // Consumed by handle_new_user() to seed user_profiles.display_name.
        data: displayName ? { display_name: displayName } : undefined,
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      // Case A — email confirmation OFF. GoTrue returns an explicit duplicate error.
      if (isDuplicateEmailError(error)) {
        return { status: 'duplicate_email' };
      }

      if (error.status === 429 || error.code === 'over_email_send_rate_limit') {
        return { status: 'rate_limited', retryAfterSeconds: parseRetryAfter(error) };
      }

      if (error.status === 422 || error.status === 400) {
        // Server-side validation we didn't catch client-side (leaked password check,
        // domain blocklist, minimum length configured higher in the dashboard).
        return { status: 'invalid', fieldErrors: { password: [error.message] } };
      }

      console.error('[auth] signUp failed', scrubError(error));
      return {
        status: 'error',
        message: "We couldn't create your account. Try again in a moment.",
      };
    }

    // Case B — email confirmation ON and the address already exists. GoTrue returns a
    // success shape with an obfuscated user and an empty identities array, on purpose,
    // so the response can't be used to enumerate accounts. Detect it, but only surface
    // it when policy allows.
    if (data.user && (data.user.identities?.length ?? 0) === 0) {
      return REVEAL_DUPLICATE_EMAIL
        ? { status: 'duplicate_email' }
        : { status: 'created', userId: data.user.id, hasSession: false };
    }

    if (!data.user) {
      console.error('[auth] signUp returned no user and no error');
      return {
        status: 'error',
        message: "We couldn't create your account. Try again in a moment.",
      };
    }

    return {
      status: 'created',
      userId: data.user.id,
      hasSession: data.session !== null,
    };
  } catch (thrown) {
    // Network failure, CORS, DNS. Never let the raw input near this log line.
    const error = thrown instanceof Error ? thrown : new Error('Unknown signup failure');
    console.error('[auth] signUp threw', scrubError(error));
    return {
      status: 'error',
      message: 'Check your connection and try again.',
    };
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// KNOWN: see docs/security-notes.md
function isDuplicateEmailError(error: AuthError): boolean {
  if (error.code === 'user_already_exists' || error.code === 'email_exists') return true;
  // Older GoTrue builds send no code, only a 422 with this phrasing. Matched loosely
  // on purpose: a false negative here degrades to a generic error, which is acceptable.
  return error.status === 422 && /already\s+registered|already\s+exists/i.test(error.message);
}

function parseRetryAfter(error: AuthError): number | null {
  const match = /(\d+)\s*second/i.exec(error.message);
  return match ? Number(match[1]) : null;
}
