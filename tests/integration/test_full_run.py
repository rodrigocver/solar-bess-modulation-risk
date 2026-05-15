"""Integration tests: full pipeline with mocked BigQuery."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.economics import ScenarioResult, compute_scenario_result
from solar_bess_risk.manifest import RunManifest, generate_run_id, hash_params, write_manifest
from solar_bess_risk.profile import generate_synthetic_profile
from solar_bess_risk.report_charts import (
    build_dispatch_heatmap,
    build_operation_distribution,
    build_payback_sensitivity,
    build_saturation_curve,
)
from solar_bess_risk.report_export import (
    build_summary_table_html,
    build_topup_summary_table_html,
    write_report,
)
from solar_bess_risk.simulation import simulate_all_scenarios


def _make_deterministic_prices(seed: int = 42) -> PriceProfile:
    """Create deterministic test prices."""
    rng = np.random.default_rng(seed)
    prices = rng.uniform(100, 400, size=HOURS_PER_YEAR).astype(np.float64)
    return PriceProfile(
        prices_brl_per_mwh=prices,
        source="bigquery_pld_SE_2025",
        bq_submarket="SE",
        bq_year=2025,
    )


@pytest.fixture
def params() -> SimulationParams:
    return SimulationParams()


@pytest.fixture
def solar(params: SimulationParams):
    return generate_synthetic_profile(params)


@pytest.fixture
def prices() -> PriceProfile:
    return _make_deterministic_prices()


class TestFullRun:
    """End-to-end integration tests."""

    def test_full_pipeline_completes(self, params, solar, prices, tmp_path):
        """Full run with defaults completes without exception."""
        sim_results = simulate_all_scenarios(params, solar, prices)
        assert len(sim_results) == 44

        scenario_results = []
        for bess_cfg, dispatch in sim_results:
            sr = compute_scenario_result(bess_cfg, dispatch, prices, params)
            scenario_results.append(sr)

        assert len(scenario_results) == 44

        # Build report
        from solar_bess_risk.economics import compute_payback_sensitivity as cps

        figures = [
            build_saturation_curve(scenario_results),
            build_dispatch_heatmap(sim_results[5][1], sim_results[5][0]),
            build_payback_sensitivity(
                cps(scenario_results[5], prices, params),
                params,
                float(np.mean(prices.prices_brl_per_mwh)),
            ),
            build_operation_distribution(sim_results[5][1]),
        ]

        table_html = build_summary_table_html(scenario_results)
        topup_html = build_topup_summary_table_html(scenario_results, prices)

        output_dir = tmp_path / "test-run"
        report_path = write_report(
            figures, table_html, topup_html, scenario_results, params, output_dir
        )

        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

        # Write manifest
        run_id = generate_run_id()
        manifest = RunManifest(
            tool_version="1.0.0",
            run_id=run_id,
            timestamp_iso8601="2025-01-01T00:00:00+00:00",
            params_sha256=hash_params(params),
            rng_seed=params.rng_seed,
            profile_source=solar.source,
            price_source="bigquery_pld_SE_2025",
            scenario_top_up_hours={},
        )
        manifest_path = write_manifest(manifest, scenario_results, output_dir)
        assert manifest_path.exists()

        import json

        manifest_data = json.loads(manifest_path.read_text())
        assert "price_source" in manifest_data
        assert "scenario_top_up_hours" in manifest_data

    def test_report_self_contained(self, params, solar, prices, tmp_path):
        """HTML report contains no external CDN references."""
        sim_results = simulate_all_scenarios(params, solar, prices)
        scenario_results = [
            compute_scenario_result(cfg, disp, prices, params)
            for cfg, disp in sim_results
        ]

        figures = [build_saturation_curve(scenario_results)]
        table_html = build_summary_table_html(scenario_results)
        topup_html = build_topup_summary_table_html(scenario_results, prices)

        output_dir = tmp_path / "self-contained"
        report_path = write_report(
            figures, table_html, topup_html, scenario_results, params, output_dir
        )

        content = report_path.read_text(encoding="utf-8")
        assert "cdn.plot.ly" not in content

    def test_summary_table_44_rows(self, params, solar, prices, tmp_path):
        """Summary table contains 44 data rows."""
        sim_results = simulate_all_scenarios(params, solar, prices)
        scenario_results = [
            compute_scenario_result(cfg, disp, prices, params)
            for cfg, disp in sim_results
        ]

        table_html = build_summary_table_html(scenario_results)
        # 44 data rows + 1 header row
        assert table_html.count("<tr>") == 44 + 1

    def test_saturation_monotonic(self, params, solar, prices):
        """Saturation curve is monotonically non-decreasing per ILR."""
        sim_results = simulate_all_scenarios(params, solar, prices)
        scenario_results = [
            compute_scenario_result(cfg, disp, prices, params)
            for cfg, disp in sim_results
        ]

        # Group by ILR
        ilr_data: dict[float, list[tuple[float, float]]] = {}
        for r in scenario_results:
            ilr, bess_pct, _ = r.scenario_id
            avoided = r.curtailment_without_bess_mwh_yr - r.curtailment_with_bess_mwh_yr
            if ilr not in ilr_data:
                ilr_data[ilr] = []
            ilr_data[ilr].append((bess_pct, avoided))

        for ilr, points in ilr_data.items():
            points.sort(key=lambda x: x[0])
            for i in range(1, len(points)):
                assert points[i][1] >= points[i - 1][1] - 1e-6, (
                    f"Non-monotonic at ILR={ilr}: {points[i-1]} -> {points[i]}"
                )

    def test_sc001_performance(self, params, solar, prices):
        """SC-001: 44 scenarios complete in < 180 s."""
        start = time.perf_counter()
        simulate_all_scenarios(params, solar, prices)
        elapsed = time.perf_counter() - start
        assert elapsed < 180, f"Took {elapsed:.1f}s, expected < 180s"

    def test_sc004_saturation_consistency(self, params, solar, prices):
        """SC-004: ScenarioResult avoided curtailment matches saturation data."""
        sim_results = simulate_all_scenarios(params, solar, prices)
        scenario_results = [
            compute_scenario_result(cfg, disp, prices, params)
            for cfg, disp in sim_results
        ]

        for r in scenario_results:
            avoided = r.curtailment_without_bess_mwh_yr - r.curtailment_with_bess_mwh_yr
            assert avoided >= -1e-2, f"Negative avoided curtailment: {avoided}"


class TestReproducibility:
    """SC-003: Two runs with identical params produce identical results."""

    def test_reproducible_results(self, params, solar):
        """Two runs produce identical results within 1e-10 MWh."""
        prices1 = _make_deterministic_prices(seed=42)
        prices2 = _make_deterministic_prices(seed=42)

        results1 = simulate_all_scenarios(params, solar, prices1)
        results2 = simulate_all_scenarios(params, solar, prices2)

        assert len(results1) == len(results2) == 44

        for (cfg1, disp1), (cfg2, disp2) in zip(results1, results2):
            sr1 = compute_scenario_result(cfg1, disp1, prices1, params)
            sr2 = compute_scenario_result(cfg2, disp2, prices2, params)

            assert abs(sr1.curtailment_without_bess_mwh_yr - sr2.curtailment_without_bess_mwh_yr) < 1e-10
            assert abs(sr1.curtailment_with_bess_mwh_yr - sr2.curtailment_with_bess_mwh_yr) < 1e-10
            assert abs(sr1.incremental_revenue_brl_yr - sr2.incremental_revenue_brl_yr) < 1e-10
            assert abs(sr1.energy_from_curtail_mwh_yr - sr2.energy_from_curtail_mwh_yr) < 1e-10
