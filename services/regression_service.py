"""Regression service — fetches plans/runs, detects regressions, aggregates data.

PERFORMANCE: Uses run-level summary counts from TestRail's plan/run response
(passed_count, failed_count, etc.) instead of fetching all individual tests.
This eliminates N+1 API calls and makes loading 10-100x faster.
"""

from __future__ import annotations

import logging

from config.settings import get_status_map
from models.types import RunData, StatusCounts, PlanData
from services.run_parser import (
    parse_run_name,
    build_display_name,
    plan_belongs_to_bu,
    is_regression_plan,
    is_smoke_plan,
)
from testrail_client import TestRailClient
from utils.helpers import is_within_days

logger = logging.getLogger(__name__)


def _all_bu_codes() -> list[str]:
    from config.settings import load_config
    cfg = load_config()
    return [
        bu.get("bu_code", "").upper()
        for bu in cfg.get("business_units", {}).values()
        if bu.get("bu_code")
    ]


# ── Status counting from run summary fields ──────────────────────────────────

def _counts_from_run_summary(run_raw: dict) -> StatusCounts:
    """Build StatusCounts from TestRail's run-level summary counts.

    TestRail returns these fields directly in run objects:
    passed_count, failed_count, blocked_count, retest_count, untested_count,
    custom_status1_count, custom_status2_count, etc.

    This avoids fetching individual tests entirely.
    """
    passed = run_raw.get("passed_count", 0) or 0
    failed = run_raw.get("failed_count", 0) or 0
    blocked = run_raw.get("blocked_count", 0) or 0
    retest = run_raw.get("retest_count", 0) or 0
    untested = run_raw.get("untested_count", 0) or 0

    # Collect custom statuses
    smap = get_status_map()
    custom: dict[str, int] = {}
    for i in range(1, 20):
        key = f"custom_status{i}_count"
        count = run_raw.get(key, 0) or 0
        if count > 0:
            # Try to map to a label from our status map
            status_id = str(i + 5)  # custom_status1 = status_id 6, etc.
            label = smap.get(status_id, {}).get("label", f"Custom {i}")
            custom[label] = custom.get(label, 0) + count

    return StatusCounts(
        passed=passed,
        failed=failed,
        blocked=blocked,
        retest=retest,
        untested=untested,
        custom=custom,
    )


def _counts_from_tests(tests: list[dict]) -> StatusCounts:
    """Fallback: count statuses from individual test objects."""
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


# ── Single run fetching (only used for manual link mode) ─────────────────────

def fetch_run(
    client: TestRailClient,
    run_id: int,
    base_url: str = "",
    bu_code: str = "",
    known_countries: list[str] | None = None,
) -> RunData:
    """Fetch a single run. Uses summary counts if available, else fetches tests."""
    raw = client.get_run(run_id)
    run_name = raw.get("name", "")
    config = raw.get("config", "") or ""

    # Use summary counts if available (much faster)
    if raw.get("passed_count") is not None:
        counts = _counts_from_run_summary(raw)
    else:
        tests = client.get_tests(run_id)
        counts = _counts_from_tests(tests)

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


# ── Plan fetching (uses summary counts — NO get_tests calls) ─────────────────

def fetch_plan(
    client: TestRailClient,
    plan_id: int,
    base_url: str = "",
    bu_code: str = "",
    known_countries: list[str] | None = None,
) -> PlanData:
    """Fetch a plan and all its runs using summary counts.

    This makes exactly ONE API call (get_plan) regardless of how many runs exist.
    No get_tests calls needed.
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

            # Use summary counts from plan response — no extra API call
            counts = _counts_from_run_summary(run_raw)
            parsed = parse_run_name(run_name, bu_code, known_countries, config=config)
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
    """Find recent plans that belong to a BU.

    Uses created_after filter to reduce API payload.
    """
    import time
    created_after = int(time.time()) - (lookback_days * 86400)

    all_plans = client.get_plans(project_id, created_after=created_after)
    matched: list[dict] = []

    all_codes = _all_bu_codes()

    for plan in all_plans:
        name = plan.get("name", "")

        # Filter by BU
        bu_match = plan_belongs_to_bu(name, bu_code)
        # Allow shared/umbrella plans (no other BU code in name)
        is_shared = not any(
            code in name.upper()
            for code in all_codes
            if code != bu_code.upper()
        )
        if not bu_match and not is_shared:
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
    """Group runs: country -> platform -> type -> stats."""
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
    return any(not r.is_completed for r in runs)
