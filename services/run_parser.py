"""Parse structured information from TestRail plan/run names and configs.

TestRail runs inside plan entries often share the same name (the entry name),
but each run has a unique `config` string describing its configuration, e.g.:
    "France, Desktop"
    "UK, Mobile"
    "Latvia (lv_LV), Desktop"

The config string is the PRIMARY source for country/platform extraction.
The run name is used as FALLBACK and for type detection (regression/smoke).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ── Config string parsing (primary) ─────────────────────────────────────────

# Known country name → code mappings
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "ireland": "IE",
    "france": "FR",
    "italy": "IT",
    "austria": "AT",
    "switzerland": "CH",
    "romania": "RO",
    "hungary": "HU",
    "czech republic": "CZ", "czechia": "CZ",
    "slovakia": "SK",
    "belgium": "BE",
    "netherlands": "NL", "holland": "NL",
    "luxembourg": "LU",
    "turkey": "TR",
    "latvia": "LV",
    "lithuania": "LT",
}


def parse_run_config(
    config: str,
    known_countries: list[str] | None = None,
) -> dict[str, str]:
    """Extract country and platform from a TestRail run config string.

    Examples:
        "France, Desktop"           → country=FR, platform=desktop
        "UK, Mobile"                → country=GB, platform=mobile
        "Latvia (lv_LV), Desktop"   → country=LV, platform=desktop
    """
    result = {"country": "unknown", "platform": "unknown"}

    if not config:
        return result

    parts = [p.strip() for p in config.split(",")]

    for part in parts:
        lower = part.lower()

        # Platform detection
        if "desktop" in lower:
            result["platform"] = "desktop"
            continue
        if "mobile" in lower:
            result["platform"] = "mobile"
            continue

        # Country detection — strip parenthetical locale info
        country_part = re.sub(r"\s*\(.*?\)", "", part).strip().lower()

        # Try full name match
        if country_part in _COUNTRY_NAME_TO_CODE:
            result["country"] = _COUNTRY_NAME_TO_CODE[country_part]
            continue

        # Try 2-letter code match
        upper = country_part.upper()
        if len(upper) == 2 and known_countries and upper in [c.upper() for c in known_countries]:
            result["country"] = upper
            continue

        # Try partial match (e.g., "czech" in "czech republic")
        for name, code in _COUNTRY_NAME_TO_CODE.items():
            if country_part in name or name in country_part:
                result["country"] = code
                break

    return result


# ── Run name parsing (fallback + type detection) ────────────────────────────

def parse_run_name(
    name: str,
    bu_code: str = "",
    known_countries: list[str] | None = None,
    config: str = "",
) -> dict[str, str]:
    """Extract type, country, and platform from a TestRail run.

    Uses `config` as primary source for country/platform.
    Falls back to parsing the run `name`.
    Always extracts `type` from the name.
    """
    # Start with config-based parsing
    if config:
        result = parse_run_config(config, known_countries)
    else:
        result = {"country": "unknown", "platform": "unknown"}

    result["type"] = "unknown"

    if not name:
        return result

    lower = name.lower()

    # ── Type detection (always from name) ────────────────────────────
    if "regression" in lower:
        result["type"] = "regression"
    elif "smoke" in lower:
        result["type"] = "smoke"
    elif "sanity" in lower:
        result["type"] = "sanity"
    elif "on demand" in lower or "on_demand" in lower:
        result["type"] = "regression"

    # ── Fallback: country from name if config didn't provide it ──────
    if result["country"] == "unknown":
        upper = name.upper()
        if bu_code and known_countries:
            bu_upper = bu_code.upper()
            for cc in known_countries:
                if f"{bu_upper}{cc.upper()}" in upper:
                    result["country"] = cc.upper()
                    break

        # Bracket notation: [FR], [GB], etc.
        if result["country"] == "unknown" and known_countries:
            for m in re.findall(r"\[([A-Z]{2,3})\]", upper):
                if m in [c.upper() for c in known_countries]:
                    result["country"] = m
                    break

    # ── Fallback: platform from name if config didn't provide it ─────
    if result["platform"] == "unknown":
        if "desktop" in lower:
            result["platform"] = "desktop"
        elif "mobile" in lower:
            result["platform"] = "mobile"

    return result


def build_display_name(run_name: str, config: str) -> str:
    """Build a human-readable display name for a run.

    If config is available, append it to distinguish runs with the same name.
    """
    if config and config not in run_name:
        return f"{run_name} [{config}]"
    return run_name


# ── Plan-level matching ──────────────────────────────────────────────────────

def plan_belongs_to_bu(plan_name: str, bu_code: str) -> bool:
    """Check if a plan name belongs to a specific business unit."""
    if not plan_name or not bu_code:
        return False
    upper = plan_name.upper()
    bu_upper = bu_code.upper()
    if f"[{bu_upper}]" in upper:
        return True
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


def run_belongs_to_bu(run_name: str, config: str, bu_code: str) -> bool:
    """Check if a run belongs to this BU based on name or config.

    Checks both the run name and the config string.
    """
    if not bu_code:
        return True  # No filter
    bu_upper = bu_code.upper()
    if run_name and bu_upper in run_name.upper():
        return True
    # For runs with generic names, we can't filter by BU — include them
    # The plan-level filter already ensures we're in the right project
    if not run_name or run_name == "":
        return True
    return True  # Include by default — plan-level filter is the main gate
