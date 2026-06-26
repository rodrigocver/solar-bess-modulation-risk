"""Structured exceptions for monthly modulation calculations."""

from __future__ import annotations


class MonthlyModulationError(Exception):
    """Base error for invalid monthly modulation runs."""


class ModulationValidationError(MonthlyModulationError):
    """Raised when input data or parameters cannot produce valid outputs."""
