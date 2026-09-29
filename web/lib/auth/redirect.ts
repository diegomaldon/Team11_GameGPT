/**
 * GameGPT · E2 Identity & Account Management
 * Return-to-intended-page handling for the auth gate. REQ001 / REQ002.
 *
 * The guard puts where you were trying to go into `?next=`, and the sign-in page sends you
 * back there afterwards. That parameter is attacker-controlled: anyone can mail out
 * /signin?next=https://evil.example and the app would bounce a freshly authenticated user
 * straight off-site. `safeNext` is the only thing standing between us and that, so every
 * read of the parameter has to go through it.
 */

/** Where we land when `next` is missing, unusable, or points off-site. */
export const DEFAULT_AFTER_SIGN_IN = "/";

/** Pages that exist to get you signed in. Bouncing back to one is a loop, not a return. */
const AUTH_ROUTES = ["/signin", "/register", "/auth/callback"];

/**
 * Narrows an untrusted `next` value to a same-origin path we are willing to navigate to.
 * Returns DEFAULT_AFTER_SIGN_IN for anything else.
 */
export function safeNext(raw: string | null | undefined): string {
  if (!raw) return DEFAULT_AFTER_SIGN_IN;

  // Must be a path, not a URL. This rejects "https://evil.example" and "mailto:..." in
  // one go, because an absolute URL of any scheme fails the leading-slash test.
  if (!raw.startsWith("/")) return DEFAULT_AFTER_SIGN_IN;

  // "//evil.example" is protocol-relative: the browser reads it as a full URL and leaves
  // the site. It passes the test above, so it needs its own. Same for the backslash
  // variant, which some browsers normalise to a forward slash.
  if (raw.startsWith("//") || raw.startsWith("/\\")) return DEFAULT_AFTER_SIGN_IN;

  // A newline or tab inside a Location value can split the header on some stacks. Cheap
  // to reject outright; nothing legitimate has one.
  if (/[\u0000-\u001f\u007f]/.test(raw)) return DEFAULT_AFTER_SIGN_IN;

  const path = raw.split(/[?#]/, 1)[0];
  if (AUTH_ROUTES.some((route) => path === route || path.startsWith(`${route}/`))) {
    return DEFAULT_AFTER_SIGN_IN;
  }

  return raw;
}

/**
 * Builds the sign-in URL for a visitor who was trying to reach `intended`.
 *
 * Omits `next` when the destination is the default, so the common case gives a clean
 * /signin rather than /signin?next=%2F.
 */
export function signInUrlFor(intended: string): string {
  const target = safeNext(intended);
  if (target === DEFAULT_AFTER_SIGN_IN) return "/signin";
  return `/signin?next=${encodeURIComponent(target)}`;
}
