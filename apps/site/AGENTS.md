# Site Agent Guide

## Scope

These instructions apply to `apps/site`.

## Role

This is the public Astro landing for Lobo Builder. It should stay clearly separate from the FastAPI dashboard and `/api/*` backend that live in the repo root.

## Guardrails

- Keep changes inside `apps/site` unless the task explicitly needs a cross-surface handoff.
- Prefer editing `src/data/site.ts`, layout/components, and `src/styles/global.css` before introducing new structure.
- Optimize for a sharp, product-facing landing page rather than an internal dashboard aesthetic.
- Validate with `npm run check` and `npm run build`.
- Use the Vercel deploy path only for the Astro site surface.

## Helpful files

- `astro.config.mjs`
- `src/pages/index.astro`
- `src/layouts/BaseLayout.astro`
- `src/components/*`
- `src/data/site.ts`
- `src/styles/global.css`
