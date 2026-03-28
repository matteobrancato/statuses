"""Orchestration entry point — exposes get_regression_dashboard() and fetch_from_link()."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import (
    get_bu_config,
    get_regression_keywords,
    get_smoke_keywords,
    get_lookback_days,
)
from models.types import PlanData, RunData
from services.baseline_service import compute_baseline
from services.regression_service import (
    aggregate_runs,
    detect_active_regression,
    discover_plans_for_bu,
    fetch_plan,
    fetch_run,
)
from testrail_client import TestRailClient
from utils.helpers import parse_testrail_link

logger = logging.getLogger(__name__)


def get_regression_dashboard(
    business_unit: str,
    base_url: str,
    user: str,
    api_key: str,
) -> dict:
    """Compute the full regression dashboard for a business unit.

    Steps:
        1. Compute baseline coverage from the suite
        2. Discover recent regression/smoke plans for the BU
        3. Fetch runs, filter by BU, parse names
        4. Aggregate and return clean JSON

    Returns a dict with: business_unit, active_regression, coverage, plans.
    """
    bu_cfg = get_bu_config(business_unit)
    client = TestRailClient(base_url, user, api_key)

    bu_code = bu_cfg["bu_code"]
    project_id = bu_cfg["project_id"]
    suite_id = bu_cfg["suite_id"]
    known_countries = list(bu_cfg.get("countries", {}).keys())
    country_names = bu_cfg.get("countries", {})

    regression_kw = get_regression_keywords()
    smoke_kw = get_smoke_keywords()
    lookback = get_lookback_days()

    # 1. Baseline coverage
    coverage = compute_baseline(
        client, project_id, suite_id,
        bu_cfg.get("regression_priorities"),
    )

    # 2. Discover plans
    raw_plans = discover_plans_for_bu(
        client, project_id, bu_code,
        regression_kw, smoke_kw, lookback,
    )

    # 3. Fetch each plan's runs (filtered by BU)
    plan_results: list[dict] = []
    all_runs: list[RunData] = []

    for raw_plan in raw_plans:
        plan_data = fetch_plan(
            client, raw_plan["id"], base_url,
            bu_code=bu_code,
            known_countries=known_countries,
        )
        if not plan_data.runs:
            continue

        all_runs.extend(plan_data.runs)
        plan_results.append({
            "id": plan_data.id,
            "name": plan_data.name,
            "url": plan_data.url,
            "plan_type": raw_plan.get("plan_type", "unknown"),
            "is_active": plan_data.is_active,
            "total": plan_data.counts.total,
            "executed": plan_data.counts.executed,
            "passed": plan_data.counts.passed,
            "failed": plan_data.counts.failed,
            "blocked": plan_data.counts.blocked,
            "progress": plan_data.counts.progress,
            "pass_rate": plan_data.counts.pass_rate,
            "runs": [
                {
                    "id": r.id,
                    "name": r.name,
                    "url": r.url,
                    "status": r.status,
                    "country": r.country,
                    "country_name": country_names.get(r.country, r.country),
                    "platform": r.platform,
                    "run_type": r.run_type,
                    "total": r.counts.total,
                    "executed": r.counts.executed,
                    "passed": r.counts.passed,
                    "failed": r.counts.failed,
                    "blocked": r.counts.blocked,
                    "retest": r.counts.retest,
                    "untested": r.counts.untested,
                    "progress": r.counts.progress,
                    "pass_rate": r.counts.pass_rate,
                }
                for r in plan_data.runs
            ],
        })

    # 4. Build output
    active = detect_active_regression(all_runs)

    return {
        "business_unit": business_unit,
        "bu_code": bu_code,
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
            "automation_backlog": {
                "java": coverage.automation_backlog.java,
                "testim_desktop": coverage.automation_backlog.testim_desktop,
                "testim_mobile": coverage.automation_backlog.testim_mobile,
                "total": coverage.automation_backlog.total,
            },
            "coverage_pct": coverage.coverage_pct,
        },
        "plans": plan_results,
        "country_names": country_names,
    }


def fetch_from_link(
    url: str,
    base_url: str,
    user: str,
    api_key: str,
    bu_code: str = "",
    known_countries: list[str] | None = None,
) -> PlanData | RunData:
    """Fetch data from a TestRail link (plan or run URL).

    This is the entry point for the manual-link mode.
    """
    client = TestRailClient(base_url, user, api_key)
    resource_type, resource_id = parse_testrail_link(url)

    if resource_type == "plan":
        return fetch_plan(
            client, resource_id, base_url,
            bu_code=bu_code, known_countries=known_countries,
        )
    else:
        return fetch_run(
            client, resource_id, base_url,
            bu_code=bu_code, known_countries=known_countries,
        )
