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
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from solar_bess_risk import __version__

if TYPE_CHECKING:
    from solar_bess_risk.config import SimulationParams

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")


@dataclass
class RunManifest:
    """JSON run manifest written to output/<run-id>/manifest.json.

    Parameters
    ----------
    tool_version : str
        Semantic version string (e.g. ``"2.0.0"``).
    run_id : str
        ``YYYYMMDD-HHMMSS-<branch>``.
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


def _current_branch() -> str:
    """Return the current git branch name, or 'unknown' if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
        # Sanitize: replace characters not safe for directory names
        return branch.replace("/", "-").replace("\\", "-") or "unknown"
    except Exception:
        return "unknown"


def generate_run_id() -> str:
    """Generate a run ID in the format ``YYYYMMDD-HHMMSS-<branch>``.

    Returns
    -------
    str
        Run ID string.
    """
    now = datetime.now(SAO_PAULO_TZ)
    ts = now.strftime("%Y%m%d-%H%M%S")
    branch = _current_branch()
    return f"{ts}-{branch}"


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
