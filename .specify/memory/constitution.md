<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.1.0 (MINOR — two new principles added; all existing
principles materially expanded with Brazilian sector context and code quality requirements)

Modified principles:
  I.  Physics-Constrained Modeling → Brazilian Sector Compliance (ONS/ANEEL/CCEE)
  II. Modular Risk Decomposition → No Data Fabrication — Explicit & Parametrizable Assumptions
  III. Test-First (unchanged name, content refined)
  IV. Auditability and Reproducibility → Reproducible Results (seed + input versioning expanded)
  V.  Simplicity and Calibration-Driven → Modular Python Architecture with Typing and Docstrings

Added principles:
  VI. Engineering-Quality Visualizations (new)
  VII. SI Units with Brazilian Sector Conventions (new)

Added sections: none
Removed sections: none

Templates updated:
  ✅ .specify/memory/constitution.md (this file)
  ✅ .specify/templates/plan-template.md (Constitution Check gates updated for 7 principles)
  ✅ .specify/templates/spec-template.md (no changes required)
  ✅ .specify/templates/tasks-template.md (no changes required)

Migration note for branch 001-solar-bess-curtailment-analyzer:
  - spec.md Assumptions section already compatible with new Principles II and VII.
  - Plan and task generation must include VI (visualization quality gates) and VII (unit
    annotation requirements) as explicit task acceptance criteria.

Deferred TODOs: None.
-->

# Solar BESS Modulation Risk Constitution

## Core Principles

### I. Brazilian Sector Compliance (ONS, ANEEL, CCEE)

All models, risk calculations, and energy accounting MUST reference and comply with the
applicable Brazilian electricity sector regulatory framework:

- **ONS**: Modulation and frequency deviation limits follow ONS grid codes (Procedimentos
  de Rede). Curtailment and dispatch constraints must reference ONS instructions where
  applicable.
- **ANEEL**: Generation curtailment definitions and compensation rules follow ANEEL
  resolutions. Any model output labelled as "curtailment" MUST use the ANEEL-consistent
  definition (involuntary reduction of injected power at the point of connection).
- **CCEE**: Energy accounting for settlement purposes (MWh registered, contracted vs.
  measured) MUST use CCEE conventions when results inform commercial analysis.

Every model output MUST explicitly identify which norm or standard it validates against.
Deviations from regulatory limits are risk events and MUST be surfaced as named,
structured findings — not buried in numeric totals.

### II. No Data Fabrication — Explicit & Parametrizable Assumptions

No model may silently assume a value. Every numerical assumption — efficiency, degradation
rate, energy price, irradiance factor, capacity factor, grid emission factor — MUST be:

- Explicitly declared with a documented source or physical justification.
- Exposed as a configurable parameter with a documented default value and unit.
- Validated at input time against physically and commercially plausible bounds (with
  bounds themselves documented and configurable).

Synthetic data (e.g., generated solar profiles) MUST be labelled as synthetic in all
outputs. The generation method, parameters, and seed MUST be recorded alongside the data.
Results derived from synthetic data MUST NOT be presented as equivalent to results derived
from measured data without an explicit caveat.

### III. Test-First (NON-NEGOTIABLE)

TDD is mandatory for all risk model logic, modulation algorithms, and economic calculations.
Tests MUST be written and reviewed before implementation begins. The Red-Green-Refactor
cycle is strictly enforced:

- Write failing unit tests that encode acceptance scenarios from `spec.md`.
- Obtain confirmation the tests represent correct expected behavior before implementing.
- Implement only enough code to make all tests pass.
- Refactor without breaking any test.

Physical constraint tests (SoC bounds, power limits, energy conservation) MUST be present
for every BESS dispatch function. Economic formula tests MUST include at least one
manually calculated reference case. No risk calculation logic is considered complete
without a passing, peer-reviewed test suite.

### IV. Reproducible Results — Seeded Randomness & Input Versioning

Every analysis run MUST be exactly reproducible:

- Any stochastic process (synthetic profile generation, Monte Carlo sampling) MUST use
  an explicitly seeded RNG. The seed MUST be a configurable parameter (default documented).
- All input configurations MUST be serialised to a JSON manifest alongside every output.
  The manifest includes: tool version, run timestamp (ISO 8601), SHA-256 hash of the
  input configuration, and the RNG seed value.
- Outputs are stored in a run-specific directory named by run ID to prevent overwriting.
- Two runs with identical manifests MUST produce byte-identical numerical results.

### V. Modular Python Architecture with Typing and Docstrings

All Python source code MUST follow clean, modular design principles:

- Every public function and class MUST carry complete PEP 484 type annotations on all
  parameters and return values. Physical quantity parameters MUST include the unit in
  the parameter name or annotation comment (e.g., `power_mw: float`).
- Every public function and class MUST have a NumPy-style docstring covering: purpose,
  parameters (name, type, unit, description), return values (type, unit), and raised
  exceptions.
- No single module exceeds 400 lines of non-test code. Complex logic is split into
  independently importable submodules.
- Magic numbers are forbidden in source. All physical constants and default parameters
  live in a dedicated `config.py` or `constants.py` with inline unit documentation.
- Modules are independently importable — no circular imports, no global mutable state.

