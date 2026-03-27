"""Utility helpers — URL parsing, date checks, normalization."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


def parse_testrail_link(url: str) -> tuple[str, int]:
    """Extract (resource_type, id) from a TestRail URL.

    Supports both styles:
      - https://host/index.php?/plans/view/12345
      - https://host/index.php?/runs/view/12345
      - https://host/plans/view/12345  (path-style)
    """
    parsed = urlparse(url)

    # Query-string style: index.php?/plans/view/61949
    if parsed.query:
        path_part = parsed.query.lstrip("/")
    else:
        path_part = parsed.path.lstrip("/")

    match = re.search(r"(plans|runs)/view/(\d+)", path_part)
    if match:
        resource = "plan" if match.group(1) == "plans" else "run"
        return resource, int(match.group(2))

    raise ValueError(f"Cannot parse TestRail link: {url}")


def is_within_days(timestamp: int | None, days: int) -> bool:
    """Check if a UNIX timestamp falls within the last N days."""
    if timestamp is None:
        return False
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    return dt >= cutoff


def safe_percentage(numerator: int | float, denominator: int | float) -> float:
    """Compute percentage safely, returning 0.0 on division by zero."""
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 1)


def normalize_string(value: str) -> str:
    """Lowercase and strip a string for consistent comparison."""
    return value.strip().lower()
