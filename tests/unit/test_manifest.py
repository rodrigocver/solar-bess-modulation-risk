"""Unit tests for solar_bess_risk.manifest — run-ID, SHA-256, manifest JSON (v2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from solar_bess_risk.config import SimulationParams
from solar_bess_risk.manifest import RunManifest, generate_run_id, hash_params, write_manifest


@pytest.fixture
def sample_params() -> SimulationParams:
    return SimulationParams(
        csv_path="/tmp/test.csv",
        mwac=100.0,
        bq_year=2025,
        bq_submarket="SE",
        capex_usd_per_kwh=200.0,
        usd_brl_rate=5.0,
        useful_life_years=20,
        bq_service_account_path="/tmp/secret.json",
    )


class TestGenerateRunId:
    """Run-ID format: YYYYMMDD-HHMMSS-<7-char hex>."""

    def test_run_id_format(self):
        run_id = generate_run_id()
        pattern = r"^\d{8}-\d{6}-[0-9a-f]{7}$"
        assert re.match(pattern, run_id), f"Run ID '{run_id}' does not match pattern"

    def test_run_id_contains_hex_suffix(self):
        run_id = generate_run_id()
        hex_part = run_id.split("-")[-1]
        assert len(hex_part) == 7
        int(hex_part, 16)  # must not raise


class TestHashParams:
    """SHA-256 of json.dumps(params, sort_keys=True) is deterministic."""

    def test_hash_is_deterministic(self, sample_params: SimulationParams):
        h1 = hash_params(sample_params)
        h2 = hash_params(sample_params)
        assert h1 == h2

    def test_hash_is_64_hex_chars(self, sample_params: SimulationParams):
        h = hash_params(sample_params)
        assert len(h) == 64
        int(h, 16)  # must not raise

    def test_hash_excludes_bq_service_account_path(self):
        """bq_service_account_path must NOT affect the hash."""
        p1 = SimulationParams(
            csv_path="/tmp/test.csv",
            mwac=100.0,
            bq_service_account_path=None,
        )
        p2 = SimulationParams(
            csv_path="/tmp/test.csv",
            mwac=100.0,
            bq_service_account_path="/tmp/key2.json",
        )
        assert hash_params(p1) == hash_params(p2)

    def test_two_identical_calls_produce_same_sha256(self):
        """Two calls with identical inputs produce identical SHA-256."""
        p = SimulationParams(csv_path="/x.csv", mwac=50.0)
        assert hash_params(p) == hash_params(p)


class TestWriteManifest:
    """write_manifest creates output/<run-id>/manifest.json with all required fields."""

    def _make_manifest(self, sample_params: SimulationParams) -> RunManifest:
        return RunManifest(
            tool_version="2.0.0",
            run_id=generate_run_id(),
            timestamp_iso8601="2026-05-18T14:30:05-03:00",
            params_sha256=hash_params(sample_params),
            profile_source="test.csv",
            price_source="bigquery_pld_SE_2025",
            fc=0.25,
            garantia_fisica_mw=25.0,
            scenarios=[
                {"label": "A", "peak_hours": [18, 19], "duration_h": 2,
                 "bess_power_mw": 25.0, "bess_energy_mwh": 50.0, "capex_brl": 50_000_000.0},
                {"label": "B", "peak_hours": [17, 18, 19], "duration_h": 3,
                 "bess_power_mw": 25.0, "bess_energy_mwh": 75.0, "capex_brl": 75_000_000.0},
                {"label": "C", "peak_hours": [17, 18, 19, 20], "duration_h": 4,
                 "bess_power_mw": 25.0, "bess_energy_mwh": 100.0, "capex_brl": 100_000_000.0},
            ],
            params={"mwac": sample_params.mwac, "bq_submarket": sample_params.bq_submarket},
            price_sources_by_year={"2025": "bigquery_pld_SE_2025"},
            backtest_years=[2025, 2026],
            acumulado_years=[2021, 2022, 2023, 2024, 2025, 2026],
            curtailment={"enabled": False, "source": None},
            rte={
                "path": "dados/11 - Envision.xlsx",
                "table": {"2025": 0.8625},
                "acumulado_rte": 0.85,
                "metadata": {
                    "rte_source_file": "11 - Envision.xlsx",
                    "typical_block_mwh": 10.1,
                    "pcs_mva": 2.52,
                },
            },
        )

    def test_manifest_contains_all_required_fields(self, sample_params, tmp_path):
        manifest = self._make_manifest(sample_params)
        output_dir = tmp_path / manifest.run_id
        manifest_path = write_manifest(manifest, output_dir)
        data = json.loads(manifest_path.read_text())

        required = [
            "tool_version", "run_id", "timestamp_iso8601", "params_sha256",
            "profile_source", "price_source", "fc", "garantia_fisica_mw", "scenarios",
        ]
        for field in required:
            assert field in data, f"Missing required field: {field}"

    def test_bq_service_account_path_entirely_absent(self, sample_params, tmp_path):
        """bq_service_account_path must NOT appear in manifest.json at all (not even as null)."""
        manifest = self._make_manifest(sample_params)
        output_dir = tmp_path / manifest.run_id
        manifest_path = write_manifest(manifest, output_dir)
        raw = manifest_path.read_text()
        assert "bq_service_account_path" not in raw
        assert "service_account" not in raw

    def test_scenarios_is_list_of_3_dicts(self, sample_params, tmp_path):
        manifest = self._make_manifest(sample_params)
        output_dir = tmp_path / manifest.run_id
        manifest_path = write_manifest(manifest, output_dir)
        data = json.loads(manifest_path.read_text())

        assert isinstance(data["scenarios"], list)
        assert len(data["scenarios"]) == 3
        for s in data["scenarios"]:
            for key in ("label", "peak_hours", "duration_h", "bess_power_mw", "bess_energy_mwh", "capex_brl"):
                assert key in s

    def test_manifest_contains_reproducibility_context(self, sample_params, tmp_path):
        manifest = self._make_manifest(sample_params)
        manifest_path = write_manifest(manifest, tmp_path / manifest.run_id)
        data = json.loads(manifest_path.read_text())

        assert data["params"]["bq_submarket"] == "SE"
        assert data["price_sources_by_year"]["2025"] == "bigquery_pld_SE_2025"
        assert data["backtest_years"] == [2025, 2026]
        assert data["acumulado_years"] == [2021, 2022, 2023, 2024, 2025, 2026]
        assert data["curtailment"]["enabled"] is False
        assert data["rte"]["metadata"]["typical_block_mwh"] == 10.1
        assert data["rte"]["metadata"]["pcs_mva"] == 2.52

    def test_two_runs_identical_inputs_same_sha256(self):
        """Two calls with identical inputs produce identical SHA-256."""
        p = SimulationParams(csv_path="/x.csv", mwac=50.0)
        assert hash_params(p) == hash_params(p)
