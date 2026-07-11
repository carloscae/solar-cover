"""Tests that button translation keys exist and match between strings and en.json."""

from __future__ import annotations

import json
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent / "custom_components" / "solar_cover"


def _load(name: str) -> dict:
    return json.loads((_BASE / name).read_text(encoding="utf-8"))


def test_reset_all_label_present_in_both_files() -> None:
    for name in ("strings.json", "translations/en.json"):
        buttons = _load(name)["entity"]["button"]
        assert buttons["reset_timers"]["name"] == "Reset all"


def test_reset_override_label_present_in_both_files() -> None:
    for name in ("strings.json", "translations/en.json"):
        buttons = _load(name)["entity"]["button"]
        assert buttons["reset_override"]["name"] == "Reset override"
