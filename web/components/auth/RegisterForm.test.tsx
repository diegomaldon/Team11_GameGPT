// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
// Registers toHaveFocus / toHaveAttribute. Imported here rather than in a global setup
// file so the node-environment tests in lib/auth are not dragged through DOM matchers.
import '@testing-library/jest-dom/vitest';

/**
 * GameGPT · E2 · RegisterForm accessibility tests.
 *
 * These cover the two acceptance criteria that register.test.ts cannot reach, because that
 * file tests lib/auth/register.ts — the logic module — and never renders the form:
 *
 *   AC1 · "focus moves to the first invalid field", and the aria-describedby /
 *         aria-invalid wiring between an input and its error message.
 *   AC2 · the password inputs are type="password" with autoComplete="new-password".
 *
 * Written as tests rather than captured as screenshots on purpose: a screenshot proves the
 * form was correct on the day someone photographed it, and these re-run on every PR. In
 * particular, deleting `shouldFocusError` would leave all 20 of register.test.ts's
 * assertions green — the first test below is the one that would catch it.
 */

const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
}));

// Same seam register.test.ts uses. Nothing here touches the network.
const signUp = vi.fn();
vi.mock('../../lib/supabase', () => ({ supabase: { auth: { signUp } } }));

const { RegisterForm } = await import('./RegisterForm');

const VALID_EMAIL = 'diego@example.com';

beforeEach(() => {
  signUp.mockReset();
  replace.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
describe('AC1 — focus management', () => {
  it('moves focus to the first invalid field on submit', async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    // Email is deliberately valid so the first error is further down the form. The email
    // input carries autoFocus, so asserting on it would pass even with focus management
    // removed entirely.
    await user.type(screen.getByLabelText('Email'), VALID_EMAIL);
    await user.type(screen.getByLabelText('Password'), 'short');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByLabelText('Password')).toHaveFocus();
    });

    expect(signUp).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
describe('AC1 — errors are announced and linked to their input', () => {
  it('sets aria-invalid and points aria-describedby at the error message', async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    await user.type(screen.getByLabelText('Email'), 'diego@');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    const email = await screen.findByLabelText('Email');

    await waitFor(() => {
      expect(email).toHaveAttribute('aria-invalid', 'true');
    });

    const describedBy = email.getAttribute('aria-describedby');
    expect(describedBy).toBe('email-error');

    // The referenced element must actually exist, carry the message, and be announced.
    const error = document.getElementById(describedBy!);
    expect(error).not.toBeNull();
    expect(error).toHaveAttribute('role', 'alert');
    expect(error!.textContent).toMatch(/you@example\.com/);
  });

  it('leaves aria-describedby pointing at the hint while a field is valid', () => {
    render(<RegisterForm />);

    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('aria-invalid', 'false');
    expect(password).toHaveAttribute('aria-describedby', 'password-hint');
    expect(document.getElementById('password-hint')).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
describe('AC2 — credential inputs are typed for password managers', () => {
  it('renders both password fields as type=password with new-password autocomplete', () => {
    render(<RegisterForm />);

    for (const label of ['Password', 'Confirm password']) {
      const input = screen.getByLabelText(label);
      expect(input).toHaveAttribute('type', 'password');
      expect(input).toHaveAttribute('autocomplete', 'new-password');
    }
  });

  it('never renders the password as a value attribute in the DOM', async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    const secret = 'CorrectHorse9Battery';
    await user.type(screen.getByLabelText('Password'), secret);

    // The value lives in the DOM property, not in serialised markup that could end up in
    // an error report, a session replay, or a screenshot.
    expect(document.body.innerHTML).not.toContain(secret);
  });
});
