"""Baseline coverage service — computes case counts from a TestRail suite.

Dynamically discovers automation-related custom fields from the TestRail API,
then classifies each case as automated (java, testim_desktop, testim_mobile)
or manual based on those fields.
"""

from __future__ import annotations

import logging
from typing import Any

from models.types import AutomationBreakdown, CoverageData
from testrail_client import TestRailClient

logger = logging.getLogger(__name__)

# Keywords that indicate a case is automated (matched case-insensitively)
_AUTOMATED_KEYWORDS = {"automated", "java", "cypress", "selenium", "playwright"}
_TESTIM_DESKTOP_KEYWORDS = {"testim_desktop", "testim desktop", "testim-desktop"}
_TESTIM_MOBILE_KEYWORDS = {"testim_mobile", "testim mobile", "testim-mobile"}
_NOT_AUTOMATED_KEYWORDS = {"not automated", "none", "manual", "not_automated", "n/a"}


def compute_baseline(
    client: TestRailClient,
    project_id: int,
    suite_id: int,
    regression_priorities: list[str] | None = None,
) -> CoverageData:
    """Fetch all cases from a suite and compute coverage metrics.

    Dynamically discovers automation fields from TestRail's field definitions,
    then checks each case's custom fields to classify automation type.
    """
    # 1. Discover automation-related fields
    auto_fields = _discover_automation_fields(client)
    logger.info("Discovered %d automation-related fields: %s",
                len(auto_fields), [f["system_name"] for f in auto_fields])

    # 2. Fetch all cases
    cases = client.get_cases(project_id, suite_id)
    logger.info("Fetched %d cases from suite %d", len(cases), suite_id)

    priority_set = {p.lower() for p in (regression_priorities or [])}
    regression_count = 0
    breakdown = AutomationBreakdown()

    for case in cases:
        # Count regression cases by priority
        priority_label = _priority_label(case.get("priority_id"))
        if priority_set and priority_label in priority_set:
            regression_count += 1

        # Classify automation using discovered fields
        auto_type = _classify_automation(case, auto_fields)
        if auto_type == "java":
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


def _discover_automation_fields(client: TestRailClient) -> list[dict]:
    """Find all custom fields related to automation status.

    Looks for fields whose label contains 'automation' (case-insensitive).
    Returns a list of field info dicts with keys: system_name, options.
    """
    try:
        all_fields = client.get_case_fields()
    except Exception as e:
        logger.warning("Could not fetch case fields: %s", e)
        return []

    auto_fields: list[dict] = []

    for field in all_fields:
        label = (field.get("label") or "").lower()
        name = field.get("system_name", "")

        # Match fields with "automation" in the label
        if "automation" not in label:
            continue

        # Build option ID → label mapping for dropdown fields
        options_map: dict[int, str] = {}
        configs = field.get("configs", [])
        for config in configs:
            raw_options = config.get("options", {}).get("items", "")
            if isinstance(raw_options, str):
                # Format: "1, Not automated\n2, Automated\n3, Testim Desktop\n..."
                for line in raw_options.strip().split("\n"):
                    line = line.strip()
                    if "," in line:
                        parts = line.split(",", 1)
                        try:
                            opt_id = int(parts[0].strip())
                            opt_label = parts[1].strip()
                            options_map[opt_id] = opt_label
                        except (ValueError, IndexError):
                            pass

        auto_fields.append({
            "system_name": f"custom_{name}" if not name.startswith("custom_") else name,
            "label": field.get("label", ""),
            "options": options_map,
        })

    return auto_fields


def _classify_automation(case: dict, auto_fields: list[dict]) -> str | None:
    """Classify a case's automation type by checking all automation fields.

    Returns: "java", "testim_desktop", "testim_mobile", or None (manual).
    """
    for field_info in auto_fields:
        field_name = field_info["system_name"]
        raw_value = case.get(field_name)

        if raw_value is None or raw_value == 0:
            continue

        # Resolve option ID to label if this is a dropdown field
        options = field_info.get("options", {})
        if isinstance(raw_value, int) and options:
            value_str = options.get(raw_value, "").lower()
        elif isinstance(raw_value, str):
            value_str = raw_value.strip().lower()
        else:
            value_str = str(raw_value).strip().lower()

        # Skip "not automated" / empty
        if not value_str or value_str in _NOT_AUTOMATED_KEYWORDS:
            continue

        # Classify
        if any(kw in value_str for kw in _TESTIM_DESKTOP_KEYWORDS):
            return "testim_desktop"
        if any(kw in value_str for kw in _TESTIM_MOBILE_KEYWORDS):
            return "testim_mobile"
        if any(kw in value_str for kw in _AUTOMATED_KEYWORDS):
            return "java"

        # Any other non-empty, non-"not automated" value → treat as automated
        logger.debug("Unknown automation value '%s' for field '%s' — treating as java",
                      value_str, field_name)
        return "java"

    return None


def _priority_label(priority_id: int | None) -> str:
    """Map TestRail priority ID to a human label (lowercase)."""
    mapping = {1: "low", 2: "medium", 3: "high", 4: "highest"}
    return mapping.get(priority_id or 0, "unknown")
