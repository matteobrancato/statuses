"""TestRail API client for fetching test run/plan data."""

import re
import requests
from urllib.parse import urlparse, parse_qs


# TestRail status IDs → human-readable labels and colors
STATUS_MAP = {
    1: {"label": "Passed", "color": "#4CAF50"},
    2: {"label": "Blocked", "color": "#9C27B0"},
    3: {"label": "Untested", "color": "#9E9E9E"},
    4: {"label": "Retest", "color": "#FF9800"},
    5: {"label": "Failed", "color": "#F44336"},
    6: {"label": "Custom 1", "color": "#00BCD4"},
    7: {"label": "Custom 2", "color": "#795548"},
    8: {"label": "Custom 3", "color": "#607D8B"},
}


class TestRailClient:
    """Minimal TestRail API v2 wrapper."""

    def __init__(self, base_url: str, user: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (user, api_key)
        self.session.headers.update({"Content-Type": "application/json"})

    def _get(self, endpoint: str, params: dict | None = None):
        url = f"{self.base_url}/index.php?/api/v2/{endpoint}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_plan(self, plan_id: int) -> dict:
        return self._get(f"get_plan/{plan_id}")

    def get_run(self, run_id: int) -> dict:
        return self._get(f"get_run/{run_id}")

    def get_tests(self, run_id: int) -> list[dict]:
        """Fetch all tests for a run, handling pagination."""
        tests = []
        offset = 0
        while True:
            data = self._get(f"get_tests/{run_id}", params={"limit": 250, "offset": offset})
            if isinstance(data, dict) and "tests" in data:
                batch = data["tests"]
                tests.extend(batch)
                if data.get("_links", {}).get("next") is None:
                    break
                offset += len(batch)
            elif isinstance(data, list):
                tests.extend(data)
                break
            else:
                break
        return tests

    def get_results_for_run(self, run_id: int) -> list[dict]:
        """Fetch all results for a run, handling pagination."""
        results = []
        offset = 0
        while True:
            data = self._get(f"get_results_for_run/{run_id}", params={"limit": 250, "offset": offset})
            if isinstance(data, dict) and "results" in data:
                batch = data["results"]
                results.extend(batch)
                if data.get("_links", {}).get("next") is None:
                    break
                offset += len(batch)
            elif isinstance(data, list):
                results.extend(data)
                break
            else:
                break
        return results


def parse_testrail_link(url: str) -> tuple[str, int]:
    """Parse a TestRail URL and return (type, id).

    Supports:
      - /plans/view/12345
      - /runs/view/12345
    Returns ('plan', id) or ('run', id).
    """
    # Try path-style: /plans/view/ID or /runs/view/ID
    match = re.search(r"/(plans|runs)/view/(\d+)", url)
    if match:
        kind = "plan" if match.group(1) == "plans" else "run"
        return kind, int(match.group(2))

    # Try query-style: ?/plans/view/ID or ?/runs/view/ID
    parsed = urlparse(url)
    query = parsed.query
    match = re.search(r"/(plans|runs)/view/(\d+)", query)
    if match:
        kind = "plan" if match.group(1) == "plans" else "run"
        return kind, int(match.group(2))

    raise ValueError(f"Cannot parse TestRail URL: {url}")


def fetch_run_data(client: TestRailClient, run_id: int) -> dict:
    """Fetch a single run and its tests, return structured data."""
    run = client.get_run(run_id)
    tests = client.get_tests(run_id)

    status_counts = {}
    for t in tests:
        sid = t.get("status_id", 3)  # default untested
        info = STATUS_MAP.get(sid, {"label": f"Status {sid}", "color": "#999999"})
        label = info["label"]
        status_counts[label] = status_counts.get(label, 0) + 1

    total = len(tests)
    passed = status_counts.get("Passed", 0)
    failed = status_counts.get("Failed", 0)
    blocked = status_counts.get("Blocked", 0)
    untested = status_counts.get("Untested", 0)
    retest = status_counts.get("Retest", 0)
    executed = total - untested

    return {
        "run_id": run_id,
        "name": run.get("name", f"Run #{run_id}"),
        "description": run.get("description", ""),
        "url": run.get("url", ""),
        "milestone": run.get("milestone", None),
        "created_on": run.get("created_on"),
        "is_completed": run.get("is_completed", False),
        "total": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "untested": untested,
        "retest": retest,
        "executed": executed,
        "pass_rate": (passed / executed * 100) if executed > 0 else 0,
        "completion": (executed / total * 100) if total > 0 else 0,
        "status_counts": status_counts,
        "tests": tests,
    }


def fetch_plan_data(client: TestRailClient, plan_id: int) -> dict:
    """Fetch a test plan and all its child runs."""
    plan = client.get_plan(plan_id)
    entries = plan.get("entries", [])

    all_runs = []
    for entry in entries:
        for run in entry.get("runs", []):
            run_data = fetch_run_data(client, run["id"])
            run_data["suite_name"] = entry.get("name", "")
            all_runs.append(run_data)

    # Aggregate totals
    total = sum(r["total"] for r in all_runs)
    passed = sum(r["passed"] for r in all_runs)
    failed = sum(r["failed"] for r in all_runs)
    blocked = sum(r["blocked"] for r in all_runs)
    untested = sum(r["untested"] for r in all_runs)
    retest = sum(r["retest"] for r in all_runs)
    executed = total - untested

    # Merge status counts
    merged_counts = {}
    for r in all_runs:
        for label, count in r["status_counts"].items():
            merged_counts[label] = merged_counts.get(label, 0) + count

    return {
        "plan_id": plan_id,
        "name": plan.get("name", f"Plan #{plan_id}"),
        "description": plan.get("description", ""),
        "url": plan.get("url", ""),
        "milestone": plan.get("milestone", None),
        "created_on": plan.get("created_on"),
        "is_completed": plan.get("is_completed", False),
        "total": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "untested": untested,
        "retest": retest,
        "executed": executed,
        "pass_rate": (passed / executed * 100) if executed > 0 else 0,
        "completion": (executed / total * 100) if total > 0 else 0,
        "status_counts": merged_counts,
        "runs": all_runs,
    }


def fetch_from_link(client: TestRailClient, url: str) -> dict:
    """High-level: parse a link and return plan or run data."""
    kind, entity_id = parse_testrail_link(url)
    if kind == "plan":
        data = fetch_plan_data(client, entity_id)
        data["type"] = "plan"
    else:
        data = fetch_run_data(client, entity_id)
        data["type"] = "run"
    return data
