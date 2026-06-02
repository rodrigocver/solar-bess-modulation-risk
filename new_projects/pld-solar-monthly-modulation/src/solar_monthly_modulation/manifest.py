"""Manifest creation for reproducible monthly modulation runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solar_monthly_modulation.constants import FORMULAS, TOOL_VERSION
from solar_monthly_modulation.models import ModulationConfig, ModulationResult


def sha256_file(path: str | Path) -> str:
    """Compute the SHA-256 hash of a file.

    Parameters
    ----------
    path : str or pathlib.Path
        File path to hash.

    Returns
    -------
    str
        Hexadecimal SHA-256 digest.
    """

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    config: ModulationConfig,
    result: ModulationResult,
    outputs: dict[str, str],
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-serialisable audit manifest.

    Parameters
    ----------
    config : ModulationConfig
        Run configuration.
    result : ModulationResult
        Calculation result with source metadata.
    outputs : dict[str, str]
        Output labels and file paths.
    created_at : str or None
        Optional ISO-8601 timestamp override.

    Returns
    -------
    dict[str, Any]
        Manifest payload ready for JSON writing.
    """

    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    config_payload = {
        "csv_path": config.csv_path,
        "mwac": config.mwac,
        "years": list(config.years),
        "submarket": config.submarket,
        "pld_base_dir": config.pld_base_dir,
        "bq_service_account_path_provided": config.bq_service_account_path is not None,
    }
    return {
        "tool": "pld-solar-monthly-modulation",
        "tool_version": TOOL_VERSION,
        "created_at": timestamp,
        "configuration": config_payload,
        "input_hashes": {
            "solar_csv_sha256": sha256_file(config.csv_path),
        },
        "source_labels": {
            "solar_csv_filename": result.source_metadata.solar_csv_filename,
            "solar_fc": result.source_metadata.solar_fc,
            "garantia_fisica_mw": result.source_metadata.garantia_fisica_mw,
            "price_sources": result.source_metadata.price_sources,
        },
        "formulas": FORMULAS,
        "outputs": outputs,
    }


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    """Write a manifest JSON file.

    Parameters
    ----------
    path : str or pathlib.Path
        Destination JSON path.
    manifest : dict[str, Any]
        JSON-serialisable manifest.

    Returns
    -------
    pathlib.Path
        Written manifest path.
    """

    target = Path(path)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return target
