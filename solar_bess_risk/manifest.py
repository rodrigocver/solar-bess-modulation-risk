"""Run manifest: run-ID generation, SHA-256 hashing, and JSON manifest writer.

Functions
---------
generate_run_id() -> str
hash_params(params) -> str
write_manifest(manifest, output_dir) -> Path
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solar_bess_risk.config import SimulationParams


@dataclass
class RunManifest:
    """JSON run manifest written to output/<run-id>/manifest.json.

    Parameters
    ----------
    tool_version : str
        Semantic version string (e.g. ``"2.0.0"``).
    run_id : str
        ``YYYYMMDD-HHMMSS-<sha256[:7]>``.
    timestamp_iso8601 : str
        ISO 8601 timestamp with timezone.
    params_sha256 : str
        Full 64-char SHA-256 hex of serialised parameters.
    profile_source : str
        CSV filename (basename).
    price_source : str
        ``"bigquery_pld_{submarket}_{year}"``.
    fc : float
        Capacity factor derived from CSV.
    garantia_fisica_mw : float
        Physical guarantee in MW.
    scenarios : list[dict]
        Scenario entries with label, peak_hours, duration_h, bess_power_mw,
        charge_power_mw, bess_energy_mwh, and capex_brl.
    """

    tool_version: str
    run_id: str
    timestamp_iso8601: str
    params_sha256: str
    profile_source: str
    price_source: str
    fc: float
    garantia_fisica_mw: float
    scenarios: list[dict]
    params: dict | None = None
    price_sources_by_year: dict[str, str] | None = None
    backtest_years: list[int] | None = None
    acumulado_years: list[int] | None = None
    curtailment: dict | None = None
    rte: dict | None = None


def generate_run_id() -> str:
    """Generate a run ID in the format ``YYYYMMDD-HHMMSS-<7-char hex>``.

    Returns
    -------
    str
        Run ID string.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    raw = now.isoformat().encode("utf-8")
    hex7 = hashlib.sha256(raw).hexdigest()[:7]
    return f"{ts}-{hex7}"


def hash_params(params: SimulationParams) -> str:
    """Compute SHA-256 of the serialised parameter set.

    The ``bq_service_account_path`` field is excluded entirely — it is
    never serialised.

    Parameters
    ----------
    params : SimulationParams
        Complete simulation configuration.

    Returns
    -------
    str
        64-char hexadecimal SHA-256 digest.
    """
    d = asdict(params)
    d.pop("bq_service_account_path", None)
    raw = json.dumps(d, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_manifest(manifest: RunManifest, output_dir: Path) -> Path:
    """Write the run manifest JSON to ``output_dir/manifest.json``.

    Parameters
    ----------
    manifest : RunManifest
        Populated manifest dataclass.
    output_dir : Path
        Directory to write ``manifest.json`` into (created if missing).

    Returns
    -------
    Path
        Path to the written ``manifest.json``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "manifest.json"
    data = asdict(manifest)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path
