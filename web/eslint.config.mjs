import { dirname } from 'path';
import { fileURLToPath } from 'url';
import { FlatCompat } from '@eslint/eslintrc';

/**
 * GameGPT · E1 · ESLint 9 flat config.
 *
 * Flat config rather than .eslintrc because ESLint 8 reached end of life in October 2024.
 * The practical consequence for CI: flat config dropped `--ext`, so the lint script is a
 * bare `eslint .` and the file scoping lives here instead of on the command line.
 *
 * `next/core-web-vitals` carries the React and a11y rules; `next/typescript` layers on
 * @typescript-eslint. Both still ship as eslintrc-shaped configs, which is what FlatCompat
 * is translating.
 */

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({ baseDirectory: __dirname });

export default [
  {
    // Flat config has no cascade, so build output and generated files have to be excluded
    // here or `eslint .` walks straight into them.
    ignores: [
      '.next/**',
      'node_modules/**',
      'next-env.d.ts',
      'coverage/**',
      // Emitted by `npm run gen:api` from the frozen OpenAPI contract, not hand-written.
      'lib/api/schema.d.ts',
    ],
  },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
];
