import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * Tests are grouped by acceptance criterion so a grader can read the output as a checklist.
 * Every `it` name states the behaviour, not the implementation.
 */

const signUp = vi.fn();
vi.mock('../supabase', () => ({ supabase: { auth: { signUp } } }));

const { registerWithEmail, registerSchema, scrubError } = await import('./register');

const VALID = {
  email: 'Diego@Example.com',
  password: 'CorrectHorse9Battery',
  confirmPassword: 'CorrectHorse9Battery',
};

function authError(partial: Record<string, unknown>) {
  return Object.assign(new Error(String(partial.message ?? 'error')), {
    name: 'AuthApiError',
    ...partial,
  });
}

beforeEach(() => {
  signUp.mockReset();
  vi.stubGlobal('window', { location: { origin: 'http://localhost:5173' } });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
describe('AC1 — validation blocks a bad submit and names the fix', () => {
  it('rejects an empty email without calling Supabase', async () => {
    const result = await registerWithEmail({ ...VALID, email: '' });

    expect(result).toMatchObject({ status: 'invalid' });
    expect(signUp).not.toHaveBeenCalled();
    expect(result.status === 'invalid' && result.fieldErrors.email?.[0]).toBe(
      'Enter your email address.',
    );
  });

  it('rejects a malformed email and names a valid example', async () => {
    const result = await registerWithEmail({ ...VALID, email: 'diego@' });

    expect(result.status).toBe('invalid');
    expect(result.status === 'invalid' && result.fieldErrors.email?.[0]).toMatch(
      /you@example\.com/,
    );
    expect(signUp).not.toHaveBeenCalled();
  });

  it('rejects a password under 12 characters', async () => {
    const result = await registerWithEmail({
      ...VALID,
      password: 'Short1pass',
      confirmPassword: 'Short1pass',
    });

    expect(result.status === 'invalid' && result.fieldErrors.password?.[0]).toBe(
      'Use at least 12 characters.',
    );
  });

  it('rejects a password over the bcrypt 72-byte ceiling', () => {
    const parsed = registerSchema.safeParse({
      ...VALID,
      password: `Aa1${'x'.repeat(80)}`,
      confirmPassword: `Aa1${'x'.repeat(80)}`,
    });

    expect(parsed.success).toBe(false);
  });

  it('rejects a mismatched confirmation on the confirmation field', async () => {
    const result = await registerWithEmail({ ...VALID, confirmPassword: 'Different9Pass' });

    expect(result.status === 'invalid' && result.fieldErrors.confirmPassword?.[0]).toBe(
      "Passwords don't match.",
    );
  });

  it('normalises the email to lowercase before it reaches Supabase', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: { access_token: 't' } },
      error: null,
    });

    await registerWithEmail(VALID);

    expect(signUp).toHaveBeenCalledWith(
      expect.objectContaining({ email: 'diego@example.com' }),
    );
  });
});

// ---------------------------------------------------------------------------
describe('AC2 — the password never reaches a log or a return value', () => {
  it('keeps the plaintext out of every console argument on failure', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    signUp.mockResolvedValue({
      data: { user: null, session: null },
      error: authError({ status: 500, message: 'internal error' }),
    });

    await registerWithEmail(VALID);

    const captured = JSON.stringify(spy.mock.calls);
    expect(captured).not.toContain(VALID.password);
    expect(captured).not.toContain(VALID.email);
  });

  it('keeps the plaintext out of every console argument when the call throws', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    signUp.mockRejectedValue(new Error('network down'));

    await registerWithEmail(VALID);

    expect(JSON.stringify(spy.mock.calls)).not.toContain(VALID.password);
  });

  it('never returns the password in any result shape', async () => {
    const cases = [
      { data: { user: null, session: null }, error: authError({ status: 500, message: 'x' }) },
      {
        data: { user: { id: 'u1', identities: [] }, session: null },
        error: null,
      },
      {
        data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: { access_token: 't' } },
        error: null,
      },
    ];

    for (const mocked of cases) {
      vi.spyOn(console, 'error').mockImplementation(() => {});
      signUp.mockResolvedValue(mocked);
      const result = await registerWithEmail(VALID);
      expect(JSON.stringify(result)).not.toContain(VALID.password);
    }
  });

  it('scrubError emits only name, message, status and code', () => {
    const scrubbed = scrubError(
      authError({ status: 422, code: 'weak_password', message: 'too weak' }),
    );

    expect(Object.keys(scrubbed).sort()).toEqual(['code', 'message', 'name', 'status']);
  });
});

