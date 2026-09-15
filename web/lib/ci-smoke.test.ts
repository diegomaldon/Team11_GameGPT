import { describe, it, expect } from 'vitest';

/**
 * GameGPT · E1 · Pipeline smoke test.
 *
 * This exists so the `Unit tests` check has something to run before E2 lands any real
 * tests. Without it `vitest --run` finds no test files, exits 1, and the CI PR is red on
 * arrival — which would make the pipeline look broken on the very PR that introduces it.
 *
 * The alternative was `passWithNoTests: true`, rejected because it makes the check pass
 * without ever proving Vitest works on the runner. That is the one thing this PR needs to
 * demonstrate.
 *
 * Safe to delete once E2's register.test.ts is merged.
 */
describe('CI pipeline', () => {
  it('runs Vitest and evaluates assertions', () => {
    expect(1 + 1).toBe(2);
  });

  it('executes TypeScript without a separate build step', () => {
    const double = (n: number): number => n * 2;
    expect(double(21)).toBe(42);
  });
});
