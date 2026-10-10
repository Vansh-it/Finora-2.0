# Finora Mobile — AI Financial Research (phone-only frontend)

A complete, working, mobile-only frontend for **Finora**, themed on the
reference app art: deep-black surfaces, perspective orange grid glow, glowing
orange CTAs, mono labels, snap carousels, and bottom-sheet "receipts".

> **Live preview is running** — open the preview (port `4321`) on a phone-width
> viewport. On desktop the app renders in a centered 430px phone column.

## Quick start

```bash
cd finora-mobile
npm install
npm run dev      # http://localhost:4321  (talks to the deployed Finora backend)
```

Other scripts: `npm run build`, `npm run preview`, `node smoke.mjs` (Playwright
end-to-end smoke test + screenshots into `shots/`).

## Theme mapping (reference images → Finora)

| Reference | Finora adaptation |
|---|---|
| `PERFORMANCE ANALYTICS` / `DETAILED PROGRESS REPORTS` corner labels | Same labels on landing + dashboard |
| Orange check + rays "Training complete!" | 9-stage research pipeline with DONE stamps |
| Workout detail cards (45–50 min · kcal · exercises) | KPI cards, quality pills, forensic score cards |
| Leaderboard podium + points feed | Reviews wall, quota usage, source ledger |
| AI Workout Builder ("Describe goals… Generate Plan") | `ResearchInput` + AI memo + Ask Finora sheets |
| Heart-rate / sleep chart, weekly stats | Revenue-vs-income chart (tap bars), sparklines, trend bars |
| Bottom nav with raised center button | 5-tab bar with raised **Ask AI** center action |

## Routes (16)

Public: `/` landing · `/auth` · `/methodology` · `/about` · `/reviews`
(with write-a-review sheet) · `/limit` (developer's letter + live countdown) ·
`/terms` · `/privacy` · `/more` · `*` 404.
Protected: `/research` (+ `?ticker=` 9-stage processing) · `/dashboard`
(9 swipeable tabs) · `/history` · `/profile` · `/chat` (streaming).

## Highlights

- **Every number has a receipt** — any KPI/cell opens an `EvidenceSheet`
  (formula → inputs → filing/accession → XBRL → verification), 3-deep drill-in.
- **Mobile-only shell** — 52px top bar, 64px bottom tabs, single scroll
  container, safe-area + keyboard-inset handling, no page-level horizontal scroll.
- **Smooth motion** — route slides, entrance staggers, count-ups, stamp pops,
  sheet drag physics; all disabled under `prefers-reduced-motion`.
- **A11y** — landmarks, skip link, tablist arrow keys, focus-trapped sheets,
  live regions, 44px targets, 16px inputs (no iOS zoom).
- **Real API integration** — `src/lib/api.ts` is a typed HTTP client for the
  deployed Flask backend (default `https://finora-api-dio1.onrender.com`,
  override with `VITE_API_URL`); `src/lib/adapter.ts` maps the backend payload
  onto the dashboard session shape. Auth, quota, research, history, streaming
  chat, reviews and watchlist all hit the live endpoints.
- **Verified** — `tsc` clean, `vite build` green, Playwright smoke passes with
  **zero console errors** and **0px overflow** on every route (see `shots/`).

## Stack

React 19 · TypeScript (strict, no `any`) · Vite 7/8 · react-router-dom v7 ·
Tailwind v4 · lucide-react · recharts (lazy) · react-markdown · HashRouter
(preview-safe routing).
