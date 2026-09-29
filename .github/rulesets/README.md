# Branch rulesets

`main-protection.json` is the ruleset that makes E1/AC2 true. The workflow in
`../workflows/ci.yml` only *reports* status — a GitHub Actions workflow has no authority to
block a merge. This file is the half that actually blocks.

## Importing it

Repo → **Settings** → **Rules** → **Rulesets** → **New ruleset** → **Import a ruleset**,
then select `main-protection.json`. Review the screen and click **Create**.

Importing is preferable to filling the form in by hand for one specific reason: the UI's
status-check picker only lists checks it has already seen run, so on a fresh repo you cannot
select `Lint`, `Typecheck` or `Unit tests` until the workflow has run on `main` at least
once. Import accepts them by name regardless.

## What each rule does, and which AC it satisfies

| Rule in the JSON | Effect | AC2 bullet |
|---|---|---|
| `pull_request`, `required_approving_review_count: 1` | No direct pushes to `main`; every change needs a PR with one approval | "direct pushes to `main` are blocked" |
| `required_status_checks` → `Lint`, `Typecheck`, `Unit tests` | Merge button disabled until all three pass, and it names the failing one | "All three checks block merge on failure" |
| `strict_required_status_checks_policy: true` | Branch must be up to date with `main` before merging | "require branches to be up to date" |
| `non_fast_forward` | Blocks force pushes to `main` | "Block force pushes" |
| `deletion` | Blocks deleting `main` | not required, cheap insurance |
| `bypass_actors: []` | Empty on purpose — admins are subject to the rules too | "enforced on admins too" |

## Notes

- `~DEFAULT_BRANCH` targets whatever the default branch is, so this keeps working if `main`
  is ever renamed. Replace with `refs/heads/main` to pin it literally.
- The three contexts are the `name:` values of the jobs in `ci.yml`, not the job ids. If you
  rename a job there, update it here or the ruleset will wait forever on a check that no
  longer reports.
- `ci.yml` also defines an aggregate `CI` job. Requiring that single check instead of the
  three named ones means adding a fourth job later needs no ruleset edit — but AC2 asks for
  the three by name, so that is what this file does.
- Rulesets need GitHub Pro or higher on private repos. Free on public repos. GitHub
  Education benefits cover it.

## Evidence for grading

The JSON is not evidence on its own. AC2 asks for a screenshot of the ruleset screen after
import, plus a screenshot of a PR with the merge button disabled by a failing check.
