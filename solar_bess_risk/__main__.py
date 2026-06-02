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
from solar_bess_risk.data_sources import (
    DataSourceError,
    PriceProfile,
    fetch_price_bigquery,
    load_price_local_pld,
)
from solar_bess_risk.manifest import RunManifest, generate_run_id, hash_params, write_manifest
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.projection import project_cashflows_with_rte
from solar_bess_risk.report_excel import build_excel_report, build_html_report
from solar_bess_risk.rte import get_rte_metadata, load_rte_table
from solar_bess_risk.risk_metrics import compute_historical_risk_metrics
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
        charge_power_mw=bess_power,
        peak_hour_weights=template.peak_hour_weights,
        rte=rte,
        charge_mode=charge_mode,
    )


def _fetch_pld_for_year(year: int, params: SimulationParams) -> PriceProfile:
    """Load PLD for a given year, using local history and BigQuery only for 2026."""
    year_params = replace(params, bq_year=year)

    if 2021 <= year <= 2025:
        return load_price_local_pld(year, params.bq_submarket)

    if year == 2026:
        from solar_bess_risk.backtest import (
            _fetch_observed_primary_series,
            _project_partial_year_prices,
        )
        print("    2026: buscando PLD observado no BigQuery...")
        observed = _fetch_observed_primary_series(year_params)
        print(
            f"    2026: {len(observed)} horas observadas; "
            "completando ano com base local 2025."
        )
        base_profile = load_price_local_pld(2025, params.bq_submarket)
        result = _project_partial_year_prices(
            observed,
            base_profile,
            target_year=2026,
            base_year=2025,
            submarket=params.bq_submarket,
        )
        print(
            f"    2026: série final com "
            f"{result.metadata.observed_hours} horas observadas + "
            f"{result.metadata.projected_hours} horas projetadas "
            f"(fator={result.metadata.projection_factor:.4f})."
        )
        return result.profile

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
        _dispatch, _pld, gf, _gen, peak_hours, duration_h, _year_label, rte = data[:8]
        scenario = data[8] if len(data) > 8 else None
        if duration_h not in scenario_map:
            bess_power = scenario.bess_power_mw if scenario is not None else gf
            bess_energy = scenario.bess_energy_mwh if scenario is not None else gf * duration_h
            charge_power = (
                scenario.charge_power_mw or scenario.bess_power_mw
                if scenario is not None else bess_power
            )
            capex_brl = (
                scenario.capex_brl
                if scenario is not None
                else bess_energy * 1000 * CAPEX_USD_PER_KWH[duration_h] * params.usd_brl_rate
            )
            scenario_map[duration_h] = {
                "label": next(t.label for t in SCENARIO_TEMPLATES if t.duration_h == duration_h),
                "duration_h": duration_h,
                "peak_hours": sorted(peak_hours),
                "bess_power_mw": bess_power,
                "charge_power_mw": charge_power,
                "bess_energy_mwh": bess_energy,
                "capex_usd_per_kwh": CAPEX_USD_PER_KWH[duration_h],
                "capex_brl": capex_brl,
                "rte_sample": rte,
            }

    return RunManifest(
        tool_version=__version__,
        run_id=run_id,
        timestamp_iso8601=datetime.now(timezone.utc).isoformat(),
        params_sha256=hash_params(params),
        profile_source=solar.csv_filename,
        price_source=f"local_pld_2021_2025_plus_bigquery_{params.bq_submarket}_2026",
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
            "lcoe_discount_rate": params.lcoe_discount_rate,
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
        print(
            "Uso: python -m solar_bess_risk [--service-account PATH] "
            "[--quick-test] [--skip-excel] [--director-only]"
        )
        print("\nFerramenta de backtest solar + BESS com output HTML.")
        print("  --skip-excel    Não gera backtest_completo.xlsx.")
        print("  --director-only Gera apenas relatorio_diretoria.html + manifest.")
        sys.exit(0)

    # Parse optional flags
    sa_path = None
    if "--service-account" in sys.argv:
        idx = sys.argv.index("--service-account")
        if idx + 1 < len(sys.argv):
            sa_path = sys.argv[idx + 1]

    quick_test = "--quick-test" in sys.argv
    skip_excel = "--skip-excel" in sys.argv or "--director-only" in sys.argv
    director_only = "--director-only" in sys.argv
    risk_max_solar_years = 3 if quick_test else None

    # 1. Interactive parameter collection
    if quick_test:
        params = SimulationParams(csv_path="solar/solar_baguacu_m2_600mw_id2.csv", mwac=600.0)
        curtailment_enabled = True
        rte_path = "dados/11 - Envision.xlsx"
        charge_mode = 3
        print("  Modo quick-test: risco histórico limitado a 3 anos solares.")
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
    print("[2/5] Carregando preços PLD...")
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
        # ONS curtailment is scaled by sem-BESS generation (gen_lim)
        _gen_lim = solar.generation_lim_mw if solar.generation_lim_mw is not None else solar.generation_mw
        curt_series = get_curtailment_for_scenario(year, curtailment_enabled, _gen_lim)
        pld = pld_by_year[year]
        rte_year = rte_table.get(year, rte_fallback)

        for dur in DURATIONS:
            scenario = _get_scenario_for_duration(dur, gf, params.usd_brl_rate, rte=rte_year, charge_mode=charge_mode)
            tab_name = f"{year}-{dur}h"
            print(f"  {tab_name} (RTE={rte_year:.4f})...")

            price_source = price_sources_by_year.get(year, f"pld_{params.bq_submarket}_{year}")
            price_profile = PriceProfile(
                pld,
                price_source,
                params.bq_submarket,
                year,
            )
            dispatch = simulate_scenario(
                solar,
                price_profile,
                scenario, params, curtailment_series=curt_series,
            )
            projection = project_cashflows_with_rte(
                solar=solar,
                pld=pld,
                price_source=price_source,
                bq_submarket=params.bq_submarket,
                scenario=scenario,
                params=params,
                curtailment_series=curt_series,
                rte_table=rte_table,
                start_year=year,
            )
            risk_metrics = compute_historical_risk_metrics(
                solar=solar,
                prices=price_profile,
                scenario=scenario,
                params=params,
                curtailment_series=curt_series,
                max_solar_years=risk_max_solar_years,
            )
            results_by_key[tab_name] = (
                dispatch, pld, gf, solar.generation_lim_mw if solar.generation_lim_mw is not None else solar.generation_mw,
                scenario.peak_hours, dur, year, rte_year, scenario, projection, risk_metrics,
            )

    # Accumulated scenarios
    _gen_lim_acum = solar.generation_lim_mw if solar.generation_lim_mw is not None else solar.generation_mw
    curt_acum = get_curtailment_for_scenario(2025, curtailment_enabled, _gen_lim_acum)  # proxy
    for dur in DURATIONS:
        scenario = _get_scenario_for_duration(dur, gf, params.usd_brl_rate, rte=rte_acum, charge_mode=charge_mode)
        tab_name = f"Acum-{dur}h"
        print(f"  {tab_name} (RTE={rte_acum:.4f})...")

        acum_source = f"mixed_pld_{params.bq_submarket}_acum_2021_2026"
        price_profile = PriceProfile(
            acum_pld,
            acum_source,
            params.bq_submarket,
            2001,
        )
        dispatch = simulate_scenario(
            solar,
            price_profile,
            scenario, params, curtailment_series=curt_acum,
        )
        projection = project_cashflows_with_rte(
            solar=solar,
            pld=acum_pld,
            price_source=acum_source,
            bq_submarket=params.bq_submarket,
            scenario=scenario,
            params=params,
            curtailment_series=curt_acum,
            rte_table=rte_table,
            start_year=min(rte_table) if rte_table else 2025,
        )
        risk_metrics = compute_historical_risk_metrics(
            solar=solar,
            prices=price_profile,
            scenario=scenario,
            params=params,
            curtailment_series=curt_acum,
            max_solar_years=risk_max_solar_years,
        )
        results_by_key[tab_name] = (
            dispatch, acum_pld, gf, solar.generation_lim_mw if solar.generation_lim_mw is not None else solar.generation_mw,
            scenario.peak_hours, dur, 2001, rte_acum, scenario, projection, risk_metrics,
        )

    # 5. Generate reports (HTML + Excel + Consultancy report)
    print("[4/6] Gerando relatórios...")
    run_id = generate_run_id()
    project_slug = Path(params.csv_path).stem
    output_dir = Path("output") / project_slug / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path: str | None = None
    if not director_only:
        report_path = build_html_report(
            results_by_key,
            output_dir / "report.html",
            mwac=params.mwac, usd_brl_rate=params.usd_brl_rate,
            bq_submarket=params.bq_submarket,
            charge_mode=charge_mode,
            rte_metadata=rte_metadata,
        )
        print(f"  HTML: {report_path}")
    else:
        print("  HTML principal: pulado (--director-only)")

    excel_path: str | None = None
    if not skip_excel:
        excel_path = build_excel_report(
            results_by_key,
            output_dir / "backtest_completo.xlsx",
            mwac=params.mwac,
            usd_brl_rate=params.usd_brl_rate,
            charge_mode=charge_mode,
        )
        print(f"  Excel: {excel_path}")
    else:
        print("  Excel: pulado (--skip-excel/--director-only)")

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
    print(f"  HTML: {report_path if report_path is not None else 'n/a'}")
    print(f"  Excel: {excel_path if excel_path is not None else 'n/a'}")
    print(f"  Relatório Diretoria: {consultancy_path}")
    print(f"  Run ID: {run_id}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
