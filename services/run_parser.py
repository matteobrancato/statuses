"""Parse structured information from TestRail run names."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_run_name(
    name: str,
    patterns: dict[str, str] | None = None,
) -> dict[str, str]:
    """Extract country, platform, and type from a run name.

    Uses regex patterns from config. Falls back to 'unknown' for any
    field that cannot be parsed — never raises.
    """
    patterns = patterns or {}
    result = {"country": "unknown", "platform": "unknown", "type": "unknown"}

    for field_name, pattern in patterns.items():
        if field_name not in result:
            continue
        try:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                result[field_name] = match.group(1).strip()
        except re.error as exc:
            logger.warning("Bad regex for '%s': %s", field_name, exc)

    # Heuristic fallback: detect manual/automated from common keywords
    if result["type"] == "unknown":
        lower = name.lower()
        if "automat" in lower:
            result["type"] = "automated"
        elif "manual" in lower:
            result["type"] = "manual"

    # Heuristic fallback: detect platform from common keywords
    if result["platform"] == "unknown":
        lower = name.lower()
        if "desktop" in lower:
            result["platform"] = "desktop"
        elif "mobile" in lower:
            result["platform"] = "mobile"

    return result


def is_regression_run(
    name: str,
    keywords: list[str] | None = None,
) -> bool:
    """Check if a run name matches regression keywords."""
    keywords = keywords or ["Regression", "NR", "On Demand"]
    lower = name.lower()
    return any(kw.lower() in lower for kw in keywords)
