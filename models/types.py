"""Typed data structures for the regression dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StatusCounts:
    """Counts of tests by status."""
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    retest: int = 0
    untested: int = 0
    custom: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return (
            self.passed + self.failed + self.blocked
            + self.retest + self.untested
            + sum(self.custom.values())
        )

    @property
    def executed(self) -> int:
        return self.total - self.untested

    @property
    def progress(self) -> float:
        return (self.executed / self.total * 100) if self.total else 0.0

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.executed * 100) if self.executed else 0.0

    def merge(self, other: StatusCounts) -> StatusCounts:
        """Return a new StatusCounts summing both."""
        merged_custom: dict[str, int] = {**self.custom}
        for k, v in other.custom.items():
            merged_custom[k] = merged_custom.get(k, 0) + v
        return StatusCounts(
            passed=self.passed + other.passed,
            failed=self.failed + other.failed,
            blocked=self.blocked + other.blocked,
            retest=self.retest + other.retest,
            untested=self.untested + other.untested,
            custom=merged_custom,
        )

    def to_distribution(self, status_map: dict[str, dict[str, str]]) -> dict[str, int]:
        """Return a {label: count} dict for all non-zero statuses."""
        dist: dict[str, int] = {}
        base = {"Passed": self.passed, "Failed": self.failed, "Blocked": self.blocked,
                "Retest": self.retest, "Untested": self.untested}
        for label, count in base.items():
            if count:
                dist[label] = count
        for label, count in self.custom.items():
            if count:
                dist[label] = count
        return dist


@dataclass
class RunData:
    """Parsed data for a single TestRail run."""
    id: int
    name: str
    url: str
    is_completed: bool
    country: str = "unknown"
    platform: str = "unknown"
    run_type: str = "unknown"
    counts: StatusCounts = field(default_factory=StatusCounts)

    @property
    def status(self) -> str:
        return "completed" if self.is_completed else "active"


@dataclass
class AutomationBreakdown:
    """Breakdown of automated test types."""
    java: int = 0
    testim_desktop: int = 0
    testim_mobile: int = 0

    @property
    def total(self) -> int:
        return self.java + self.testim_desktop + self.testim_mobile


@dataclass
class CoverageData:
    """Baseline coverage information."""
    total: int = 0
    regression: int = 0
    automated_total: int = 0
    automation_breakdown: AutomationBreakdown = field(default_factory=AutomationBreakdown)

    @property
    def coverage_pct(self) -> float:
        return (self.automated_total / self.regression * 100) if self.regression else 0.0


@dataclass
class PlanData:
    """Aggregated data for a TestRail plan."""
    id: int
    name: str
    url: str
    runs: list[RunData] = field(default_factory=list)
    counts: StatusCounts = field(default_factory=StatusCounts)

    @property
    def is_active(self) -> bool:
        return any(not r.is_completed for r in self.runs)


@dataclass
class DashboardResult:
    """Final output structure for get_regression_dashboard()."""
    business_unit: str
    active_regression: bool
    coverage: CoverageData
    runs: dict  # nested: country → platform → type → run stats
