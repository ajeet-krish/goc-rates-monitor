# GoC Rates Monitor

Static SolidJS site plus Python uv pipeline (BoC Valet, StatCan bulk, FRED) publishing snapshots JSON to GitHub Pages.

## Quick Commands

Pipeline (uv, from repo root):
`uv sync`
`uv run pytest`
`uv run ruff check pipeline/src`
`uv run ruff format pipeline/src`

Web (SolidJS, from web dir):
`cd web`
`npm install`
`npm run build`
`npm run typecheck`

## Conventions

Use full sentences and plain punctuation (commas, colons, parentheses).
Python uses snake_case with type hints on all public functions.
SolidJS uses TypeScript with strict props typing.
Every numeric field in snapshots and code requires explicit units.
Pipeline fails closed on missing or stale source data.
Keep functions small and pure where practical.

## Project Map

`src/goc_rates/`: fetch, normalize, snapshot builders
`tests/`: pytest unit and golden snapshot tests
`config/benchmark_map.yaml`: tenor to series map
`snapshots/YYYY-MM-DD/`: committed JSON outputs
`docs/`: architecture, decisions, research, reviews, tests

## Status

| Phase | Description | Status |
| Phase 1 | Foundation clients calendar snapshot verify | Complete |
| Phase 2 | Curve engine par approx slopes carry spreads | Complete |
| Phase 3 | Site shell curve funding verification pages | Complete |
| Phase 4 | CPI engine trim median validation | Complete |
| Phase 5 | Inflation breaks verification methods polish | Complete |
| Phase 6 | True bootstrap with benchmark map post launch | In Progress |

## Deep Docs

Architecture: docs/architecture.md
Decisions: docs/decisions.md
Research: docs/research.md
Reviews: docs/reviews.md
Tests: docs/tests.md
