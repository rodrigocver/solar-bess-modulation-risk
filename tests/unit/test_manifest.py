"""Unit tests for solar_bess_risk.manifest module.

Tests written FIRST (TDD) — must FAIL until manifest.py is implemented.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import numpy as np
import pytest

from solar_bess_risk.config import SimulationParams


class TestGenerateRunId:
    """Run-ID format: YYYYMMDD-HHMMSS-<7-char hex>."""

    def test_run_id_format(self):
        from solar_bess_risk.manifest import generate_run_id

        run_id = generate_run_id()
        pattern = r"^\d{8}-\d{6}-[0-9a-f]{7}$"
        assert re.match(pattern, run_id), f"Run ID '{run_id}' does not match pattern"

    def test_run_id_contains_hex_suffix(self):
        from solar_bess_risk.manifest import generate_run_id

        run_id = generate_run_id()
        hex_part = run_id.split("-")[-1]
        assert len(hex_part) == 7
        int(hex_part, 16)  # must not raise


class TestHashParams:
    """SHA-256 of json.dumps(params, sort_keys=True) is deterministic."""

    def test_hash_is_deterministic(self):
        from solar_bess_risk.manifest import hash_params

        params = SimulationParams()
        h1 = hash_params(params)
        h2 = hash_params(params)
        assert h1 == h2

    def test_hash_is_64_hex_chars(self):
        from solar_bess_risk.manifest import hash_params

        h = hash_params(SimulationParams())
        assert len(h) == 64
        int(h, 16)  # must not raise

    def test_hash_excludes_bq_service_account_path(self):
        from solar_bess_risk.manifest import hash_params

        p1 = SimulationParams(bq_service_account_path=None)
        p2 = SimulationParams(bq_service_account_path="/some/path.json")
        assert hash_params(p1) == hash_params(p2)


class TestRunManifest:
    """RunManifest dataclass contains all required fields."""

    def test_manifest_has_required_fields(self):
        from solar_bess_risk.manifest import RunManifest

        required = {
            "tool_version",
            "run_id",
            "timestamp_iso8601",
            "params_sha256",
            "rng_seed",
            "profile_source",
            "price_source",
            "scenario_top_up_hours",
        }
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(RunManifest)}
        assert required.issubset(field_names), f"Missing fields: {required - field_names}"

    def test_scenario_top_up_hours_is_dict(self):
        from solar_bess_risk.manifest import RunManifest

        m = RunManifest(
            tool_version="1.0.0",
            run_id="20260515-143005-a1b2c3d",
            timestamp_iso8601="2026-05-15T14:30:05-03:00",
            params_sha256="a" * 64,
            rng_seed=42,
            profile_source="synthetic",
            price_source="bigquery_pld_SE_2025",
            scenario_top_up_hours={"1.3_25.0_2.0": ["00:00", "01:00"]},
        )
        assert isinstance(m.scenario_top_up_hours, dict)

    def test_scenario_top_up_hours_key_format(self):
        """Keys should be '{ilr}_{bess_pct}_{dur_h}'."""
        from solar_bess_risk.manifest import RunManifest

        m = RunManifest(
            tool_version="1.0.0",
            run_id="20260515-143005-a1b2c3d",
            timestamp_iso8601="2026-05-15T14:30:05-03:00",
            params_sha256="a" * 64,
            rng_seed=42,
            profile_source="synthetic",
            price_source="bigquery_pld_SE_2025",
            scenario_top_up_hours={"1.3_25.0_2.0": ["03:00", "04:00"]},
        )
        for key in m.scenario_top_up_hours:
            parts = key.split("_")
            assert len(parts) == 3
            float(parts[0])  # ilr
            float(parts[1])  # bess_pct
            float(parts[2])  # dur_h

    def test_scenario_top_up_hours_values_are_hh00_strings(self):
        from solar_bess_risk.manifest import RunManifest

        m = RunManifest(
            tool_version="1.0.0",
            run_id="20260515-143005-a1b2c3d",
            timestamp_iso8601="2026-05-15T14:30:05-03:00",
            params_sha256="a" * 64,
            rng_seed=42,
            profile_source="synthetic",
            price_source="bigquery_pld_SE_2025",
            scenario_top_up_hours={"1.3_25.0_2.0": ["03:00", "04:00"]},
        )
        for slots in m.scenario_top_up_hours.values():
            assert isinstance(slots, list)
            for s in slots:
                assert re.match(r"^\d{2}:00$", s), f"Invalid HH:00 format: {s}"


class TestWriteManifest:
    """write_manifest creates output/<run-id>/manifest.json with all fields."""

    def test_manifest_json_written(self, tmp_path):
        from solar_bess_risk.manifest import RunManifest, write_manifest

        manifest = RunManifest(
            tool_version="1.0.0",
            run_id="20260515-143005-a1b2c3d",
            timestamp_iso8601="2026-05-15T14:30:05-03:00",
            params_sha256="a" * 64,
            rng_seed=42,
            profile_source="synthetic",
            price_source="bigquery_pld_SE_2025",
            scenario_top_up_hours={},
        )
        path = write_manifest(manifest, results=[], output_dir=tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["tool_version"] == "1.0.0"
        assert data["run_id"] == "20260515-143005-a1b2c3d"
        assert "params_sha256" in data
        assert "scenario_top_up_hours" in data

    def test_bq_service_account_path_absent_from_manifest(self, tmp_path):
        from solar_bess_risk.manifest import RunManifest, write_manifest

        manifest = RunManifest(
            tool_version="1.0.0",
            run_id="20260515-143005-a1b2c3d",
            timestamp_iso8601="2026-05-15T14:30:05-03:00",
            params_sha256="a" * 64,
            rng_seed=42,
            profile_source="synthetic",
            price_source="bigquery_pld_SE_2025",
            scenario_top_up_hours={},
        )
        path = write_manifest(manifest, results=[], output_dir=tmp_path)
        text = path.read_text()
        assert "service_account_path" not in text.lower()
