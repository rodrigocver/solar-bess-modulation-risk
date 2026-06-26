# Data Model: Monthly PLD Solar Modulation

## ModulationConfig

- `csv_path`: source solar generation CSV path
- `mwac`: plant AC capacity in MWac
- `years`: requested PLD years
- `submarket`: CCEE submarket code
- `output_dir`: base output directory
- `pld_base_dir`: local PLD directory

Validation:

- `mwac` must be positive.
- `years` must not be empty.
- `submarket` must be one of SE, S, NE, N.

## MonthlyModulationRow

- `year`
- `month`
- `hours`
- `generation_mwh`
- `flat_price_brl_per_mwh`
- `captured_price_brl_per_mwh`
- `weighted_revenue_brl`
- `modulation_factor`
- `generation_per_mwac_mwh_per_mwac`
- `price_source`

Validation:

- `generation_mwh` must be positive.
- `flat_price_brl_per_mwh` must be positive.
- `modulation_factor` must be finite.

## AnnualSummaryRow

- `year`
- `generation_mwh`
- `flat_price_brl_per_mwh`
- `captured_price_brl_per_mwh`
- `weighted_revenue_brl`
- `modulation_factor`
- `generation_per_mwac_mwh_per_mwac`
- `price_source`

## RunManifest

- `tool_version`
- `created_at`
- `configuration`
- `input_hashes`
- `formulas`
- `outputs`
- `source_labels`
