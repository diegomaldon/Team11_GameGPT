"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMock } from "@/lib/mock/store";
import { PLATFORMS, type Platform } from "@/lib/mock/data";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Field,
  Modal,
  PageHeader,
  TextInput,
  Toggle,
  cx,
} from "@/components/ui";
import { Check, LogOut } from "@/components/icons";

export default function SettingsPage() {
  const { state } = useMock();
  return (
    <>
      <PageHeader title="Settings" subtitle="Manage your profile, linked platforms, and preferences." />
      <div className="flex flex-col gap-5">
        <ProfileCard />
        <LinkedAccountsCard />
        <PreferencesCard />
        <DangerCard />
      </div>
      <p className="mt-6 text-center text-xs text-[var(--ink-faint)]">
        Signed in as {state.profile.email} · demo account
      </p>
    </>
  );
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-4">
        <h2 className="font-display text-base font-semibold">{title}</h2>
        {description && (
          <p className="mt-0.5 text-[13px] text-[var(--ink-soft)]">{description}</p>
        )}
      </div>
      {children}
    </Card>
  );
}

function ProfileCard() {
  const { state, updateProfile } = useMock();
  const [name, setName] = useState(state.profile.name);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = name.trim() !== state.profile.name;

  function save() {
    if (!dirty || !name.trim()) return;
    setSaving(true);
    window.setTimeout(() => {
      updateProfile({ name: name.trim() });
      setSaving(false);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    }, 500);
  }

  return (
    <SectionCard title="Profile">
      <div className="flex items-center gap-4">
        <Avatar name={state.profile.name} size={56} />
        <div>
          <p className="font-display text-lg font-semibold">{state.profile.name}</p>
          <p className="text-sm text-[var(--ink-faint)]">{state.profile.email}</p>
        </div>
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field label="Display name" htmlFor="name">
          <TextInput id="name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Email" htmlFor="email" hint="Managed by your sign-in provider">
          <TextInput id="email" value={state.profile.email} disabled />
        </Field>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button size="sm" onClick={save} loading={saving} disabled={!dirty}>
          Save changes
        </Button>
        {saved && (
          <span className="inline-flex items-center gap-1 text-[13px] font-medium text-emerald-700">
            <Check className="h-4 w-4" /> Saved
          </span>
        )}
      </div>
    </SectionCard>
  );
}

function LinkedAccountsCard() {
  const { state, unlinkAccount } = useMock();
  const [connecting, setConnecting] = useState<Platform | null>(null);

  return (
    <SectionCard
      title="Linked accounts"
      description="Connect a platform to import your owned games automatically."
    >
      <ul className="flex flex-col divide-y divide-[var(--border)]">
        {state.accounts.map((acc) => {
          const meta = PLATFORMS[acc.platform];
          const { Icon, label } = meta;
          return (
            <li key={acc.platform} className="flex items-center gap-3 py-3.5 first:pt-0 last:pb-0">
              <span
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white"
                style={{ backgroundColor: meta.tint }}
              >
                <Icon className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{label}</p>
                {acc.connected ? (
                  <p className="truncate text-xs text-[var(--ink-faint)]">
                    Connected{acc.handle ? ` · ${acc.handle}` : ""}
                  </p>
                ) : (
                  <p className="text-xs text-[var(--ink-faint)]">Not connected</p>
                )}
              </div>
              {acc.connected ? (
                <div className="flex items-center gap-2">
                  <Badge tone="success">
                    <Check className="h-3 w-3" /> Linked
                  </Badge>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => unlinkAccount(acc.platform)}
                  >
                    Disconnect
                  </Button>
                </div>
              ) : (
                <Button size="sm" onClick={() => setConnecting(acc.platform)}>
                  Connect
                </Button>
              )}
            </li>
          );
        })}
      </ul>

      <ConnectModal
        platform={connecting}
        onClose={() => setConnecting(null)}
      />
    </SectionCard>
  );
}

