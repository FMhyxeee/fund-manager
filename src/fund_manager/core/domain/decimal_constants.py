"""Shared decimal precision and sentinel constants for deterministic accounting."""

from __future__ import annotations

from decimal import Decimal

UNITS_QUANTIZER = Decimal("0.000001")
RATIO_QUANTIZER = Decimal("0.000001")
NAV_QUANTIZER = Decimal("0.00000001")
AVG_COST_QUANTIZER = NAV_QUANTIZER
AMOUNT_QUANTIZER = Decimal("0.0001")
TOTAL_COST_QUANTIZER = AMOUNT_QUANTIZER
MONEY_QUANTIZER = AMOUNT_QUANTIZER
ZERO = Decimal("0")
HUNDRED = Decimal("100")

__all__ = [
    "AMOUNT_QUANTIZER",
    "AVG_COST_QUANTIZER",
    "HUNDRED",
    "MONEY_QUANTIZER",
    "NAV_QUANTIZER",
    "RATIO_QUANTIZER",
    "TOTAL_COST_QUANTIZER",
    "UNITS_QUANTIZER",
    "ZERO",
]
