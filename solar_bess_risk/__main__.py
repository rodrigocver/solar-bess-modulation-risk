"""Entry point: python -m solar_bess_risk."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from solar_bess_risk import __version__
from solar_bess_risk.cli import run_session
from solar_bess_risk.config import (
    ACUMULADO_YEARS,
    BACKTEST_YEARS,
    BESS_BLOCK_SPECS,
    CAPEX_USD_PER_KWH,
    DURATIONS,
    HOURS_PER_YEAR,
    SCENARIO_TEMPLATES,
    SimulationParams,
)
from solar_bess_risk.curtailment import get_curtailment_for_scenario
from solar_bess_risk.data_sources import DataSourceError, PriceProfile, fetch_price_bigquery
from solar_bess_risk.manifest import RunManifest, generate_run_id, hash_params, write_manifest
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.report_excel import build_excel_report, build_html_report
from solar_bess_risk.rte import get_rte_metadata, load_rte_table
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario


def _get_scenario_for_duration(
    duration_h: int, gf: float, usd_brl_rate: float, rte: float = 1.0, charge_mode: int = 0
) -> ScenarioDefinition:
    """Build a ScenarioDefinition for a given duration using block-based sizing.

    BESS is sized as multiples of typical blocks:
      - 2h: 4.54 MW / 10.1 MWh per block
      - 4h: 2.52 MW / 10.1 MWh per block

    Number of blocks = ceil(garantia_fisica / block_power).
    """
    import math

    template = next(t for t in SCENARIO_TEMPLATES if t.duration_h == duration_h)
    block = BESS_BLOCK_SPECS[duration_h]

    n_blocks = math.ceil(gf / block.block_power_mw)
    bess_power = n_blocks * block.block_power_mw
    bess_energy = n_blocks * block.block_energy_mwh

    capex_usd = bess_energy * 1000 * CAPEX_USD_PER_KWH[duration_h]
    capex_brl = capex_usd * usd_brl_rate

    return ScenarioDefinition(
        label=template.label,
        peak_hours=template.peak_hours,
        duration_h=duration_h,
        bess_power_mw=bess_power,
        bess_energy_mwh=bess_energy,
        capex_brl=capex_brl,
        peak_hour_weights=template.peak_hour_weights,
        rte=rte,
        charge_mode=charge_mode,
    )


def _fetch_pld_for_year(year: int, params: SimulationParams) -> PriceProfile:
    """Fetch PLD for a given year (with projection for 2026)."""
    year_params = replace(params, bq_year=year)

    if year == 2026:
        # Use projection logic from backtest module
        from solar_bess_risk.backtest import fetch_backtest_prices
        result = fetch_backtest_prices(
            year_params,
            projection_year=2026,
            projection_base_year=2025,
        )
        return result.profile
    else:
        return fetch_price_bigquery(year_params)


def _compute_acumulado_pld(
    pld_by_year: dict[int, np.ndarray],
) -> np.ndarray:
    """Compute mean PLD hour-by-hour across all acumulado years.

    PLD 2024 must have 29/Feb removed before calling this function.
    """
    arrays = [pld_by_year[y] for y in sorted(pld_by_year.keys())]
    stacked = np.stack(arrays, axis=0)
    return stacked.mean(axis=0)


def _build_run_manifest(
    *,
    run_id: str,
    params: SimulationParams,
    solar,
    results_by_key: dict[str, tuple],
    price_sources_by_year: dict[int, str],
    rte_path: str,
    rte_table: dict[int, float],
    rte_acum: float,
    curtailment_enabled: bool,
    rte_metadata: dict[str, float | str] | None,
) -> RunManifest:
    """Build a reproducible manifest from the executed run inputs."""
    scenario_map: dict[int, dict] = {}
    for data in results_by_key.values():
        _dispatch, _pld, gf, _gen, peak_hours, duration_h, _year_label, rte = data
        if duration_h not in scenario_map:
            bess_energy = gf * duration_h
            scenario_map[duration_h] = {
                "label": next(t.label for t in SCENARIO_TEMPLATES if t.duration_h == duration_h),
                "duration_h": duration_h,
                "peak_hours": sorted(peak_hours),
                "bess_power_mw": gf,
                "bess_energy_mwh": bess_energy,
                "capex_usd_per_kwh": CAPEX_USD_PER_KWH[duration_h],
                "capex_brl": bess_energy * 1000 * CAPEX_USD_PER_KWH[duration_h] * params.usd_brl_rate,
                "rte_sample": rte,
            }

    return RunManifest(
        tool_version=__version__,
        run_id=run_id,
        timestamp_iso8601=datetime.now(timezone.utc).isoformat(),
        params_sha256=hash_params(params),
        profile_source=solar.csv_filename,
        price_source=f"bigquery_pld_{params.bq_submarket}_multi_year",
        fc=solar.fc,
        garantia_fisica_mw=solar.garantia_fisica_mw,
        scenarios=[scenario_map[d] for d in sorted(scenario_map)],
        params={
            "csv_path": params.csv_path,
            "mwac": params.mwac,
            "bq_submarket": params.bq_submarket,
            "usd_brl_rate": params.usd_brl_rate,
            "useful_life_years": params.useful_life_years,
            "bess_o_and_m_pct_capex": params.bess_o_and_m_pct_capex,
            "bess_degradation_pct_yr": params.bess_degradation_pct_yr,
        },
        price_sources_by_year={str(k): v for k, v in sorted(price_sources_by_year.items())},
        backtest_years=BACKTEST_YEARS,
        acumulado_years=ACUMULADO_YEARS,
        curtailment={
            "enabled": curtailment_enabled,
            "source": "dados/media_agregada_horaria_2025_2026.xlsx" if curtailment_enabled else None,
        },
        rte={
            "path": rte_path,
            "table": {str(k): v for k, v in sorted(rte_table.items())},
            "acumulado_rte": rte_acum,
            "metadata": rte_metadata,
        },
    )


def main() -> None:
    """Run the full analysis pipeline."""
    print(f"\n{'='*60}")
    print(f"  Solar BESS Modulation Risk Tool v{__version__}")
    print(f"{'='*60}\n")

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Uso: python -m solar_bess_risk [--service-account PATH] [--quick-test]")
        print("\nFerramenta de backtest solar + BESS com output HTML.")
        sys.exit(0)

    # Parse optional flags
    sa_path = None
    if "--service-account" in sys.argv:
        idx = sys.argv.index("--service-account")
        if idx + 1 < len(sys.argv):
            sa_path = sys.argv[idx + 1]

    quick_test = "--quick-test" in sys.argv

    # 1. Interactive parameter collection
    if quick_test:
        params = SimulationParams(csv_path="solar_baguacu_m2_600mw_id8.csv", mwac=600.0)
        curtailment_enabled = True
        rte_path = "dados/11 - Envision.xlsx"
        charge_mode = 3
    else:
        params, curtailment_enabled, rte_path, charge_mode = run_session(service_account_path=sa_path)

    # 2. Load solar profile
    print("\n[1/5] Carregando perfil solar...")
    solar = load_solar_csv(params.csv_path, params.mwac)
    gf = solar.garantia_fisica_mw

    # Load RTE table (per-year round-trip efficiency)
    try:
        rte_table = load_rte_table(rte_path)
        rte_fallback = rte_table[min(rte_table)]
        print(f"  RTE carregado: {len(rte_table)} anos, 1º ano={rte_fallback:.4f}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  AVISO: RTE não carregado ({e}). Usando params.bess_roundtrip_efficiency.")
        rte_table = {}
        rte_fallback = params.bess_roundtrip_efficiency

    rte_acum = (
        sum(rte_table.values()) / len(rte_table) if rte_table
        else params.bess_roundtrip_efficiency
    )
    rte_metadata = get_rte_metadata(rte_path)

    # 3. Fetch PLD for backtest years + acumulado years
    print("[2/5] Buscando preços PLD no BigQuery...")
    all_years = sorted(set(BACKTEST_YEARS) | set(ACUMULADO_YEARS))
    pld_by_year: dict[int, np.ndarray] = {}
    price_sources_by_year: dict[int, str] = {}

    for year in all_years:
        print(f"  PLD {year}...")
        try:
            prices = _fetch_pld_for_year(year, params)
            pld_by_year[year] = prices.prices_brl_per_mwh
            price_sources_by_year[year] = prices.source
        except DataSourceError as e:
            print(f"\nERRO ao buscar PLD {year}: {e}", file=sys.stderr)
            sys.exit(1)

    # Compute accumulated PLD (mean across 6 years)
    print("  Calculando PLD acumulado (média 2021-2026)...")
    acum_pld = _compute_acumulado_pld(pld_by_year)

    # 4. Simulate all (year × duration) combinations
    print("[3/5] Simulando cenários...")
    results_by_key: dict[str, tuple] = {}

    for year in BACKTEST_YEARS:
        curt_series = get_curtailment_for_scenario(year, curtailment_enabled, solar.generation_mw)
        pld = pld_by_year[year]
        rte_year = rte_table.get(year, rte_fallback)

        for dur in DURATIONS:
            scenario = _get_scenario_for_duration(dur, gf, params.usd_brl_rate, rte=rte_year, charge_mode=charge_mode)
            tab_name = f"{year}-{dur}h"
            print(f"  {tab_name} (RTE={rte_year:.4f})...")

            dispatch = simulate_scenario(
                solar,
                PriceProfile(
                    pld,
                    price_sources_by_year.get(year, f"bigquery_pld_{params.bq_submarket}_{year}"),
                    params.bq_submarket,
                    year,
                ),
                scenario, params, curtailment_series=curt_series,
            )
            results_by_key[tab_name] = (
                dispatch, pld, gf, solar.generation_mw,
                scenario.peak_hours, dur, year, rte_year,
            )

    # Accumulated scenarios
    curt_acum = get_curtailment_for_scenario(2025, curtailment_enabled, solar.generation_mw)  # proxy
    for dur in DURATIONS:
        scenario = _get_scenario_for_duration(dur, gf, params.usd_brl_rate, rte=rte_acum, charge_mode=charge_mode)
        tab_name = f"Acum-{dur}h"
        print(f"  {tab_name} (RTE={rte_acum:.4f})...")

        dispatch = simulate_scenario(
            solar,
            PriceProfile(
                acum_pld,
                f"bigquery_pld_{params.bq_submarket}_acum",
                params.bq_submarket,
                2001,
            ),
            scenario, params, curtailment_series=curt_acum,
        )
        results_by_key[tab_name] = (
            dispatch, acum_pld, gf, solar.generation_mw,
            scenario.peak_hours, dur, 2001, rte_acum,
        )

    # 5. Generate reports (HTML + Excel + Consultancy report)
    print("[4/6] Gerando relatórios...")
    run_id = generate_run_id()
    output_dir = Path("output") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = build_html_report(
        results_by_key,
        output_dir / "report.html",
        mwac=params.mwac, usd_brl_rate=params.usd_brl_rate,
        bq_submarket=params.bq_submarket,
        charge_mode=charge_mode,
        rte_metadata=rte_metadata,
    )

    # Excel with all tabs
    excel_path = build_excel_report(
        results_by_key,
        output_dir / "backtest_completo.xlsx",
        mwac=params.mwac,
        usd_brl_rate=params.usd_brl_rate,
        charge_mode=charge_mode,
    )
    print(f"  Excel: {excel_path}")

    # Consultancy-style HTML report
    from solar_bess_risk.report_consultancy import build_consultancy_report
    consultancy_path = build_consultancy_report(
        results_by_key,
        output_dir / "relatorio_diretoria.html",
        mwac=params.mwac,
        usd_brl_rate=params.usd_brl_rate,
        bq_submarket=params.bq_submarket,
        garantia_fisica_mw=gf,
        fc=solar.fc,
        charge_mode=charge_mode,
        rte_metadata=rte_metadata,
    )
    print(f"  Relatório Diretoria: {consultancy_path}")

    # 6. Write manifest
    print("[5/6] Salvando manifest...")
    manifest = _build_run_manifest(
        run_id=run_id,
        params=params,
        solar=solar,
        results_by_key=results_by_key,
        price_sources_by_year=price_sources_by_year,
        rte_path=rte_path,
        rte_table=rte_table,
        rte_acum=rte_acum,
        curtailment_enabled=curtailment_enabled,
        rte_metadata=rte_metadata,
    )
    write_manifest(manifest, output_dir)

    print(f"\n{'='*60}")
    print(f"  Análise concluída!")
    print(f"  HTML: {report_path}")
    print(f"  Excel: {excel_path}")
    print(f"  Relatório Diretoria: {consultancy_path}")
    print(f"  Run ID: {run_id}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
