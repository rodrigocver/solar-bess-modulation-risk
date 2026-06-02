"""Command-line interface for monthly PLD solar modulation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_monthly_modulation.constants import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PLD_BASE_DIR,
    DEFAULT_SUBMARKET,
    DEFAULT_YEARS,
)
from solar_monthly_modulation.errors import MonthlyModulationError  # noqa: E402
from solar_monthly_modulation.models import ModulationConfig  # noqa: E402
from solar_monthly_modulation.modulation import run_modulation  # noqa: E402
from solar_monthly_modulation.report import write_outputs  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build the monthly modulation CLI parser.

    Returns
    -------
    argparse.ArgumentParser
        Configured command-line parser.
    """

    parser = argparse.ArgumentParser(
        description="Calcula modulação mensal solar sem BESS contra PLD histórico."
    )
    parser.add_argument("--csv-path", required=True, help="CSV de geração solar sem BESS.")
    parser.add_argument("--mwac", required=True, type=float, help="Capacidade AC da usina em MWac.")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=list(DEFAULT_YEARS),
        help="Anos históricos de PLD.",
    )
    parser.add_argument("--submarket", default=DEFAULT_SUBMARKET, help="Submercado CCEE.")
    parser.add_argument(
        "--pld-base-dir",
        default=DEFAULT_PLD_BASE_DIR,
        help="Diretório com arquivos pld_horario_<ano>.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Diretório base para outputs.",
    )
    parser.add_argument(
        "--bq-service-account-path",
        default=None,
        help="JSON de service account para buscar PLD observado no BigQuery.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Parameters
    ----------
    argv : list[str] or None
        Optional argument vector; uses process arguments when omitted.

    Returns
    -------
    int
        Process exit code: 0 success, 2 validation failure, 1 unexpected failure.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    config = ModulationConfig(
        csv_path=args.csv_path,
        mwac=args.mwac,
        years=tuple(args.years),
        submarket=args.submarket.upper(),
        pld_base_dir=args.pld_base_dir,
        output_dir=args.output_dir,
        bq_service_account_path=args.bq_service_account_path,
    )

    try:
        result = run_modulation(config)
        outputs = write_outputs(config, result)
    except MonthlyModulationError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERRO inesperado: {exc}", file=sys.stderr)
        return 1

    print(f"Resultado mensal: {outputs.monthly_csv}")
    print(f"Resumo anual: {outputs.annual_csv}")
    print(f"Relatório HTML: {outputs.html_report}")
    print(f"Manifesto: {outputs.manifest_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
