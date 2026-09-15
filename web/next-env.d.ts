/// <reference types="next" />
/// <reference types="next/image-types/global" />

// NOTE: This file should not be edited.
// See https://nextjs.org/docs/app/api-reference/config/typescript for more information.
//
// Committed deliberately (E1). It carries the ambient module declaration for `.css`
// imports, so without it `tsc --noEmit` fails on app/layout.tsx's `import "./globals.css"`
// in any checkout where `next dev`/`next build` has not run — which is every CI run.
