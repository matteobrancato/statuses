"""Baseline coverage service — computes case counts from a TestRail suite.

Dynamically discovers automation-related custom fields from the TestRail API.
The automation TYPE (java, testim_desktop, testim_mobile) is determined by the
FIELD LABEL, not the value. The VALUE determines if it's automated, backlog, etc.

Field label examples:
    "Automation Status"               → java
    "Automation Status Testim Desktop" → testim_desktop
    "Automation Status Testim Mobile"  → testim_mobile

Value examples:
    "Not automated"        → skip
    "Automated"            → automated
    "Automated UAT"        → automated
    "Automated DEV"        → automated
    "Ready to be automated" → backlog
"""

from __future__ import annotations

import logging

from models.types import AutomationBreakdown, AutomationBacklog, CoverageData
from testrail_client import TestRailClient

logger = logging.getLogger(__name__)

# Values that count as "automated" (substring match, case-insensitive)
_AUTOMATED_PREFIXES = ["automated"]
# Values that explicitly mean NOT automated
_NOT_AUTOMATED_VALUES = {"not automated", "none", "manual", "not_automated", "n/a", ""}
# Values that mean "ready to be automated" (backlog)
_BACKLOG_VALUES = {"ready to be automated", "ready_to_be_automated", "ready for automation"}


def compute_baseline(
    client: TestRailClient,
    project_id: int,
    suite_id: int,
    regression_priorities: list[str] | None = None,
) -> CoverageData:
    """Fetch all cases and compute coverage metrics."""
    # 1. Discover automation-related fields
    auto_fields = _discover_automation_fields(client)
    logger.info("Discovered %d automation fields: %s",
                len(auto_fields), [(f["label"], f["auto_type"]) for f in auto_fields])

    # 2. Fetch all cases
    cases = client.get_cases(project_id, suite_id)
    logger.info("Fetched %d cases from suite %d", len(cases), suite_id)

    # Default regression priorities: high + highest
    priority_set = {p.lower() for p in (regression_priorities or ["high", "highest"])}
    regression_count = 0
    breakdown = AutomationBreakdown()
    backlog = AutomationBacklog()

    for case in cases:
        # Count regression cases by priority
        priority_label = _priority_label(case.get("priority_id"))
        if priority_label in priority_set:
            regression_count += 1

        # Classify automation across all fields
        _classify_case(case, auto_fields, breakdown, backlog)

    return CoverageData(
        total=len(cases),
        regression=regression_count,
        automated_total=breakdown.total,
        automation_breakdown=breakdown,
        automation_backlog=backlog,
    )


def _discover_automation_fields(client: TestRailClient) -> list[dict]:
    """Find all custom fields related to automation status.

    Returns list of dicts with: system_name, label, auto_type, options.
    auto_type is determined by the field label:
        - contains "testim desktop" → "testim_desktop"
        - contains "testim mobile"  → "testim_mobile"
        - otherwise                 → "java"
    """
    try:
        all_fields = client.get_case_fields()
    except Exception as e:
        logger.warning("Could not fetch case fields: %s", e)
        return []

    auto_fields: list[dict] = []

    for field in all_fields:
        label = (field.get("label") or "")
        label_lower = label.lower()
        name = field.get("system_name", "")

        if "automation" not in label_lower:
            continue

        # Determine type from field label
        if "testim" in label_lower and "desktop" in label_lower:
            auto_type = "testim_desktop"
        elif "testim" in label_lower and "mobile" in label_lower:
            auto_type = "testim_mobile"
        else:
            auto_type = "java"

        # Build option ID → label mapping for dropdown fields
        options_map: dict[int, str] = {}
        configs = field.get("configs", [])
        for config in configs:
            raw_options = config.get("options", {}).get("items", "")
            if isinstance(raw_options, str):
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

        system_name = f"custom_{name}" if not name.startswith("custom_") else name
        auto_fields.append({
            "system_name": system_name,
            "label": label,
            "auto_type": auto_type,
            "options": options_map,
        })

    return auto_fields


def _classify_case(
    case: dict,
    auto_fields: list[dict],
    breakdown: AutomationBreakdown,
    backlog: AutomationBacklog,
) -> None:
    """Check all automation fields for a case, updating breakdown and backlog.

    A case can be counted in multiple types if it has values in multiple fields
    (e.g. automated in "Automation Status" AND "Automation Status Testim Desktop").
    We count the FIRST automated match to avoid double-counting in totals.
    Backlog is counted independently per field.
    """
    counted_automated = False

    for field_info in auto_fields:
        field_name = field_info["system_name"]
        auto_type = field_info["auto_type"]
        raw_value = case.get(field_name)

        if raw_value is None or raw_value == 0:
            continue

        # Resolve dropdown ID to label
        options = field_info.get("options", {})
        if isinstance(raw_value, int) and options:
            value_str = options.get(raw_value, "").strip().lower()
        elif isinstance(raw_value, str):
            value_str = raw_value.strip().lower()
        else:
            value_str = str(raw_value).strip().lower()

        if not value_str or value_str in _NOT_AUTOMATED_VALUES:
            continue

        # Check backlog
        if value_str in _BACKLOG_VALUES:
            if auto_type == "java":
                backlog.java += 1
            elif auto_type == "testim_desktop":
                backlog.testim_desktop += 1
            elif auto_type == "testim_mobile":
                backlog.testim_mobile += 1
            continue

        # Check automated (value starts with or contains "automated")
        is_automated = any(value_str.startswith(prefix) for prefix in _AUTOMATED_PREFIXES)
        if is_automated and not counted_automated:
            counted_automated = True
            if auto_type == "java":
                breakdown.java += 1
            elif auto_type == "testim_desktop":
                breakdown.testim_desktop += 1
            elif auto_type == "testim_mobile":
                breakdown.testim_mobile += 1


def _priority_label(priority_id: int | None) -> str:
    """Map TestRail priority ID to a human label (lowercase)."""
    mapping = {1: "low", 2: "medium", 3: "high", 4: "highest"}
    return mapping.get(priority_id or 0, "unknown")