### VI. Engineering-Quality Visualizations

Charts MUST be designed for engineering decision-making, not decoration:

- Every chart MUST have: a descriptive title, labeled axes with explicit units, and a
  legend when multiple series are present.
- Color scales for scalar data MUST be perceptually uniform (e.g., viridis, plasma).
  Rainbow/jet colormaps are forbidden for quantitative data.
- Interactive charts MUST provide hover tooltips that show the exact value and unit of
  each data point, not just relative position.
- Every chart MUST be interpretable without running any additional code — all necessary
  context (units, scenario labels, parameter values used) MUST appear in the chart itself.
- The HTML report MUST include a dedicated "Model Assumptions & Limitations" section
  adjacent to the charts, explicitly cross-referencing which assumptions affect each
  visualisation.

### VII. SI Units with Brazilian Sector Conventions

Physical quantities MUST use consistent units throughout all code, documentation, and
outputs:

| Quantity | Unit | Notes |
|---|---|---|
| AC power capacity | MWac | Always suffix "ac" when DC/AC distinction matters |
| DC power capacity | MWp | Megawatt-peak (nominal STC) |
| Energy | MWh | No kWh in public interfaces (use MWh × 10³ factor note instead) |
| Frequency | Hz | Grid nominal: 60 Hz (Brazilian grid) |
| Storage duration | h | Hours |
| Currency (Brazil) | BRL/MWh | Label must appear on every monetary output |
| Currency (international) | USD/kWh | Label must appear on every CAPEX input/output |
| Degradation | %/year | Explicit per-year suffix |
| Efficiency | % | Round-trip basis; document charge and discharge split if asymmetric |

Unit labels MUST appear in: Python variable names or inline annotations, docstrings,
chart axis labels, and all summary table column headers. Mixing unit systems in a single
computation without an explicit documented conversion factor is forbidden.

## Domain Constraints

The following operational constraints apply to all features within this project:

- **Time-series ordering**: Solar generation and BESS telemetry MUST be handled as
  strictly ordered, timestamped hourly sequences (8,760 values per year). Out-of-order
  or missing hours MUST be flagged as structured errors — silent interpolation is forbidden
  unless the interpolation method and its impact are documented.
- **Grid frequency reference**: The Brazilian grid nominal frequency is 60 Hz. All
  frequency deviation risk thresholds and modulation limits MUST be expressed relative
  to 60 Hz unless an explicit ONS reference states otherwise.
- **No silent failures**: Any computation unable to produce a valid result (missing data,
  constraint violation, numerical instability, division by zero) MUST raise a structured
  exception with a human-readable message identifying the failing input and its value.
  Returning `NaN`, `None`, or 0 as a sentinel is forbidden unless the condition is
  explicitly documented and the caller is required to handle it.
- **Scale convention**: All models are normalised to 1 MWac unless the feature spec
  explicitly requires absolute sizing. Outputs must clearly state the normalisation basis
  so analysts can scale results to their actual plant capacity.

## Development Workflow

The following workflow MUST be followed for every feature:

1. **Specify**: Capture requirements and acceptance scenarios in `spec.md` using the
   `/speckit-specify` command. Spec MUST be approved before planning begins.
2. **Clarify**: Resolve all `NEEDS CLARIFICATION` items via `/speckit-clarify` before
   proceeding to planning.
3. **Plan**: Produce design artifacts (research, data model, contracts) via `/speckit-plan`.
   The Constitution Check gate in `plan.md` MUST pass for all seven principles before
   Phase 1 design begins.
4. **Tasks**: Generate a dependency-ordered task list via `/speckit-tasks`. Tasks are
   organised by user story to enable incremental, independently testable delivery. Each
   task MUST specify the file path and the principle(s) it fulfils.
5. **Implement**: Execute tasks via `/speckit-implement`. Tests MUST be written and failing
   before implementation (Principle III). Unit annotations and docstrings are required
   before a task is marked complete (Principles V and VII).
6. **Review**: All PRs MUST include a Constitution Check comment verifying compliance with
   all seven Core Principles and all Domain Constraints.

Feature branches follow the naming convention `NNN-short-description` (sequential numbering).

## Governance

This constitution supersedes all other documented practices for this project. Any conflict
between this constitution and another document (README, ticket, verbal instruction) resolves
in favour of this constitution unless an amendment has been ratified.

**Amendment procedure**:

1. Propose the amendment in a dedicated PR with a written rationale.
2. Increment `CONSTITUTION_VERSION` per semantic versioning rules (MAJOR for principle
   removals or breaking redefinitions, MINOR for additions or material expansions,
   PATCH for clarifications and wording refinements).
3. Update `LAST_AMENDED_DATE` to the merge date.
4. Run the `/speckit-constitution` command to propagate changes to all dependent templates.
5. Add a migration note in the Sync Impact Report for any in-progress feature branches
   affected by the amendment.

**Compliance**: All PRs MUST include verification that the implementation does not violate
any of the seven Core Principles or Domain Constraints. Complexity beyond what is justified
by acceptance scenarios MUST be explicitly approved. Refer to `CLAUDE.md` for runtime
development guidance.

**Version**: 1.1.0 | **Ratified**: 2026-05-15 | **Last Amended**: 2026-05-15
