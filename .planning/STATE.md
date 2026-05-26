# STATE.md

## Current Status
**Milestone**: 1 — Solar+BESS Modulation Risk Tool v2
**Active Phase**: None (all phases complete — milestone ready for audit/close)
**Branch**: `002-modulation-risk-tool`
**Last Updated**: 2026-05-21

## What Just Happened
- All 7 implementation phases are complete (Setup → Report Polish)
- Full test suite passing (`pytest tests/` exit 0)
- HTML report generation working (`output/<run-id>/report.html`)
- Backtest infrastructure implemented (`backtest.py`, `output/backtest_2021_2026_projected/`)
- GSD `.planning/` bootstrapped via `gsd-ingest-docs` from `specs/002-modulation-risk-tool/`

## Next Steps
- Run `gsd-audit-milestone` to audit milestone 1 completion before closing
- Or run `gsd-new-milestone` to start milestone 2 (new features)
- Outstanding: tasks.md task checkboxes not yet ticked (tracking debt only — codebase is complete)

## Key Decisions (from ADR/research.md)
- Garantia física dispatch model (v2) — replaced curtailment-based model
- BigQuery mandatory for price data — no fallback, run aborts on unavailability
- Three fixed scenarios A/B/C (2h peak 18-19h, 4h peak 17-20h)
- CAPEX fixed by duration: 2h=164.57 USD/kWh, 4h=151.79 USD/kWh
- Plotly inline HTML for self-contained offline reports
- No pvlib — CSV required (no synthetic solar profile)

## Blocked / Risks
None known.