function ConnectModal({
  platform,
  onClose,
}: {
  platform: Platform | null;
  onClose: () => void;
}) {
  const { linkAccount } = useMock();
  const [handle, setHandle] = useState("");
  const [busy, setBusy] = useState(false);

  if (!platform) return null;
  const meta = PLATFORMS[platform];
  const isSteam = platform === "steam";
  const fieldLabel = isSteam ? "steamID64" : `${meta.label} username`;

  function connect() {
    setBusy(true);
    // Simulate the OAuth / lookup round-trip.
    window.setTimeout(() => {
      linkAccount(platform!, handle.trim() || "you");
      setBusy(false);
      setHandle("");
      onClose();
    }, 900);
  }

  return (
    <Modal
      open={!!platform}
      onClose={() => {
        setHandle("");
        onClose();
      }}
      title={`Connect ${meta.label}`}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" onClick={connect} loading={busy}>
            {busy ? "Connecting" : "Connect"}
          </Button>
        </>
      }
    >
      <div className="flex items-center gap-3 rounded-xl bg-neutral-50 p-3">
        <span
          className="flex h-10 w-10 items-center justify-center rounded-xl text-white"
          style={{ backgroundColor: meta.tint }}
        >
          <meta.Icon className="h-5 w-5" />
        </span>
        <p className="text-[13px] text-[var(--ink-soft)]">
          {isSteam
            ? "Paste a public steamID64 to import owned games."
            : `You'll be redirected to ${meta.label} to authorize access. (Demo — no real redirect.)`}
        </p>
      </div>
      <div className="mt-4">
        <Field label={fieldLabel} htmlFor="handle">
          <TextInput
            id="handle"
            autoFocus
            inputMode={isSteam ? "numeric" : "text"}
            placeholder={isSteam ? "76561197960287930" : "your-handle"}
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}

function PreferencesCard() {
  const { state, updatePrefs } = useMock();
  const rows: { key: keyof typeof state.prefs; label: string; desc: string }[] = [
    { key: "autoSync", label: "Auto-sync libraries", desc: "Refresh owned games from linked platforms daily." },
    { key: "emailUpdates", label: "Email updates", desc: "New features and occasional recommendations." },
    { key: "matureContent", label: "Show mature content", desc: "Include 18+ titles in recommendations." },
  ];
  return (
    <SectionCard title="Preferences">
      <ul className="flex flex-col divide-y divide-[var(--border)]">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center justify-between gap-4 py-3.5 first:pt-0 last:pb-0">
            <div>
              <p className="text-sm font-medium">{r.label}</p>
              <p className="text-xs text-[var(--ink-faint)]">{r.desc}</p>
            </div>
            <Toggle
              checked={state.prefs[r.key]}
              onChange={(v) => updatePrefs({ [r.key]: v })}
              label={r.label}
            />
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

function DangerCard() {
  const { signOut, resetAll } = useMock();
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);

  return (
    <Card className={cx("p-5 sm:p-6")}>
      <h2 className="font-display text-base font-semibold">Account</h2>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium">Sign out</p>
          <p className="text-xs text-[var(--ink-faint)]">End your session on this device.</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            signOut();
            router.replace("/signin");
          }}
        >
          <LogOut className="h-4 w-4" /> Sign out
        </Button>
      </div>

      <div className="mt-4 flex flex-col gap-3 border-t border-[var(--border)] pt-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium text-rose-600">Delete account</p>
          <p className="text-xs text-[var(--ink-faint)]">
            Permanently remove your data. This can&apos;t be undone.
          </p>
        </div>
        <Button variant="danger" size="sm" onClick={() => setConfirm(true)}>
          Delete account
        </Button>
      </div>

      <Modal
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Delete account?"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => {
                resetAll();
                signOut();
                router.replace("/signin");
              }}
            >
              Delete everything
            </Button>
          </>
        }
      >
        <p className="text-sm text-[var(--ink-soft)]">
          This removes your profile, linked accounts, and library. In this demo
          it just resets the mock data and signs you out.
        </p>
      </Modal>
    </Card>
  );
}
