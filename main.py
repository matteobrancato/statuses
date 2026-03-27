"""Orchestration entry point — exposes get_regression_dashboard()."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from config.settings import get_bu_config, get_regression_keywords, get_lookback_days
from models.types import CoverageData, DashboardResult, PlanData, RunData
from services.baseline_service import compute_baseline
from services.regression_service import (
    aggregate_runs,
    detect_active_regression,
    fetch_plan,
    fetch_run,
)
from services.run_parser import is_regression_run
from testrail_client import TestRailClient
from utils.helpers import is_within_days, parse_testrail_link

logger = logging.getLogger(__name__)


def get_regression_dashboard(
    business_unit: str,
    base_url: str,
    user: str,
    api_key: str,
) -> dict:
    """Compute the full regression dashboard for a business unit.

    Returns a clean, normalized dict matching the output spec.
    """
    bu_cfg = get_bu_config(business_unit)
    client = TestRailClient(base_url, user, api_key)
    keywords = get_regression_keywords()
    lookback = get_lookback_days()
    patterns = bu_cfg.get("run_name_patterns")

    # 1. Baseline coverage
    coverage = compute_baseline(
        client,
        bu_cfg["project_id"],
        bu_cfg["suite_id"],
        bu_cfg.get("regression_priorities"),
    )

    # 2. Find regression plans/runs
    plans = client.get_plans(bu_cfg["project_id"])
    regression_runs: list[RunData] = []

    for plan in plans:
        if not is_regression_run(plan.get("name", ""), keywords):
            continue
        if not is_within_days(plan.get("created_on"), lookback):
            continue
        plan_data = fetch_plan(client, plan["id"], base_url, patterns)
        regression_runs.extend(plan_data.runs)

    # 3. Aggregate
    active = detect_active_regression(regression_runs)
    grouped = aggregate_runs(regression_runs)

    # 4. Serialize (strip internal objects)
    clean_runs = _clean_grouped_runs(grouped)

    return {
        "business_unit": business_unit,
        "active_regression": active,
        "coverage": {
            "total": coverage.total,
            "regression": coverage.regression,
            "automated_total": coverage.automated_total,
            "automation_breakdown": {
                "java": coverage.automation_breakdown.java,
                "testim_desktop": coverage.automation_breakdown.testim_desktop,
                "testim_mobile": coverage.automation_breakdown.testim_mobile,
            },
            "coverage_pct": coverage.coverage_pct,
        },
        "runs": clean_runs,
    }


def fetch_from_link(
    url: str,
    base_url: str,
    user: str,
    api_key: str,
    patterns: dict[str, str] | None = None,
) -> PlanData | RunData:
    """Fetch data from a TestRail link (plan or run URL).

    This is the primary entry point for the Streamlit dashboard.
    """
    client = TestRailClient(base_url, user, api_key)
    resource_type, resource_id = parse_testrail_link(url)

    if resource_type == "plan":
        return fetch_plan(client, resource_id, base_url, patterns)
    else:
        return fetch_run(client, resource_id, base_url, patterns)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _clean_grouped_runs(grouped: dict) -> dict:
    """Remove internal RunData objects from the aggregated structure."""
    clean: dict = {}
    for country, platforms in grouped.items():
        clean[country] = {}
        for platform, types in platforms.items():
            clean[country][platform] = {}
            for rtype, data in types.items():
                clean[country][platform][rtype] = {
                    k: v for k, v in data.items() if k != "runs"
                }
    return clean
