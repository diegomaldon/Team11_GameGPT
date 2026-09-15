import { defineConfig } from 'vitest/config';

/**
 * GameGPT · E1 · Vitest configuration.
 *
 * `environment: 'node'` is deliberate, not a leftover default. The E2 auth tests stub
 * `window` themselves with `vi.stubGlobal`, so pulling in jsdom would replace their
 * controlled stub with a real DOM and cost a second of startup per run for nothing.
 * A component test that needs a DOM should set `// @vitest-environment jsdom` per file.
 */
export default defineConfig({
  test: {
    environment: 'node',
    // `.next` holds compiled copies of source files; without this, every test would be
    // discovered twice once the app has been built locally.
    exclude: ['node_modules/**', '.next/**'],
    coverage: {
      provider: 'v8',
      // Written to web/coverage/, which is what the CI upload-artifact step points at.
      reportsDirectory: './coverage',
      reporter: ['text', 'lcov'],
      exclude: ['node_modules/**', '.next/**', '**/*.config.*', '**/*.test.*'],
    },
  },
});
