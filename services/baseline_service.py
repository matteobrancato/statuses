"""Baseline coverage service — computes case counts from a TestRail suite."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from config.settings import get_automation_type_map
from models.types import AutomationBreakdown, CoverageData
from testrail_client import TestRailClient

logger = logging.getLogger(__name__)


def compute_baseline(
    client: TestRailClient,
    project_id: int,
    suite_id: int,
    regression_priorities: list[str] | None = None,
) -> CoverageData:
    """Fetch all cases from a suite and compute coverage metrics.

    Caches internally — safe to call multiple times for the same suite.
    """
    cases = client.get_cases(project_id, suite_id)
    logger.info("Fetched %d cases from suite %d", len(cases), suite_id)

    priority_set = {p.lower() for p in (regression_priorities or [])}
    regression_count = 0
    breakdown = AutomationBreakdown()

    type_map = get_automation_type_map()

    for case in cases:
        # Count regression cases by priority
        priority_label = _priority_label(case.get("priority_id"))
        if priority_set and priority_label in priority_set:
            regression_count += 1

        # Classify automation type
        auto_type = (case.get("custom_automation_type") or "").strip().lower()
        if auto_type in ("automated", "java"):
            breakdown.java += 1
        elif auto_type == "testim_desktop":
            breakdown.testim_desktop += 1
        elif auto_type == "testim_mobile":
            breakdown.testim_mobile += 1

    return CoverageData(
        total=len(cases),
        regression=regression_count,
        automated_total=breakdown.total,
        automation_breakdown=breakdown,
    )


def _priority_label(priority_id: int | None) -> str:
    """Map TestRail priority ID to a human label (lowercase)."""
    mapping = {1: "low", 2: "medium", 3: "high", 4: "highest"}
    return mapping.get(priority_id or 0, "unknown")
