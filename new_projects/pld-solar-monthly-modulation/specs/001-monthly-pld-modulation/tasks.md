# Tasks: Monthly PLD Solar Modulation

**Input**: Design documents from `specs/001-monthly-pld-modulation/`

## Phase 1: Setup

- [x] T001 Create isolated subproject structure in `new_projects/pld-solar-monthly-modulation/`
- [x] T002 Create project metadata in `new_projects/pld-solar-monthly-modulation/pyproject.toml`

## Phase 2: Foundational

- [x] T003 Create constants and structured errors in `src/solar_monthly_modulation/constants.py` and `src/solar_monthly_modulation/errors.py`
- [x] T004 Create dataclasses in `src/solar_monthly_modulation/models.py`
- [x] T005 Create adapters around existing Solar+BESS loaders in `src/solar_monthly_modulation/adapters.py`

## Phase 3: User Story 1 - Calculate Monthly Modulation

- [x] T006 [P] [US1] Write unit tests for monthly weighted-price formulas in `tests/unit/test_modulation.py`
- [x] T007 [US1] Implement monthly and annual modulation formulas in `src/solar_monthly_modulation/modulation.py`

## Phase 4: User Story 2 - Audit Reproducible Inputs

- [x] T008 [P] [US2] Write manifest unit coverage in `tests/unit/test_modulation.py`
- [x] T009 [US2] Implement manifest writer in `src/solar_monthly_modulation/manifest.py`

## Phase 5: User Story 3 - Export Decision Tables

- [x] T010 [P] [US3] Write integration CLI test in `tests/integration/test_cli.py`
- [x] T011 [US3] Implement CSV and HTML report writing in `src/solar_monthly_modulation/report.py`
- [x] T012 [US3] Implement CLI contract in `src/solar_monthly_modulation/cli.py` and `src/solar_monthly_modulation/__main__.py`

## Phase 6: Polish

- [x] T013 Add README and quickstart documentation in `README.md`
- [x] T014 Run focused tests and verify no existing source files were modified

## Dependencies

User Story 1 is the MVP and depends on foundational adapters. User Story 2 and User Story 3 build on the calculation result model but are otherwise independently testable.