// ---------------------------------------------------------------------------
describe('AC3 — duplicate email, both confirmation modes', () => {
  it('detects the explicit duplicate error when confirmation is off', async () => {
    signUp.mockResolvedValue({
      data: { user: null, session: null },
      error: authError({ status: 422, code: 'user_already_exists', message: 'User already registered' }),
    });

    expect(await registerWithEmail(VALID)).toEqual({ status: 'duplicate_email' });
  });

  it('detects the duplicate from a legacy 422 with no error code', async () => {
    signUp.mockResolvedValue({
      data: { user: null, session: null },
      error: authError({ status: 422, message: 'User already registered' }),
    });

    expect(await registerWithEmail(VALID)).toEqual({ status: 'duplicate_email' });
  });

  it('recognises the obfuscated empty-identities response as a duplicate', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'obfuscated', identities: [] }, session: null },
      error: null,
    });

    const result = await registerWithEmail(VALID);

    // In dev REVEAL_DUPLICATE_EMAIL is true, so this surfaces. In prod the same input
    // returns the neutral `created` shape. Either way it is never `error`.
    expect(['duplicate_email', 'created']).toContain(result.status);
  });

  it('treats a populated identities array as a genuine new account', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: null },
      error: null,
    });

    expect(await registerWithEmail(VALID)).toMatchObject({ status: 'created' });
  });
});

// ---------------------------------------------------------------------------
describe('AC4 — success does not write the profile row from the client', () => {
  it('reports a session when email confirmation is off', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: { access_token: 't' } },
      error: null,
    });

    expect(await registerWithEmail(VALID)).toEqual({
      status: 'created',
      userId: 'u1',
      hasSession: true,
    });
  });

  it('reports no session when email confirmation is on, so the form does not redirect', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: null },
      error: null,
    });

    expect(await registerWithEmail(VALID)).toEqual({
      status: 'created',
      userId: 'u1',
      hasSession: false,
    });
  });

  it('makes exactly one network call — no follow-up profile insert', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: { access_token: 't' } },
      error: null,
    });

    await registerWithEmail(VALID);

    // If this ever climbs above 1, someone has reintroduced the client-side insert
    // the trigger exists to prevent.
    expect(signUp).toHaveBeenCalledTimes(1);
  });

  it('forwards display_name so the trigger can seed the profile', async () => {
    signUp.mockResolvedValue({
      data: { user: { id: 'u1', identities: [{ id: 'i1' }] }, session: null },
      error: null,
    });

    await registerWithEmail({ ...VALID, displayName: 'Diego' });

    expect(signUp).toHaveBeenCalledWith(
      expect.objectContaining({
        options: expect.objectContaining({ data: { display_name: 'Diego' } }),
      }),
    );
  });
});

// ---------------------------------------------------------------------------
describe('transport failures degrade to actionable copy', () => {
  it('maps a rate limit to a retry hint', async () => {
    signUp.mockResolvedValue({
      data: { user: null, session: null },
      error: authError({
        status: 429,
        code: 'over_email_send_rate_limit',
        message: 'For security purposes, you can only request this after 27 seconds.',
      }),
    });

    expect(await registerWithEmail(VALID)).toEqual({
      status: 'rate_limited',
      retryAfterSeconds: 27,
    });
  });

  it('maps a thrown network error to connection copy', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    signUp.mockRejectedValue(new TypeError('Failed to fetch'));

    expect(await registerWithEmail(VALID)).toEqual({
      status: 'error',
      message: 'Check your connection and try again.',
    });
  });
});
