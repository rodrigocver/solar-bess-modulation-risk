"""Entry point: ``python -m solar_bess_risk``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from solar_bess_risk import __version__
from solar_bess_risk.cli import prompt_heatmap_scenario, run_session
from solar_bess_risk.data_sources import DataSourceError, fetch_price_bigquery
from solar_bess_risk.economics import ScenarioResult, compute_payback_sensitivity, compute_scenario_result
from solar_bess_risk.manifest import RunManifest, generate_run_id, hash_params, write_manifest
from solar_bess_risk.profile import generate_synthetic_profile, load_solar_csv
from solar_bess_risk.report_charts import (
    build_dispatch_heatmap,
    build_operation_distribution,
    build_payback_sensitivity as build_payback_chart,
    build_saturation_curve,
)
from solar_bess_risk.report_export import (
    build_summary_table_html,
    build_topup_summary_table_html,
    write_report,
)
from solar_bess_risk.simulation import simulate_all_scenarios


BANNER = f"""\
Solar+BESS Modulation Risk Analysis Tool v{__version__}
Normalizado para 1 MWac | Resultados em BRL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solar_bess_risk",
        description="Solar+BESS Modulation Risk Analysis Tool",
    )
    parser.add_argument(
        "--service-account",
        type=str,
        default=None,
        help="Path to GCP service account JSON key file for BigQuery auth",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main() -> None:
    """Run the full analysis pipeline."""
    parser = _build_parser()
    args = parser.parse_args()
    print(BANNER)

    # 1. Interactive parameter prompting
    print("\n[1/7] Configuração de parâmetros...")
    params = run_session(service_account_path=args.service_account)

    # 2. Load solar profile
    print("\n[2/7] Carregando perfil solar...")
    if hasattr(params, "_solar_csv_path") and params._solar_csv_path:
        solar = load_solar_csv(params._solar_csv_path)
    else:
        solar = generate_synthetic_profile(params)
    print(f"  Perfil: {solar.source} | Energia anual: {solar.annual_energy_mwh:.1f} MWh")

    # 3. Fetch prices from BigQuery
    print("\n[3/7] Obtendo preços PLD do BigQuery...")
    try:
        prices = fetch_price_bigquery(params)
    except DataSourceError as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"  Fonte: BigQuery PLD {params.bq_submarket} {params.bq_year}")
    print(f"  Preço médio: {float(np.mean(prices.prices_brl_per_mwh)):.2f} BRL/MWh")

    # 4. Simulate all scenarios
    print(f"\n[4/7] Simulando {params.total_scenarios} cenários...")

    def _progress(current: int, total: int, label: str) -> None:
        print(f"  [{current}/{total}] {label}")

    sim_results = simulate_all_scenarios(params, solar, prices, _progress)
    print(f"  {len(sim_results)} cenários simulados com sucesso.")

    # 5. Compute economics
    print("\n[5/7] Calculando métricas econômicas...")
    scenario_results: list[ScenarioResult] = []
    for bess_cfg, dispatch in sim_results:
        sr = compute_scenario_result(bess_cfg, dispatch, prices, params)
        scenario_results.append(sr)

    # 6. Build charts and report
    print("\n[6/7] Gerando relatório HTML...")

    # Prompt for heatmap scenario
    heatmap_idx = prompt_heatmap_scenario(scenario_results)
    heatmap_bess_cfg, heatmap_dispatch = sim_results[heatmap_idx]

    # Payback sensitivity for the selected scenario
    base_price = float(np.mean(prices.prices_brl_per_mwh))
    sensitivity = compute_payback_sensitivity(scenario_results[heatmap_idx], prices, params)

    figures = [
        build_saturation_curve(scenario_results),
        build_dispatch_heatmap(heatmap_dispatch, heatmap_bess_cfg),
        build_payback_chart(sensitivity, params, base_price),
        build_operation_distribution(heatmap_dispatch),
    ]

    table_html = build_summary_table_html(scenario_results)
    topup_html = build_topup_summary_table_html(scenario_results, prices)

    run_id = generate_run_id()
    output_dir = Path("output") / run_id

    report_path = write_report(figures, table_html, topup_html, scenario_results, params, output_dir)

    # 7. Write manifest
    print("\n[7/7] Escrevendo manifesto...")
    manifest = RunManifest(
        tool_version=__version__,
        run_id=run_id,
        timestamp_iso8601=run_id[:15],  # approximation; manifest writer uses real timestamp
        params_sha256=hash_params(params),
        rng_seed=params.rng_seed,
        profile_source=solar.source,
        price_source=f"bigquery_pld_{params.bq_submarket}_{params.bq_year}",
        scenario_top_up_hours={},
    )
    manifest_path = write_manifest(manifest, scenario_results, output_dir)

    print(f"\n{'━' * 50}")
    print(f"Relatório: {report_path}")
    print(f"Manifesto: {manifest_path}")
    print(f"{'━' * 50}")
    print("Concluído!")


if __name__ == "__main__":
    main()
