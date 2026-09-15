# Security notes

Known, accepted risks. Each entry says what the issue is, why it is still here, and what
would fix it. Raised at the E8 security review.

---

## User enumeration via the duplicate-email path (E2, REQ001)

**Status:** accepted for the course demo. Not acceptable for a real deployment.

### What happens

`registerWithEmail` detects a duplicate address two different ways, because GoTrue reports
it differently depending on whether email confirmation is enabled:

| Email confirmation | GoTrue response | Detected by |
|---|---|---|
| **On** | success shape, obfuscated user, empty `identities` array | the `identities.length === 0` check |
| **Off** | explicit `422` / `user_already_exists` error | `isDuplicateEmailError()` |

`REVEAL_DUPLICATE_EMAIL` is meant to decide whether that fact reaches the visitor. It only
gates the first path:

```ts
// confirmation ON — gated
if (data.user && (data.user.identities?.length ?? 0) === 0) {
  return REVEAL_DUPLICATE_EMAIL
    ? { status: 'duplicate_email' }
    : { status: 'created', userId: data.user.id, hasSession: false };
}

// confirmation OFF — NOT gated
if (isDuplicateEmailError(error)) {
  return { status: 'duplicate_email' };   // returns regardless of the flag
}
```

So with email confirmation **disabled**, `registerWithEmail` returns `duplicate_email` even
when `REVEAL_DUPLICATE_EMAIL` is `false`. The form renders "That email is already
registered," and anyone can use the signup endpoint as an oracle to test whether a given
address has a GameGPT account.

### Why the flag looks like it should prevent this

Because the name suggests a policy switch, and it reads like one at the call site. It isn't:
it is a switch over exactly one of the two detection paths. The gap is invisible unless you
notice that the two paths are in different branches of the function.

### Why it is still here

1. The demo environment runs with email confirmation **on**, where the gated path is the one
   that fires and the flag does work.
2. `REVEAL_DUPLICATE_EMAIL` is `process.env.NODE_ENV !== 'production'`, so in a production
   build the intent is already "don't reveal" — the bug only bites in a configuration we do
   not deploy.
3. Fixing it changes observable behaviour, and AC3 was written around the current split
   ("given email confirmation is off … then the form shows 'That email is already
   registered'"). Changing it without changing the AC would fail the acceptance test.

That last point is the real reason. The behaviour is *specified*, so this is a spec problem,
not a code defect, and the fix belongs with a spec change rather than a quiet patch.

### What the fix looks like

Gate both paths on the same flag:

```ts
if (isDuplicateEmailError(error)) {
  return REVEAL_DUPLICATE_EMAIL
    ? { status: 'duplicate_email' }
    : { status: 'error', message: "We couldn't create your account. Try again in a moment." };
}
```

Note the neutral branch cannot return `created` here — with confirmation off there is
genuinely no account and no session, so claiming success would be a lie the UI acts on. A
generic error is the honest neutral response, at the cost of worse UX for someone who simply
forgot they had an account.

The properly correct fix is different and larger: stop signalling at signup at all, always
render "check your email", and handle duplicate accounts by sending a *password reset* mail
to the existing address instead of a confirmation. That is what services which take
enumeration seriously do, and it is out of scope for E2.

### Related

- `isDuplicateEmailError()` in `web/lib/auth/register.ts` carries a `// KNOWN:` marker
  pointing here.
- ACCEPTANCE_CRITERIA.md, E2 AC3 documents the two-mode behaviour this note qualifies.
- Rate limiting on the signup endpoint is GoTrue's default and has not been tuned. An
  enumeration attack is bounded by it but not prevented.
