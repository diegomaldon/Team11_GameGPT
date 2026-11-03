# TM11-142 UI overhaul: before and after

Evidence for AC-02 (documented changes). The written summary of what changed is in
[`docs/FRONTEND.md` → UI overhaul (TM11-142)](../../../docs/FRONTEND.md#ui-overhaul-tm11-142).

`before/` is `main` at `e0ec902`, the commit this branch started from. `after/` is the
`TM11-142-ui-overhaul` branch. Both were captured from the local dev server in fixture
mode (`NEXT_PUBLIC_USE_FIXTURES=1`), signed in with a test session, with reduced motion
on so the spotlight and cover wall hold still.

| Page | Before | After |
|---|---|---|
| Sign in, 1440px | [before](before/signin-1440.jpg) | [after](after/signin-1440.jpg) |
| Sign in, 375px | [before](before/signin-375.jpg) | [after](after/signin-375.jpg) |
| Register, 1440px | — | [after](after/register-1440.jpg) |
| Discover, 1440px | [before](before/discover-1440.jpg) | [after](after/discover-1440.jpg) |
| Discover, 375px | [before](before/discover-375.jpg) | [after](after/discover-375.jpg) |
| Library, 1440px | [before](before/library-1440.jpg) | [after](after/library-1440.jpg) |
| Library, 375px | [before](before/library-375.jpg) | [after](after/library-375.jpg) |
| Settings, 1440px | [before](before/settings-1440.jpg) | [after](after/settings-1440.jpg) |
| Settings, 375px | [before](before/settings-375.jpg) | [after](after/settings-375.jpg) |

What the screenshots can't show:

- **Linked accounts** stays on "Loading linked accounts…" in both sets: fixture mode
  points Supabase at a placeholder project, so that read never answers.
- **The profile card** shows the mock store's sample profile ("Alex Rivera"), as it did
  before this change.
- **Motion:** the spotlight rotates every 6 seconds and the sign-in cover wall scrolls;
  both are paused here by the reduced-motion setting.

AC-01 (the UI team approves the new style) is a sign-off, not something these files
can show. The approved design is the mockup canvas the team reviewed.
