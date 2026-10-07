# Coding Standards for GameGPT Project

**Team 11**

Diego Maldonado, Fred Joseph, Maceo Morgan, Noah Merhai

---

## Introduction

- This document gives the coding standards and best practices for the GameGPT project. GameGPT has a Python (FastAPI) back end, a TypeScript (Next.js/React) front end and a Supabase (PostgreSQL) database. Following these standards keeps the code consistent, readable and easy to maintain across the whole codebase.

## General Principles

- **Readability and Clarity:** Code should be easy to understand. Choose clarity over cleverness.
- **Consistency:** Apply the same conventions everywhere. When changing existing code, match the style around it.
- **Simplicity and Performance:** Write simple, efficient code. Don't optimise before there is a measured need.
- **Commenting and Documentation:** Comment and document code where the reason behind it isn't obvious.

## Formatting and Naming Conventions

### Indentation and Whitespace

- Python: use 4 spaces for indentation, not tabs.
- TypeScript, TSX, JSON and SQL: use 2 spaces for indentation, not tabs.
- Use blank lines sparingly inside functions to separate logical groups of statements.

### Braces and Blocks

- TypeScript: put the opening brace on the same line (K&R style).
- TypeScript: always use braces for `if`, `else`, `for`, `do` and `while`, even when the body is one statement.
- Python: keep each block body on its own line; don't write `if x: return y` on one line.

### Naming

Names follow Chapter 11 of *Code Complete* (The Power of Variable Names):

- **Describe what, not how.** A name says what the value represents.
  - Example: `match_rate`, not `calc_result`.
- **Match length to scope.** Short names are fine in a small loop; module-level names should be descriptive.
  - Example: `for g in games:` inside a small function; `IMPORT_CHUNK` at module level.
- **Put qualifiers at the end** (Total, Count, Max, Rate, Minutes).
  - Example: `matched_count`, `playtime_minutes`.
- **Name booleans so they read as true or false.**
  - Example: `is_finished`, `has_db`.
- **Include units** when a number carries one.
  - Example: `timeout_seconds`, not `timeout`.
- **Use opposite pairs consistently.**
  - Example: `first_seen_at` / `last_seen_at`.
- **Abbreviate only with agreed abbreviations:** `id`, `db`, `api`, `url`, `appid`, `req`/`resp`, `conn`/`cur`, `exc`.

Casing by language:

- **Classes, Types and React Components:** PascalCase.
  - Example: `LibrarySyncService`, `RegisterForm`.
- **Python Functions and Variables:** snake_case.
  - Example: `normalise_title`, `steam_appid`.
- **TypeScript Functions and Variables:** camelCase.
  - Example: `syncLibrary`, `steamId`.
- **Constants:** all uppercase with underscores between words.
  - Example: `DEFAULT_LIMIT`, `STEAM_API_KEY`.
- **Database Tables and Columns:** snake_case, with plural table names.
  - Example: `owned_games`, `game_id`.
- **Files:** Python `snake_case.py`; TypeScript `camelCase.ts`; React components `PascalCase.tsx`; migrations `YYYYMMDDHHMMSS_description.sql`.
- **Don't rename the SysML block classes** (`EmbeddingService`, `VectorStore`, `LLMService`, `DeduplicationService`, `RAGPipeline`, `LibrarySyncService`); they trace back to the design diagrams.

### Line Length

- Lines should not be longer than 100 characters. If needed, break them at a sensible point.

## Code Structure

### Modules and Classes

- Give each module or class one responsibility (Single Responsibility Principle).
- Keep the layers separate: routers handle HTTP only, services hold the logic, and repositories hold the SQL.
- Group related functions together for readability.

### Functions and Methods

- Functions should be short and do one task.
- Keep the number of parameters small. If a function needs more than three, use a parameter object or keyword-only arguments.
- Python: put type hints on every public function's parameters and return value.
- TypeScript: keep `strict` mode on, and don't use `any` without a comment explaining why.

## Comments and Documentation

- Start every file with a header comment saying what it does and which Jira story or requirement it serves (for example `TM11-48`, `REQ007`).
- Use docstrings (Python) or JSDoc (TypeScript) for public classes and functions whose behaviour isn't obvious from the name.
- Use inline comments to explain complex logic or decisions that aren't immediately obvious.
- Don't write comments that restate the code or add no information.
- When an API changes, update `docs/API.md` and `openapi.json` in the same pull request.

## Version Control

- Commit related changes as one logical unit, with a meaningful message in the imperative mood.
  - Example: `TM11-48 Match imported titles to games rows`.
- Use a branch for every feature or fix, named after the Jira story.
  - Example: `TM11-48-match-imported-titles`, or `fix/<description>` for small fixes.
- Never push directly to `main`.
- Never commit secrets such as API keys or passwords. Keep them in `.env`, which is git-ignored.

## Error Handling

- Prefer exceptions for errors, with typed exceptions for expected failures (for example `SteamPrivateProfileError`).
- Catch exceptions at the highest level that can handle them properly, usually the router, not at every level.
- Never use a bare `except:`, and never swallow an error silently; log it with `log.exception(...)`.
- Always clean up resources with `with` / `async with` (Python) or `try/finally` (TypeScript).
- Messages shown to users must not include stack traces, URLs or keys.

## Code Reviews

- At least one other team member must review all code before it is merged into `main`.
- All CI checks (Lint, Typecheck, Unit tests, API tests) must pass before merging.
- Reviewers check that the code follows these standards and look for logic errors and possible simplifications.
- The pull request description says what changed and why, and points out any change to a teammate's code.

## Testing

- Write unit tests for all new functions and classes where practical, in the same pull request.
- Use Test-Driven Development (TDD) where possible.
- Python tests go in `api/tests/test_<module>.py` (pytest). Web tests go next to the file under test as `<file>.test.ts` (Vitest).
- Name tests after the behaviour they check (for example `test_unmatched_is_recorded_with_reason`).
- Unit tests must run offline; fake network and database calls.
- Aim for high code coverage, but put meaningful tests ahead of coverage numbers.

## Security

- Follow secure-coding best practices to protect user data and prevent vulnerabilities.
- Use parameterised queries (`%s` placeholders) to prevent SQL injection. Never build SQL by joining strings that contain user input.
- Enable Row Level Security on every new database table.
- Never log passwords, tokens or API keys.
- Handle personal information (emails, linked accounts) according to data protection rules, and let users delete their accounts.

## Conclusion

- This document sets the foundation for developing GameGPT. Every team member is expected to follow these standards to keep the codebase high-quality and consistent. Applying them consistently makes collaboration easier and helps the project succeed.
