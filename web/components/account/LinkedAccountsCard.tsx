"use client";

// Linked accounts on Settings: one row per platform with its connection state and when it
// last synced, plus Connect / Disconnect. REQ003 · TM11-52.
//
// State comes from platform_accounts (lib/account/useLinkedAccounts.ts), not the mock store,
// so it is right after a refresh and when nothing is linked. Steam and Xbox connect through
// their sign-in redirects; the callbacks land back here and this card finishes the link.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/session";
import { PLATFORMS, type Platform } from "@/lib/mock/data";
import { describeSteamResult } from "@/lib/auth/steam";
import { completeSteamLink } from "@/lib/auth/steamClient";
import { describeXboxResult } from "@/lib/auth/xboxMessages";
import { completeXboxLink } from "@/lib/auth/xboxClient";
import {
  disconnectPlatform,
  formatLastSynced,
  linkManualPlatform,
  markSynced,
  type LinkedAccount,
} from "@/lib/account/linkedAccounts";
import { accountsDb, useLinkedAccounts } from "@/lib/account/useLinkedAccounts";
import { useLibrarySync } from "@/lib/library/useLibrarySync";
import { SyncProgress } from "@/components/library/SyncProgress";
import { Badge, Button, Card, Field, Modal, TextInput, cx } from "@/components/ui";
import { Check, Spinner } from "@/components/icons";

type Banner = { tone: "success" | "info" | "error"; message: string } | null;

/** Kicks off the real Steam OpenID redirect. REQ010 · TM11-44. */
function startSteamLink() {
  // Full navigation, not a router push — the next stop is steamcommunity.com, off-site.
  window.location.assign("/api/steam/login?next=/settings");
}

/** Kicks off the real Microsoft / Xbox Live sign-in. REQ014 · TM11-53. */
function startXboxLink() {
  window.location.assign("/api/xbox/login?next=/settings");
}

export function LinkedAccountsCard() {
  const { user } = useAuth();
  const userId = user?.id ?? null;
  const { state, reload } = useLinkedAccounts(userId);
  const [banner, setBanner] = useState<Banner>(null);
  const [connecting, setConnecting] = useState<Platform | null>(null);
  const [disconnecting, setDisconnecting] = useState<LinkedAccount | null>(null);

  // TM11-49: the import runs in the background; this tracks its progress.
  const librarySync = useLibrarySync();
  const [lastSteamId, setLastSteamId] = useState<string | null>(null);
  const { start: startLibrarySync } = librarySync;
  const startSync = useCallback(
    (steamId: string) => {
      setLastSteamId(steamId);
      startLibrarySync(steamId);
    },
    [startLibrarySync],
  );

  useStampSyncTime(librarySync.job, userId, reload);
  useSteamCallbackResult(setBanner, reload, startSync);
  useXboxCallbackResult(setBanner, reload);

  const accounts = state.status === "ready" ? state.accounts : [];
  const noneLinked = state.status === "ready" && !accounts.some((a) => a.connected);

  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-4">
        <h2 className="font-display text-base font-semibold">Linked accounts</h2>
        <p className="mt-0.5 text-[13px] text-[var(--ink-soft)]">
          Connect a platform to import your owned games automatically.
        </p>
      </div>

      {banner && (
        <div
          role={banner.tone === "error" ? "alert" : "status"}
          className={cx(
            "mb-4 rounded-xl px-3 py-2.5 text-[13px]",
            banner.tone === "success" && "bg-emerald-50 text-emerald-800",
            banner.tone === "info" && "bg-neutral-100 text-[var(--ink-soft)]",
            banner.tone === "error" && "bg-rose-50 text-rose-700",
          )}
        >
          {banner.message}
        </div>
      )}

      {state.status === "loading" && (
        <p
          role="status"
          className="flex items-center gap-2 py-6 text-sm text-[var(--ink-faint)]"
        >
          <Spinner className="h-4 w-4" /> Loading linked accounts…
        </p>
      )}

      {state.status === "error" && (
        <div
          role="alert"
          className={cx(
            "flex flex-wrap items-center justify-between gap-3 rounded-xl border",
            "border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700",
          )}
        >
          <span>{state.message}</span>
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        </div>
      )}

      {state.status === "ready" && (
        <>
          {noneLinked && (
            <p
              className={cx(
                "mb-3 rounded-xl bg-neutral-50 px-3 py-2.5 text-[13px]",
                "text-[var(--ink-soft)]",
              )}
            >
              No platforms linked yet. Connect one to import the games you own.
            </p>
          )}
          <ul aria-label="Platforms" className="flex flex-col divide-y divide-[var(--border)]">
            {accounts.map((acc) => (
              <AccountRow
                key={acc.platform}
                account={acc}
                syncing={librarySync.running}
                onSync={() => acc.accountId && startSync(acc.accountId)}
                onConnect={() => {
                  setBanner(null);
                  if (acc.connectVia === "steam") {
                    startSteamLink();
                  } else if (acc.connectVia === "xbox") {
                    startXboxLink();
                  } else {
                    setConnecting(acc.platform);
                  }
                }}
                onDisconnect={() => setDisconnecting(acc)}
              />
            ))}
          </ul>
        </>
      )}

      <SyncProgress
        job={librarySync.job}
        error={librarySync.error}
        onRetry={lastSteamId ? () => startSync(lastSteamId) : undefined}
      />

      <ManualConnectModal
        platform={connecting}
        userId={userId}
        onClose={() => setConnecting(null)}
        onLinked={(platform) => {
          setConnecting(null);
          setBanner({ tone: "success", message: `${PLATFORMS[platform].label} connected.` });
          reload();
        }}
      />

      <DisconnectModal
        account={disconnecting}
        userId={userId}
        onClose={() => setDisconnecting(null)}
        onDone={(platform) => {
          setDisconnecting(null);
          setBanner({ tone: "success", message: `${PLATFORMS[platform].label} disconnected.` });
          reload();
        }}
      />
    </Card>
  );
}

