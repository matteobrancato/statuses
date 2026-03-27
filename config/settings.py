"""Configuration loader — reads static config and merges with runtime secrets."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "default_config.json"
_cached_config: dict[str, Any] | None = None


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and cache the static JSON configuration."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    config_path = path or _CONFIG_PATH
    with open(config_path) as f:
        _cached_config = json.load(f)
    logger.info("Configuration loaded from %s", config_path)
    return _cached_config


def get_bu_config(business_unit: str) -> dict[str, Any]:
    """Return config block for a specific business unit."""
    cfg = load_config()
    bus = cfg.get("business_units", {})
    if business_unit not in bus:
        raise KeyError(
            f"Business unit '{business_unit}' not found. "
            f"Available: {list(bus.keys())}"
        )
    return bus[business_unit]


def get_bu_names() -> list[str]:
    """Return list of all configured business unit names."""
    return list(load_config().get("business_units", {}).keys())


def get_status_map() -> dict[str, dict[str, str]]:
    """Return the status_id → label/color mapping."""
    return load_config().get("status_map", {})


def get_regression_keywords() -> list[str]:
    """Return keywords used to identify regression runs."""
    return load_config().get("regression_keywords", [])


def get_smoke_keywords() -> list[str]:
    """Return keywords used to identify smoke runs."""
    return load_config().get("smoke_keywords", [])


def get_lookback_days() -> int:
    """Return how many days back to consider for active regressions."""
    return load_config().get("regression_lookback_days", 30)


def get_automation_type_map() -> dict[str, str]:
    """Return automation type → classification mapping."""
    return load_config().get("automation_type_map", {})
