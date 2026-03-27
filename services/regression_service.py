"""Regression service — detects active regressions and aggregates run data."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import get_regression_keywords, get_lookback_days, get_status_map
from models.types import RunData, StatusCounts, PlanData
from services.run_parser import is_regression_run, parse_run_name
from testrail_client import TestRailClient
from utils.helpers import is_within_days

logger = logging.getLogger(__name__)


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
    patterns: dict[str, str] | None = None,
) -> RunData:
    """Fetch a single run and compute its status counts."""
    raw = client.get_run(run_id)
    tests = client.get_tests(run_id)
    counts = _count_statuses(tests)
    parsed = parse_run_name(raw.get("name", ""), patterns)

    return RunData(
        id=run_id,
        name=raw.get("name", ""),
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
    patterns: dict[str, str] | None = None,
) -> PlanData:
    """Fetch a plan and all its runs, aggregating status counts."""
    raw = client.get_plan(plan_id)
    plan_name = raw.get("name", "")
    entries = raw.get("entries", [])

    runs: list[RunData] = []
    aggregated = StatusCounts()

    for entry in entries:
        for run_raw in entry.get("runs", []):
            rid = run_raw["id"]
            tests = client.get_tests(rid)
            counts = _count_statuses(tests)
            parsed = parse_run_name(run_raw.get("name", ""), patterns)

            run = RunData(
                id=rid,
                name=run_raw.get("name", ""),
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


# ── Run aggregation (grouped) ──────────────────────────────────────────────

def aggregate_runs(runs: list[RunData]) -> dict:
    """Group runs into nested dict: country → platform → type → stats."""
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
            # Aggregate into existing group
            grp = grouped[country][platform][rtype]
            grp["passed"] += run.counts.passed
            grp["failed"] += run.counts.failed
            grp["blocked"] += run.counts.blocked
            grp["retest"] += run.counts.retest
            grp["untested"] += run.counts.untested
            grp["total"] += run.counts.total
            grp["runs"].append(run)

            # Recompute derived values
            total = grp["total"]
            executed = total - grp["untested"]
            grp["progress"] = (executed / total * 100) if total else 0.0
            grp["pass_rate"] = (grp["passed"] / executed * 100) if executed else 0.0

            # Active if any run is active
            if run.status == "active":
                grp["status"] = "active"

    return grouped


# ── Regression detection ────────────────────────────────────────────────────

def detect_active_regression(runs: list[RunData]) -> bool:
    """A regression is active if at least one run is not completed."""
    return any(not r.is_completed for r in runs)
