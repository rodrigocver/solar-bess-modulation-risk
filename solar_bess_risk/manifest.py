"""Run manifest: run-ID generation, SHA-256 hashing, and JSON manifest writer.

Functions
---------
generate_run_id() -> str
hash_params(params) -> str
write_manifest(manifest, results, output_dir) -> Path
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from solar_bess_risk import __version__

if TYPE_CHECKING:
    from solar_bess_risk.config import SimulationParams


@dataclass
class RunManifest:
    """JSON run manifest written to output/<run-id>/manifest.json.

    Parameters
    ----------
    tool_version : str
        Semantic version string (e.g. ``"1.0.0"``).
    run_id : str
        ``YYYYMMDD-HHMMSS-<sha256[:7]>``.
    timestamp_iso8601 : str
        ISO 8601 timestamp with timezone.
    params_sha256 : str
        Full 64-char SHA-256 hex of serialised parameters.
    rng_seed : int
        RNG seed used.
    profile_source : str
        ``"synthetic"`` or CSV filename.
    price_source : str
        ``"bigquery_pld_{submarket}_{year}"``.
    scenario_top_up_hours : dict[str, list[str]]
        Per-scenario top-up slots keyed by ``"{ilr}_{bess_pct}_{dur_h}"``.
    """

    tool_version: str
    run_id: str
    timestamp_iso8601: str
    params_sha256: str
    rng_seed: int
    profile_source: str
    price_source: str
    scenario_top_up_hours: dict[str, list[str]]


def generate_run_id() -> str:
    """Generate a run ID in the format ``YYYYMMDD-HHMMSS-<7-char hex>``.

    Returns
    -------
    str
        Run ID string.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    # Use timestamp bytes for a short deterministic hex suffix
    raw = now.isoformat().encode("utf-8")
    hex7 = hashlib.sha256(raw).hexdigest()[:7]
    return f"{ts}-{hex7}"


def hash_params(params: SimulationParams) -> str:
    """Compute SHA-256 of the serialised parameter set.

    The ``bq_service_account_path`` field is excluded for security.

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


def write_manifest(
    manifest: RunManifest,
    results: list,
    output_dir: Path,
) -> Path:
    """Write the run manifest JSON to ``output_dir/manifest.json``.

    If *results* is non-empty and each element has ``top_up_hour_slots`` and
    a ``scenario_id`` attribute, the ``scenario_top_up_hours`` field is
    populated from the results.

    Parameters
    ----------
    manifest : RunManifest
        Populated manifest dataclass.
    results : list
        List of ScenarioResult (or empty).
    output_dir : Path
        Directory to write ``manifest.json`` into.

    Returns
    -------
    Path
        Path to the written ``manifest.json``.
    """
    # Populate top-up hours from results if available
    if results and hasattr(results[0], "scenario_id"):
        top_up: dict[str, list[str]] = {}
        for r in results:
            ilr, bess_pct, dur_h = r.scenario_id
            key = f"{ilr}_{bess_pct}_{dur_h}"
            top_up[key] = list(getattr(r, "top_up_hour_slots", []))
        manifest = RunManifest(
            tool_version=manifest.tool_version,
            run_id=manifest.run_id,
            timestamp_iso8601=manifest.timestamp_iso8601,
            params_sha256=manifest.params_sha256,
            rng_seed=manifest.rng_seed,
            profile_source=manifest.profile_source,
            price_source=manifest.price_source,
            scenario_top_up_hours=top_up,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "manifest.json"
    data = asdict(manifest)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path
