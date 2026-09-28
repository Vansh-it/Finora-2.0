# Finora India — Architecture

How the India foundation, the India dashboard, and the region contracts fit
together, and which decisions are load-bearing.

Scope note: this is the **fixture-backed foundation**. Live NSE/BSE ingestion
is deliberately not here — see [Not built yet](#not-built-yet).

---

## Layering

Data flows one way. Nothing below talks to anything above it.

```
fixtures / adapter            lib/india/fixtures.py, (future) india/adapter.py
        │  produce CanonicalCompanyData
        ▼
canonical models              lib/core/canonical_models.py
        │  identity, periods, statements, ownership, market data, sources
        ▼
metric engine                 lib/metrics/engine.py  + registry.py + definitions.py
        │  MetricResult / MetricDefinition — the only place arithmetic lives
        ▼
forensics + detectors         lib/india/forensics.py, lib/india/detectors.py
        │  DetectorResult — evidence, rule, sources
        ▼
dashboard builder             lib/india/dashboard_builder.py + models.py
        │  one JSON payload per entity type
        ▼
HTTP                          app.py  →  src/lib/indiaApi.ts  →  src/pages/IndiaDashboardPage.tsx
```

The engine is the only component allowed to divide. A detector that computes
its own ratio is a second, divergent definition of that ratio.

---

## Core contracts (`lib/core/`)

### `canonical_models.py`

`CanonicalCompanyData` is the boundary every adapter must produce. Two details
are load-bearing and were both gotchas:

**Statements are scope-keyed.** The metric key is
`f"{metric_id}|{period}|{statement_scope}"`. Indian issuers publish both
consolidated and standalone figures, which are materially different — the
fixture group's revenue is ~1.5x its parent's. Keying on `metric_id|period`
alone let the second write silently overwrite the first and made the engine's
scope fallback a no-op that could never prefer a scope.

`CanonicalStatement.get()` has a deliberate fallback rule:

- requested scope hits → return it
- requested scope is **present in this statement** but the metric isn't there
  → return `None`. The dataset publishes this basis, so the metric is genuinely
  missing. Returning the other basis here would answer a group-level question
  with parent-only numbers, wrong by ~50%.
- requested scope is **absent from this statement entirely** → fall back. This
  is a single-scope adapter (Bank, NBFC), where the one recorded basis is all
  there is. The result reports its real scope via `m.statement_scope`.

`available_scopes()` reports what the adapter actually recorded, so the scope
selector only appears when there is something to switch to.

### `regions.py`

Routing key is the company's **ISO-3166 country code**. Never currency — a
US-domiciled issuer trading in INR is a US company, and an Indian issuer
reporting in USD is still an Indian company.

`require_supported_region()` is called in `app.py` *before* the SEC fetch
starts. Without it an Indian company falls through to the US pipeline and fails
much later with an EDGAR error that says nothing about the real cause; with it,
the request is refused up front with a 501 and a reason.

`REGION_PIPELINES_AVAILABLE` is the switch. India is `False` because the
adapter is fixture-only. Flipping it to `True` is the single change that
starts routing Indian companies to a live pipeline.

### `conflicts.py`

`classify_conflict()` / `build_conflict()` handle multiple candidate values
for one metric from different sources. Present but not yet reachable — see
[Not built yet](#not-built-yet).

---

## Metric layer (`lib/metrics/`)

`definitions.py` registers **223 metrics** in one place: display name,
category, applicable entity types, unit, requirement, calculation method,
inputs, formula, methodology, and `source_priority`.

`registry.py` holds `MetricDefinition` plus two contracts worth knowing:

- `SourceType` — the vocabulary for provenance, kept beside the definitions so
  a metric can declare what it trusts without importing the data layer.
  Machine-readable XBRL outranks an annual-report PDF, which outranks an
  IR summary. `FIXTURE` ranks **last** everywhere, so development data can
  never outrank a real filing if both are ever present.
- `order_sources()` — sorts a metric's evidence trail by that ranking, demoting
  unrecognised source types rather than dropping them. This orders the
  evidence a reader sees; it does **not** choose between conflicting values
  (see the caveat below).

### `engine.py`

Four rules that shape almost every result:

1. **Zero and negative denominators are refused, not clamped.** `ratio_value()`
   returns a typed refusal. A negative *numerator* is fine — negative FCF is a
   real and important fact — so the guard is asymmetric by design.
2. **Partial aggregation is explicit.** Optional statement lines may be
   absent; the aggregate is marked `partial=True` rather than silently summing
   fewer things.
3. **Mixed currency and mixed scope sums are refused.** `_sum_parts()` will not
   add USD to INR, nor consolidated to standalone, and the reason names the
   conflict so the UI can explain it.
4. **Recorded lines are authoritative.** `resolve_input()` returns what the
   filing says. `calculate()` on a metric an adapter also recorded can return
   the derived value while `resolve_input()` returns the reported one — these
   are intentionally different views, not a contradiction. (An earlier attempt
   to make formulas override recorded values was reverted; the reported number
   is the one the company is accountable for.)

`ev_fcf` is the visible consequence: consolidated FY2026 FCF is negative, so
the EV/FCF multiple is unavailable rather than negative. That dropped corporate
coverage from 76/82 to 75/82, which is the correct trade.

---

## Forensic layer (`lib/india/`)

### `forensics.py` — 18 detectors

Receivables vs revenue, inventory vs revenue, gross/EBITDA/operating margin
deterioration, FCF decline, PAT-vs-OCF and PAT-vs-FCF divergence, debt
acceleration (which is also where net-debt/EBITDA deterioration lives),
interest coverage, current ratio, NWC, cash conversion cycle, dilution,
promoter holding reduction, promoter pledge increase, exceptional-item
dependence, and four event-driven contracts pending source integration.

`_margin()` is canonical here; `detectors.py` re-exports it rather than keeping
a second copy.

**Status is a four-way distinction, not a boolean:**

| Status | Meaning |
| --- | --- |
| `ACTIVE` | The detector ran and found a problem |
| `CLEAN` | It ran and found nothing wrong — a real result, with evidence |
| `INSUFFICIENT_DATA` | It could not run; nothing was learned |
| `PENDING_SOURCE_INTEGRATION` | A contract waiting on a data source |

Collapsing `CLEAN` into `INSUFFICIENT_DATA` would report "we checked and you're
fine" as "we couldn't check", which is how a research tool loses trust.

### `detectors.py` — entity wiring

`run_corporate_detectors()`, `run_bank_detectors()`, `run_nbfc_detectors()`
select the applicable set. The bank/NBFC runs are largely `_trend_detector`
calls — a year-over-year trend with an explicit direction — because that is
what asset-quality deterioration is.

### `dashboard_builder.py` / `models.py`

`build_india_dashboard(data, scope)` returns the full payload: header, KPIs,
statements, tabs, ownership, forensics, valuation, macro, sources,
completeness. `models.py` owns the per-entity tab schema so adding a tab is a
declaration, not a code change.

---

## Frontend

### `src/components/dashboard/shared/` — the region-agnostic layer

Eight components: `StatementTable`, `MetricCard`, `MetricGrid`, `RedFlagList`,
`ForensicModelCards`, `OwnershipTable`, `MacroContextStrip`, `SourceLedger`.

`types.ts` defines **structural** contracts (`SharedMetricCard`,
`SharedStatement`, …). A US payload and an India payload are both assignable
without either importing the other.

What the shared layer may not contain: a currency, an exchange, a fiscal-year
convention, a filing regime, or any region's types. Everything arrives
pre-formatted from the engine as `display_value`; this layer only decides
layout. Region facts are passed in — `MacroContextStrip` requires a `title`
because "India Macro Context" would mislabel the US strip, and
`OwnershipTable` is generic over its row type because promoter/FII/DII are
Indian disclosure concepts with no US equivalent.

`backend/tests/test_frontend_architecture.py` enforces this by scanning the
sources for region tokens. It lives in the Python suite because pytest is this
repo's only test runner; it checks behaviour, not prose, by stripping comments
first.

### India-specific layer

`india/IndiaPrimitives.tsx` (fixture banner, scope selector, company header,
research-quality bar), `india/IndiaSections.tsx` (the two components carrying
genuine Indian domain facts — the holder-category column set and the macro
title), `india/IndiaEvidenceDrawer.tsx` (formula, inputs, sources, rules for
any inspected item).

`india/IndiaMetricCardView.tsx` was deleted; `shared/MetricCard` supersedes it.

### One rule worth stating twice

An unavailable metric renders as `—` with its reason, **never as `0`**. A
missing input and a measured zero are different facts, and collapsing them is
the single most misleading thing a financial dashboard can do.

---

## Fixtures

`fixtures.py` builds three fictional entities, FY2022–FY2026: a corporate with
a worsening receivables/FCF story, a bank with mild asset-quality
deterioration, and a fast-growing NBFC. Every source is `FIXTURE`-typed,
`is_fixture=True`, and surfaced in the UI as `[DEV FIXTURE]`.

The corporate fixture also carries FY2026 **standalone** statements, which
balance exactly. The story they tell is the point: consolidated FCF is
-16.2B while standalone FCF is +26.2B, so the FCF red flag belongs to the
group, not the parent. A user who switches scope can see that.

### Known defect (consolidated corporate balance sheet)

Deliberately **not fixed**; pinned by `TestFixtureIntegrity` so it cannot drift
silently or be mistaken for an engine bug.

| Discrepancy | Amount |
| --- | --- |
| Reported `total_current_assets` below its components | 0.3B |
| Reported `total_non_current_assets` below its components | 0.8B |
| Assets exceed liabilities + equity | 22.2B |

The standalone basis is the control: it ties out exactly, which is what proves
the engine reports the consolidated imbalance rather than manufacturing it.

Cash flow, by contrast, is fully coherent — operating + investing + financing
equals net change in cash in all five years. `TestCashFlowCoherence` pins that,
because the FCF detectors are only meaningful if FCF is a faithful function of
the recorded lines.

---

## Demo status

| Entity | Coverage | Flags |
| --- | --- | --- |
| Corporate | 91.5% (75/82) | 3 active, 13 clean, 1 insufficient, 4 pending |
| Bank | 94.9% (37/39) | 8 active, 2 clean |
| NBFC | 93.2% (41/44) | 7 active, 1 clean, 1 not-applicable |

Corporate has no standalone/consolidated divergence in the flag counts because
the detectors read the scope they are asked for; the divergence shows up in the
numbers and in the scope selector, which is the intended surface.

---

## Not built yet

Named so they are not mistaken for oversights:

- **Live India ingestion.** No NSE/BSE scraping, XBRL fetch, or paid data
  provider. `lib.india.adapter` does not exist; `fixtures.py` stands in.
- **Multi-candidate value resolution.** `conflicts.py` can classify and build
  a `MetricConflict`, but the canonical store holds one value per
  (metric, period, scope), so there is nothing yet to conflict.
  `registry.order_sources()` orders the *evidence trail* only. Choosing which
  of two disagreeing values to believe needs a multi-candidate value model.
- **US dashboard adoption of the shared layer.** The eight components are
  region-agnostic and India consumes them; the US dashboard has not been
  migrated onto them yet.
- **Adverse `forensic` finding vs. plain `detector` finding.** One status
  vocabulary covers both for now.
