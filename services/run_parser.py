"""Parse structured information from TestRail plan/run names.

Run names follow patterns like:
    "Regression TPSGB Desktop"   → type=regression, bu=TPS, country=GB, platform=desktop
    "Smoke TPSGB Mobile"         → type=smoke,      bu=TPS, country=GB, platform=mobile
    "Regression DRGLT Desktop"   → type=regression, bu=DRG, country=LT, platform=desktop

Plan names follow patterns like:
    "[TPS][JDK21] 2nd March 2026 On Demand Run S1"
    "[DRG][LV] March 2026 Regression"
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Run name parsing ─────────────────────────────────────────────────────────

def parse_run_name(
    name: str,
    bu_code: str = "",
    known_countries: list[str] | None = None,
) -> dict[str, str]:
    """Extract type, country, and platform from a TestRail run name.

    Args:
        name: The run name, e.g. "Regression TPSGB Desktop".
        bu_code: The BU short code, e.g. "TPS".
        known_countries: List of known country codes for this BU, e.g. ["GB", "IE"].

    Returns:
        Dict with keys: type, country, platform. Unknown fields → "unknown".
    """
    result = {"type": "unknown", "country": "unknown", "platform": "unknown"}

    if not name:
        return result

    upper = name.upper()
    lower = name.lower()

    # ── Type detection ───────────────────────────────────────────────
    if "regression" in lower:
        result["type"] = "regression"
    elif "smoke" in lower:
        result["type"] = "smoke"
    elif "sanity" in lower:
        result["type"] = "sanity"

    # ── Platform detection ───────────────────────────────────────────
    if "desktop" in lower:
        result["platform"] = "desktop"
    elif "mobile" in lower:
        result["platform"] = "mobile"

    # ── Country detection ────────────────────────────────────────────
    # Strategy 1: If we know the BU code, look for {BU_CODE}{COUNTRY} pattern
    if bu_code and known_countries:
        bu_upper = bu_code.upper()
        for cc in known_countries:
            # Match "TPSGB" or "TPS GB" or "TPS_GB" in the run name
            patterns = [
                f"{bu_upper}{cc.upper()}",       # TPSGB
                f"{bu_upper} {cc.upper()}",      # TPS GB
                f"{bu_upper}_{cc.upper()}",      # TPS_GB
            ]
            for pat in patterns:
                if pat in upper:
                    result["country"] = cc.upper()
                    break
            if result["country"] != "unknown":
                break

    # Strategy 2: Check for [COUNTRY] bracket notation
    if result["country"] == "unknown" and known_countries:
        bracket_match = re.findall(r"\[([A-Z]{2,3})\]", upper)
        for m in bracket_match:
            if m in [c.upper() for c in known_countries]:
                result["country"] = m
                break

    # Strategy 3: Check for country code as standalone word
    if result["country"] == "unknown" and known_countries:
        for cc in known_countries:
            # Match as whole word
            if re.search(rf"\b{cc.upper()}\b", upper):
                result["country"] = cc.upper()
                break

    return result


# ── Plan name matching ───────────────────────────────────────────────────────

def plan_belongs_to_bu(plan_name: str, bu_code: str) -> bool:
    """Check if a plan name belongs to a specific business unit.

    Plan names often contain [BU_CODE] in brackets, or the BU code
    as part of run names within.
    """
    if not plan_name or not bu_code:
        return False

    upper = plan_name.upper()
    bu_upper = bu_code.upper()

    # Check bracket notation: [TPS], [DRG], etc.
    if f"[{bu_upper}]" in upper:
        return True

    # Check if BU code appears as word or prefix
    # e.g., "TPSGB" contains "TPS"
    if bu_upper in upper:
        return True

    return False


def is_regression_plan(name: str, keywords: list[str] | None = None) -> bool:
    """Check if a plan name matches regression/on-demand keywords."""
    keywords = keywords or ["Regression", "NR", "No Regression", "On Demand"]
    lower = name.lower()
    return any(kw.lower() in lower for kw in keywords)


def is_smoke_plan(name: str, keywords: list[str] | None = None) -> bool:
    """Check if a plan name matches smoke keywords."""
    keywords = keywords or ["Smoke"]
    lower = name.lower()
    return any(kw.lower() in lower for kw in keywords)


def run_belongs_to_bu(run_name: str, bu_code: str) -> bool:
    """Check if a specific run within a plan belongs to this BU.

    Run names like "Regression TPSGB Desktop" contain the BU code.
    """
    if not run_name or not bu_code:
        return False
    return bu_code.upper() in run_name.upper()
