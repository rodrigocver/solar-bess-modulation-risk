# CLI Contract: Monthly PLD Solar Modulation

## Command

```text
solar-monthly-modulation --csv-path PATH --mwac MWAC [--years YEAR ...] [--submarket CODE] [--pld-base-dir DIR] [--output-dir DIR]
```

## Arguments

| Argument | Required | Default | Description |
|---|---:|---|---|
| `--csv-path` | yes | none | Solar generation CSV without BESS |
| `--mwac` | yes | none | Plant AC capacity in MWac |
| `--years` | no | `2021 2022 2023 2024 2025` | Historical PLD years |
| `--submarket` | no | `SE` | CCEE submarket code |
| `--pld-base-dir` | no | `dados/pld` | Directory containing `pld_horario_<year>.csv` |
| `--output-dir` | no | `output/monthly_modulation` | Base output directory |

## Success

- Prints the run output directory.
- Writes `monthly_modulation.csv`, `annual_summary.csv`, and `manifest.json`.
- Exits with code 0.

## Failure

- Prints a human-readable structured error.
- Exits with code 2 for validation/calculation errors.
- Exits with code 1 for unexpected errors.
