"""Regression service — fetches plans/runs, detects regressions, aggregates data."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import get_status_map
from models.types import RunData, StatusCounts, PlanData
from services.run_parser import (
    parse_run_name,
    build_display_name,
    plan_belongs_to_bu,
    run_belongs_to_bu,
    is_regression_plan,
    is_smoke_plan,
)
from testrail_client import TestRailClient
from utils.helpers import is_within_days

logger = logging.getLogger(__name__)


def _all_bu_codes() -> list[str]:
    """Return all BU codes from config (cached internally)."""
    from config.settings import load_config
    cfg = load_config()
    return [
        bu.get("bu_code", "").upper()
        for bu in cfg.get("business_units", {}).values()
        if bu.get("bu_code")
    ]


# ── Status counting ─────────────────────────────────────────────────────────

def _count_statuses(tests: list[dict]) -> StatusCounts:
    """Tally test statuses into a StatusCounts object."""
    smap = get_status_map()
    counts = StatusCounts()

    for test in tests:
        sid = str(test.get("status_id", 3))
        label = smap.get(sid, {}).get("label", f"Status_{sid}")

        if label == "Passed":
            counts.passed += 1
        elif label == "Failed":
            counts.failed += 1
        elif label == "Blocked":
            counts.blocked += 1
        elif label == "Retest":
            counts.retest += 1
        elif label == "Untested":
            counts.untested += 1
        else:
            counts.custom[label] = counts.custom.get(label, 0) + 1

    return counts


# ── Single run fetching ─────────────────────────────────────────────────────

def fetch_run(
    client: TestRailClient,
    run_id: int,
    base_url: str = "",
    bu_code: str = "",
    known_countries: list[str] | None = None,
) -> RunData:
    """Fetch a single run and compute its status counts."""
    raw = client.get_run(run_id)
    tests = client.get_tests(run_id)
    counts = _count_statuses(tests)

    run_name = raw.get("name", "")
    config = raw.get("config", "") or ""
    parsed = parse_run_name(run_name, bu_code, known_countries, config=config)
    display = build_display_name(run_name, config)

    return RunData(
        id=run_id,
        name=display,
        url=f"{base_url}/index.php?/runs/view/{run_id}",
        is_completed=raw.get("is_completed", False),
        country=parsed["country"],
        platform=parsed["platform"],
        run_type=parsed["type"],
        counts=counts,
    )


# ── Plan fetching ───────────────────────────────────────────────────────────

def fetch_plan(
    client: TestRailClient,
    plan_id: int,
    base_url: str = "",
    bu_code: str = "",
    known_countries: list[str] | None = None,
) -> PlanData:
    """Fetch a plan and all its runs, aggregating status counts.

    Uses the run's `config` field (e.g. "France, Desktop") as primary source
    for country/platform extraction.
    """
    raw = client.get_plan(plan_id)
    plan_name = raw.get("name", "")
    entries = raw.get("entries", [])

    runs: list[RunData] = []
    aggregated = StatusCounts()

    for entry in entries:
        entry_name = entry.get("name", "")

        for run_raw in entry.get("runs", []):
            run_name = run_raw.get("name", "") or entry_name
            config = run_raw.get("config", "") or ""

            rid = run_raw["id"]
            tests = client.get_tests(rid)
            counts = _count_statuses(tests)
            parsed = parse_run_name(run_name, bu_code, known_countries, config=config)

            # Build a clear display name using config
            display = build_display_name(entry_name or run_name, config)

            run = RunData(
                id=rid,
                name=display,
                url=f"{base_url}/index.php?/runs/view/{rid}",
                is_completed=run_raw.get("is_completed", False),
                country=parsed["country"],
                platform=parsed["platform"],
                run_type=parsed["type"],
                counts=counts,
            )
            runs.append(run)
            aggregated = aggregated.merge(counts)

    return PlanData(
        id=plan_id,
        name=plan_name,
        url=f"{base_url}/index.php?/plans/view/{plan_id}",
        runs=runs,
        counts=aggregated,
    )


# ── Discover plans for a BU ─────────────────────────────────────────────────

def discover_plans_for_bu(
    client: TestRailClient,
    project_id: int,
    bu_code: str,
    regression_keywords: list[str],
    smoke_keywords: list[str],
    lookback_days: int,
) -> list[dict]:
    """Find recent plans that belong to a BU and match regression/smoke keywords."""
    all_plans = client.get_plans(project_id)
    matched: list[dict] = []

    for plan in all_plans:
        name = plan.get("name", "")

        # Filter by BU — but allow shared/umbrella plans
        bu_match = plan_belongs_to_bu(name, bu_code)
        is_shared = not any(
            f"[{code}]" in name.upper() or code in name.upper()
            for code in _all_bu_codes()
            if code != bu_code.upper()
        )
        if not bu_match and not is_shared:
            continue

        # Must be recent
        if not is_within_days(plan.get("created_on"), lookback_days):
            continue

        # Classify plan type
        if is_regression_plan(name, regression_keywords):
            plan["plan_type"] = "regression"
        elif is_smoke_plan(name, smoke_keywords):
            plan["plan_type"] = "smoke"
        else:
            plan["plan_type"] = "other"

        matched.append(plan)

    logger.info(
        "Found %d plans for BU '%s' in project %d (last %d days)",
        len(matched), bu_code, project_id, lookback_days,
    )
    return matched


# ── Run aggregation ────────────────────────────────────────────────────────

def aggregate_runs(runs: list[RunData]) -> dict:
    """Group runs: country → platform → type → stats."""
    grouped: dict = {}

    for run in runs:
        country = run.country
        platform = run.platform
        rtype = run.run_type

        grouped.setdefault(country, {})
        grouped[country].setdefault(platform, {})

        if rtype not in grouped[country][platform]:
            grouped[country][platform][rtype] = {
                "status": run.status,
                "progress": run.counts.progress,
                "pass_rate": run.counts.pass_rate,
                "passed": run.counts.passed,
                "failed": run.counts.failed,
                "blocked": run.counts.blocked,
                "retest": run.counts.retest,
                "untested": run.counts.untested,
                "total": run.counts.total,
                "runs": [run],
            }
        else:
            grp = grouped[country][platform][rtype]
            grp["passed"] += run.counts.passed
            grp["failed"] += run.counts.failed
            grp["blocked"] += run.counts.blocked
            grp["retest"] += run.counts.retest
            grp["untested"] += run.counts.untested
            grp["total"] += run.counts.total
            grp["runs"].append(run)

            total = grp["total"]
            executed = total - grp["untested"]
            grp["progress"] = (executed / total * 100) if total else 0.0
            grp["pass_rate"] = (grp["passed"] / executed * 100) if executed else 0.0

            if run.status == "active":
                grp["status"] = "active"

    return grouped


# ── Regression detection ────────────────────────────────────────────────────

def detect_active_regression(runs: list[RunData]) -> bool:
    """A regression is active if at least one run is not completed."""
    return any(not r.is_completed for r in runs)
