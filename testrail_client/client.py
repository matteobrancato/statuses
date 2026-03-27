"""TestRail API client with retries, pagination, and rate-limit safety."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 250
_MAX_RETRIES = 3
_BACKOFF_FACTOR = 1.0
_RATE_LIMIT_SLEEP = 2.0


class TestRailClient:
    """Reusable TestRail API v2 client."""

    def __init__(self, base_url: str, user: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.auth = (user, api_key)
        self._session.headers.update({"Content-Type": "application/json"})

        # Automatic retries with exponential backoff
        retry = Retry(
            total=_MAX_RETRIES,
            backoff_factor=_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ── Core request ────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a GET request against the TestRail API."""
        url = f"{self._base_url}/index.php?/api/v2/{endpoint}"
        resp = self._session.get(url, params=params, timeout=30)

        # Handle rate-limiting explicitly
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", _RATE_LIMIT_SLEEP))
            logger.warning("Rate limited — sleeping %ds", retry_after)
            time.sleep(retry_after)
            return self._get(endpoint, params)

        resp.raise_for_status()
        return resp.json()

    def _get_paginated(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Fetch all pages of a paginated endpoint."""
        results: list[dict] = []
        offset = 0
        params = dict(params or {})

        while True:
            params["limit"] = _DEFAULT_PAGE_SIZE
            params["offset"] = offset
            data = self._get(endpoint, params)

            # API v2 wraps paginated results
            if isinstance(data, dict):
                items = data.get("tests") or data.get("results") or data.get("cases") or data.get("plans") or data.get("runs") or []
                results.extend(items)
                if data.get("_links", {}).get("next") is None:
                    break
                offset += _DEFAULT_PAGE_SIZE
            elif isinstance(data, list):
                results.extend(data)
                break
            else:
                break

        return results

    # ── Public API ──────────────────────────────────────────────────────

    def get_plan(self, plan_id: int) -> dict:
        """Fetch a single test plan with its entries."""
        return self._get(f"get_plan/{plan_id}")

    def get_plans(self, project_id: int, created_after: int | None = None) -> list[dict]:
        """Fetch test plans for a project, optionally filtered by creation date."""
        params: dict[str, Any] = {}
        if created_after is not None:
            params["created_after"] = created_after
        return self._get_paginated(f"get_plans/{project_id}", params=params)

    def get_run(self, run_id: int) -> dict:
        """Fetch a single test run."""
        return self._get(f"get_run/{run_id}")

    def get_runs(self, project_id: int) -> list[dict]:
        """Fetch all runs for a project."""
        return self._get_paginated(f"get_runs/{project_id}")

    def get_tests(self, run_id: int) -> list[dict]:
        """Fetch all tests for a run (paginated)."""
        return self._get_paginated(f"get_tests/{run_id}")

    def get_cases(self, project_id: int, suite_id: int) -> list[dict]:
        """Fetch all test cases for a project/suite (paginated)."""
        return self._get_paginated(
            f"get_cases/{project_id}", params={"suite_id": suite_id}
        )

    def get_results_for_run(self, run_id: int) -> list[dict]:
        """Fetch all test results for a run (paginated)."""
        return self._get_paginated(f"get_results_for_run/{run_id}")

    def get_case_fields(self) -> list[dict]:
        """Fetch all case field definitions (includes custom fields with options)."""
        return self._get("get_case_fields")

    def get_statuses(self) -> list[dict]:
        """Fetch all test status definitions (built-in + custom)."""
        return self._get("get_statuses")