function AccountRow({
  account,
  syncing,
  onSync,
  onConnect,
  onDisconnect,
}: {
  account: LinkedAccount;
  syncing: boolean;
  onSync: () => void;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  const meta = PLATFORMS[account.platform];
  const { Icon, label } = meta;
  const supported = account.connectVia !== null;
  return (
    <li
      aria-label={label}
      className="flex flex-wrap items-center gap-3 py-3.5 first:pt-0 last:pb-0"
    >
      <span
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white"
        style={{ backgroundColor: meta.tint }}
      >
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">{label}</p>
        {account.connected ? (
          <>
            <p className="truncate text-xs text-[var(--ink-faint)]">
              Connected{account.accountId ? ` · ${account.accountId}` : ""}
            </p>
            <p
              className="text-xs text-[var(--ink-faint)]"
              title={
                account.lastSyncedAt ? new Date(account.lastSyncedAt).toLocaleString() : undefined
              }
            >
              {formatLastSynced(account.lastSyncedAt)}
            </p>
          </>
        ) : (
          <p className="text-xs text-[var(--ink-faint)]">
            {supported ? "Not connected" : "Not supported yet"}
          </p>
        )}
      </div>
      {account.connected ? (
        <div className="flex items-center gap-2">
          <Badge tone="success">
            <Check className="h-3 w-3" /> Linked
          </Badge>
          {account.platform === "steam" && account.accountId && (
            <Button variant="secondary" size="sm" loading={syncing} onClick={onSync}>
              {syncing ? "Syncing" : "Sync now"}
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={onDisconnect}
            aria-label={`Disconnect ${label}`}
          >
            Disconnect
          </Button>
        </div>
      ) : (
        <Button
          size="sm"
          onClick={onConnect}
          disabled={!supported}
          aria-label={`Connect ${label}`}
        >
          Connect
        </Button>
      )}
    </li>
  );
}

/**
 * Stamps last_synced_at on the Steam row once an import succeeds, then reloads so the row
 * shows it. The backend import runs as the dev user and can't reach this user's row
 * (docs/steam-library.md → "Known gap"), so the page does it with the user's own session.
 */
function useStampSyncTime(
  job: ReturnType<typeof useLibrarySync>["job"],
  userId: string | null,
  reload: () => void,
) {
  const stamped = useRef<string | null>(null);
  useEffect(() => {
    if (!job || job.state !== "succeeded" || !userId || stamped.current === job.job_id) {
      return;
    }
    stamped.current = job.job_id;
    markSynced(accountsDb, userId, "steam").then(reload, () => {
      // The import itself worked; only the timestamp is missing. Not worth an error banner.
    });
  }, [job, userId, reload]);
}

/**
 * Reads the `?steam=` result /api/steam/callback redirects back with. On `verified` the
 * callback has sealed the steamID64 in an httpOnly cookie; this asks the server to write the
 * platform_accounts row (POST /api/steam/link), then starts a library import. Runs once per
 * outcome, then strips the params so a refresh does not replay it. TM11-44 · TM11-52.
 */
function useSteamCallbackResult(
  setBanner: (b: Banner) => void,
  reload: () => void,
  startSync: (steamId: string) => void,
) {
  const router = useRouter();
  const params = useSearchParams();
  const { status, session } = useAuth();
  const result = params.get("steam");
  const reason = params.get("reason");
  const handled = useRef(false);

  useEffect(() => {
    if (!result || handled.current || status === "loading") {
      return;
    }
    handled.current = true;
    setBanner(describeSteamResult(result, reason));

    if (result === "verified") {
      completeSteamLink(fetch, session?.access_token ?? null).then((outcome) => {
        if (outcome.status === "linked") {
          setBanner(describeSteamResult("linked"));
          reload();
          // The link is saved whether or not the import succeeds; progress and any
          // per-title failures show under the account list (TM11-49).
          startSync(outcome.steamId);
        } else {
          setBanner(describeSteamResult("error", outcome.reason));
        }
      });
    }

    router.replace("/settings");
  }, [result, reason, status, session, setBanner, reload, startSync, router]);
}

/**
 * Reads the `?xbox=` result /api/xbox/callback redirects back with and, on `verified`,
 * finishes the link through POST /api/xbox/link. REQ014 · TM11-53.
 */
function useXboxCallbackResult(setBanner: (b: Banner) => void, reload: () => void) {
  const router = useRouter();
  const params = useSearchParams();
  const { status, session } = useAuth();
  const result = params.get("xbox");
  const reason = params.get("reason");
  const handled = useRef(false);

  useEffect(() => {
    if (!result || handled.current || status === "loading") {
      return;
    }
    handled.current = true;

    if (result === "verified") {
      setBanner({ tone: "info", message: "Finishing your Xbox connection…" });
      completeXboxLink(fetch, session?.access_token ?? null).then((outcome) => {
        if (outcome.status === "linked") {
          setBanner(describeXboxResult("linked", null, outcome.gamertag));
          reload();
        } else {
          setBanner(describeXboxResult("error", outcome.reason));
        }
      });
    } else {
      setBanner(describeXboxResult(result, reason));
    }

    // Drop xbox/reason so a reload does not replay the outcome.
    router.replace("/settings");
  }, [result, reason, status, session, setBanner, reload, router]);
}

/** Connect for platforms with no sign-in flow (Epic): the user types their account name. */
function ManualConnectModal({
  platform,
  userId,
  onClose,
  onLinked,
}: {
  platform: Platform | null;
  userId: string | null;
  onClose: () => void;
  onLinked: (platform: Platform) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!platform) {
    return null;
  }
  const meta = PLATFORMS[platform];

  function close() {
    if (busy) {
      return;
    }
    setName("");
    setError(null);
    onClose();
  }

  async function connect() {
    if (!platform || !userId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await linkManualPlatform(accountsDb, userId, platform, name);
      setName("");
      onLinked(platform);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={close}
      title={`Connect ${meta.label}`}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" onClick={connect} loading={busy}>
            {busy ? "Connecting" : "Connect"}
          </Button>
        </>
      }
    >
      <p className="text-[13px] text-[var(--ink-soft)]">
        {meta.label} has no sign-in GameGPT can use yet, so enter your account name. It
        isn&apos;t verified, and games from {meta.label} are added by hand on the Library page.
      </p>
      <div className="mt-4">
        <Field
          label={`${meta.label} account name`}
          htmlFor="manual-account-name"
          error={error ?? undefined}
        >
          <TextInput
            id="manual-account-name"
            autoFocus
            autoComplete="off"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError(null);
            }}
          />
        </Field>
      </div>
    </Modal>
  );
}

/** Disconnect deletes the row and, by cascade, the games imported through it. Ask first. */
function DisconnectModal({
  account,
  userId,
  onClose,
  onDone,
}: {
  account: LinkedAccount | null;
  userId: string | null;
  onClose: () => void;
  onDone: (platform: Platform) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!account) {
    return null;
  }
  const { label } = PLATFORMS[account.platform];

  function close() {
    if (busy) {
      return;
    }
    setError(null);
    onClose();
  }

  async function confirm() {
    if (!account || !userId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await disconnectPlatform(accountsDb, userId, account.platform);
      onDone(account.platform);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={close}
      title={`Disconnect ${label}?`}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={confirm} loading={busy}>
            Disconnect
          </Button>
        </>
      }
    >
      <p className="text-sm text-[var(--ink-soft)]">
        Games imported through this {label} account will be removed from your library. You
        can connect again at any time.
      </p>
      {error && (
        <p role="alert" className="mt-3 rounded-xl bg-rose-50 px-3 py-2.5 text-sm text-rose-700">
          {error}
        </p>
      )}
    </Modal>
  );
}
