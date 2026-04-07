---
name: autonomy-hub-astro-site
description: Use when working on Lobo Builder's public Astro site in `apps/site`, including layout, copy, sections, styling, and Vercel-facing static deployment concerns.
---

# Autonomy Hub Astro Site

Use this skill for public-site tasks only.

## Read first

- `apps/site/astro.config.mjs`
- `apps/site/src/pages/index.astro`
- `apps/site/src/layouts/BaseLayout.astro`
- `apps/site/src/components/*`
- `apps/site/src/data/site.ts`
- `apps/site/src/styles/global.css`

## Guardrails

- Keep the landing isolated from backend runtime code in `src/autonomy_hub`.
- Reuse existing Astro components and site data before introducing new sections or patterns.
- Prefer meaningful visual hierarchy and product clarity over generic dashboard-like layouts.
- Validate with `npm run check` and `npm run build` from `apps/site`.
- Use `deploy-to-vercel` when the task includes publishing the landing.
