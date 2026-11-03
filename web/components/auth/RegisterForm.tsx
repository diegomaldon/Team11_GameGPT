'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  registerSchema,
  registerWithEmail,
  type RegisterInput,
} from '../../lib/auth/register';

/**
 * GameGPT · E2 · Email and password registration. REQ001.
 *
 * Styling is Tailwind utility classes on the TM11-142 theme tokens (app/globals.css);
 * nothing here depends on the styling layer.
 *
 * AC1 note: react-hook-form's `shouldFocusError` defaults to true, which is what moves
 * focus to the first invalid input. Don't turn it off.
 *
 * Routing note: the original draft used react-router-dom. This app is Next App Router, so
 * navigation is `useRouter` from next/navigation and links are next/link. Targets are the
 * pages that actually exist — `/signin`, and `/` for the authenticated app home — rather
 * than the `/sign-in` and `/dashboard` the draft assumed.
 */

// Matches TextInput in components/ui.tsx. Plain inputs here because react-hook-form's
// register() hands each one its own ref and handlers.
const INPUT_CLASS =
  'h-12 w-full rounded-full border border-[var(--border-input)] bg-[var(--bg)] px-5 text-[15px] text-[var(--ink)] outline-none transition-colors focus:border-[var(--accent)] aria-[invalid=true]:border-rose-300';

type FormState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'confirm_email'; email: string }
  | { kind: 'failed'; message: string };

export function RegisterForm() {
  const router = useRouter();
  const [state, setState] = useState<FormState>({ kind: 'idle' });

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    mode: 'onBlur',
    defaultValues: { email: '', password: '', confirmPassword: '', displayName: '' },
  });

  async function onSubmit(values: RegisterInput) {
    setState({ kind: 'submitting' });
    const result = await registerWithEmail(values);

    switch (result.status) {
      case 'created':
        if (result.hasSession) {
          router.replace('/');
        } else {
          // Email confirmation is on. There is no session yet, so redirecting to a
          // protected route would bounce straight back to sign-in.
          setState({ kind: 'confirm_email', email: values.email });
        }
        return;

      case 'duplicate_email':
        setError('email', {
          type: 'server',
          message: 'That email is already registered.',
        });
        setState({ kind: 'idle' });
        return;

      case 'invalid':
        for (const [field, messages] of Object.entries(result.fieldErrors)) {
          if (messages?.[0]) {
            setError(field as keyof RegisterInput, { type: 'server', message: messages[0] });
          }
        }
        setState({ kind: 'idle' });
        return;

      case 'rate_limited':
        setState({
          kind: 'failed',
          message: result.retryAfterSeconds
            ? `Too many attempts. Try again in ${result.retryAfterSeconds} seconds.`
            : 'Too many attempts. Try again in a minute.',
        });
        return;

      case 'error':
        setState({ kind: 'failed', message: result.message });
        return;
    }
  }

  if (state.kind === 'confirm_email') {
    return (
      <div className="space-y-3" role="status">
        <h1 className="font-display text-[40px] leading-[1.05]">Confirm your email</h1>
        <p className="text-base leading-relaxed text-[var(--ink-faint)]">
          We sent a confirmation link to {state.email}. Open it to finish setting up your
          account.
        </p>
        <p className="text-sm text-[var(--ink-faint)]">
          Nothing arrived after a few minutes? Check your spam folder, then{' '}
          <Link href="/register" className="font-medium text-[var(--heading)] underline">
            try again
          </Link>
          .
        </p>
      </div>
    );
  }

  const busy = isSubmitting || state.kind === 'submitting';

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
      <div className="space-y-2.5">
        <h1 className="font-display text-[44px] leading-[1.05]">Create your account</h1>
        <p className="text-base leading-relaxed text-[var(--ink-faint)]">
          Connect your game libraries next, so we never recommend something you already own.
        </p>
      </div>

      {state.kind === 'failed' && (
        <p role="alert" className="rounded-2xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          {state.message}
        </p>
      )}

      <Field
        id="email"
        label="Email"
        error={errors.email?.message}
        input={
          <input
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? 'email-error' : undefined}
            className={INPUT_CLASS}
            {...register('email')}
          />
        }
      />

      <Field
        id="displayName"
        label="Display name"
        hint="Optional. Shown on your recommendations."
        error={errors.displayName?.message}
        input={
          <input
            id="displayName"
            type="text"
            autoComplete="nickname"
            aria-invalid={Boolean(errors.displayName)}
            aria-describedby={errors.displayName ? 'displayName-error' : 'displayName-hint'}
            className={INPUT_CLASS}
            {...register('displayName')}
          />
        }
      />

      <Field
        id="password"
        label="Password"
        hint="At least 12 characters, with an uppercase letter and a number."
        error={errors.password?.message}
        input={
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            aria-invalid={Boolean(errors.password)}
            aria-describedby={errors.password ? 'password-error' : 'password-hint'}
            className={INPUT_CLASS}
            {...register('password')}
          />
        }
      />

      <Field
        id="confirmPassword"
        label="Confirm password"
        error={errors.confirmPassword?.message}
        input={
          <input
            id="confirmPassword"
            type="password"
            autoComplete="new-password"
            aria-invalid={Boolean(errors.confirmPassword)}
            aria-describedby={errors.confirmPassword ? 'confirmPassword-error' : undefined}
            className={INPUT_CLASS}
            {...register('confirmPassword')}
          />
        }
      />

      <button
        type="submit"
        disabled={busy}
        className="h-12 w-full rounded-full bg-[var(--accent)] px-6 text-[15px] font-semibold text-[var(--on-accent)] transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-60"
      >
        {busy ? 'Creating your account' : 'Create account'}
      </button>

      <p className="text-sm text-[var(--ink-faint)]">
        Already have an account?{' '}
        <Link href="/signin" className="font-medium text-[var(--heading)] underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  input,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  input: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-[13px] font-medium text-[var(--label)]">
        {label}
      </label>
      {input}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-[var(--ink-faint)]">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
