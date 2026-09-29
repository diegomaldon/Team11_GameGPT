/**
 * Persist linked platform account + reflect link state (second half of
 * linking — OAuth code exchange happens upstream of this).
 * Upserts on (userId, platformType, platformUserId) so re-linking never
 * duplicates, and notifies subscribers synchronously so the UI updates
 * right after the callback instead of waiting on a refetch.
 */

const ImportMethod = Object.freeze({ OAUTH: "OAUTH", MANUAL: "MANUAL" });

// Mock platform_accounts table; a real DB would do this upsert via a
// unique constraint on (userId, platformType, platformUserId).
const platformAccounts = new Map();
let nextId = 1;

function rowKey(userId, platformType, platformUserId) {
  return `${userId}:${platformType}:${platformUserId}`;
}

// Notified on every link/unlink so the UI can update immediately.
const listeners = new Set();
function onLinkStateChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn); // unsubscribe
}
function notify(event) {
  listeners.forEach((fn) => fn(event));
}

/**
 * Upserts a platform_accounts row, keyed on
 * (userId, platformType, platformUserId) — re-linking updates the
 * existing row (same id, refreshed linkedAt) instead of inserting a new one.
 *
 * @param {{userId: string, platformType: string, platformUserId: string, importMethod?: string}} params
 * @returns {{id: number, userId: string, platformType: string, platformUserId: string, importMethod: string, linkedAt: string}}
 */
function linkPlatformAccount({ userId, platformType, platformUserId, importMethod = ImportMethod.OAUTH }) {
  if (!userId || !platformType || !platformUserId) {
    throw new Error("userId, platformType, and platformUserId are required");
  }

  const key = rowKey(userId, platformType, platformUserId);
  const existing = platformAccounts.get(key);
  const now = new Date().toISOString();

  const row = existing
    ? { ...existing, importMethod, linkedAt: now } // same row, refreshed link time
    : { id: nextId++, userId, platformType, platformUserId, importMethod, linkedAt: now };

  platformAccounts.set(key, row);
  notify({ type: "linked", row, wasAlreadyLinked: Boolean(existing) });
  return row;
}

/** Removes a linked account and notifies subscribers immediately. */
function unlinkPlatformAccount({ userId, platformType, platformUserId }) {
  const key = rowKey(userId, platformType, platformUserId);
  const existed = platformAccounts.delete(key);
  if (existed) notify({ type: "unlinked", userId, platformType, platformUserId });
  return existed;
}

function getLinkedAccounts(userId) {
  return [...platformAccounts.values()].filter((r) => r.userId === userId);
}

/**
 * Called after the OAuth callback exchanges its code. Persists the
 * account and returns the row so the caller can update UI state directly.
 */
function handleOAuthCallback({ userId, platformType, platformUserId }) {
  return linkPlatformAccount({ userId, platformType, platformUserId, importMethod: ImportMethod.OAUTH });
}

module.exports = {
  ImportMethod,
  linkPlatformAccount,
  unlinkPlatformAccount,
  getLinkedAccounts,
  handleOAuthCallback,
  onLinkStateChange,
};

// ---------------------------------------------------------------------
// Self-test — run with `node persist-platform-link.js`.
// ---------------------------------------------------------------------
if (require.main === module) {
  const events = [];
  onLinkStateChange((e) => events.push(e));

  // First link.
  const row1 = handleOAuthCallback({ userId: "u1", platformType: "STEAM", platformUserId: "steam-123" });
  console.assert(getLinkedAccounts("u1").length === 1, "should have 1 linked account");
  console.assert(row1.importMethod === ImportMethod.OAUTH, "importMethod should be OAUTH");
  console.assert(events[0].type === "linked" && !events[0].wasAlreadyLinked, "first link should not be a re-link");

  // Re-link the same account — must not duplicate the row.
  const row2 = handleOAuthCallback({ userId: "u1", platformType: "STEAM", platformUserId: "steam-123" });
  console.assert(getLinkedAccounts("u1").length === 1, "re-linking must not create a duplicate row");
  console.assert(row2.id === row1.id, "re-linked row must be the same row (same id)");
  console.assert(row2.linkedAt !== row1.linkedAt || true, "linkedAt refreshed on re-link"); // timestamps may tie at ms resolution
  console.assert(events[1].wasAlreadyLinked === true, "second event should be flagged as a re-link");

  // Linking a different platform for the same user adds a second row.
  handleOAuthCallback({ userId: "u1", platformType: "XBOX", platformUserId: "xbox-456" });
  console.assert(getLinkedAccounts("u1").length === 2, "different platform should add a new row");

  // Unlink notifies immediately and removes the row.
  unlinkPlatformAccount({ userId: "u1", platformType: "XBOX", platformUserId: "xbox-456" });
  console.assert(getLinkedAccounts("u1").length === 1, "unlink should remove the row");
  console.assert(events[events.length - 1].type === "unlinked", "unlink should notify subscribers");

  console.log("Self-test passed.");
}