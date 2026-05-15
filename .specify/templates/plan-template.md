# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify compliance with all seven Core Principles and Domain Constraints from
`.specify/memory/constitution.md` (v1.1.0):

- [ ] **I. Brazilian Sector Compliance** — Model outputs reference applicable ONS/ANEEL/CCEE
  norms by name. Curtailment definition follows ANEEL conventions. Regulatory deviations
  are surfaced as named, structured findings.
- [ ] **II. No Data Fabrication** — Every numerical assumption has a documented source and
  physical/commercial justification. All parameters are configurable with documented
  defaults and validated bounds. Synthetic data is labelled as synthetic in all outputs.
- [ ] **III. Test-First** — Failing unit tests are written before implementation for all
  risk model logic, BESS dispatch functions, and economic formulas. At least one manual
  reference-case test exists for each economic formula.
- [ ] **IV. Reproducible Results** — Every run writes a JSON manifest (tool version,
  timestamp, input SHA-256, RNG seed). Stochastic processes use a configurable seeded RNG.
  Identical manifests produce identical numerical outputs.
- [ ] **V. Modular Python Architecture** — All public functions/classes have PEP 484 type
  annotations with unit suffixes in parameter names. NumPy-style docstrings present on all
  public APIs. No module exceeds 400 lines. No magic numbers in source.
- [ ] **VI. Engineering-Quality Visualizations** — Every chart has title, axis labels with
  units, and legend. Perceptually uniform colour scales used for scalar data. Hover tooltips
  show value + unit. HTML report includes "Model Assumptions & Limitations" section.
- [ ] **VII. SI Units & Brazilian Sector Conventions** — Power in MWac/MWp, energy in MWh,
  frequency in Hz (nominal 60 Hz), currency labelled BRL/MWh or USD/kWh. Unit labels in
  variable names/annotations, docstrings, axis labels, and table column headers.
- [ ] **Domain Constraints** — Time-series is strictly ordered hourly (8,760 values).
  Brazilian grid frequency reference is 60 Hz. No silent failures — all edge cases raise
  structured exceptions. Results normalised to 1 MWac with explicit normalisation note.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
