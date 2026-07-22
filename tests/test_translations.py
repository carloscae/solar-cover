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
        assert buttons["reset_override"]["name"] == "{cover} reset override"


def test_cover_intent_distinct_from_zone_intent_in_both_files() -> None:
    # Per-cover sensors share the zone device now, so "intent" (zone) and
    # "cover_intent" (per-cover) must be separate translation keys with
    # separate names, or two entities on the same device would render
    # identically in the UI.
    for name in ("strings.json", "translations/en.json"):
        sensors = _load(name)["entity"]["sensor"]
        assert sensors["intent"]["name"] == "Active intent"
        assert sensors["cover_intent"]["name"] == "{cover} active intent"
        assert sensors["cover_intent"]["state"] == sensors["intent"]["state"]


def test_inactive_weather_label_is_action_neutral_in_both_files() -> None:
    # The label must not assume "retracted" -- a zone can be configured to
    # close instead. The specific action lives in the reason sensor text.
    for name in ("strings.json", "translations/en.json"):
        sensors = _load(name)["entity"]["sensor"]
        assert sensors["intent"]["state"]["inactive_weather"] == "Weather safety"
        assert sensors["cover_intent"]["state"]["inactive_weather"] == "Weather safety"


def test_weather_action_selector_options_present_in_both_files() -> None:
    from custom_components.solar_cover.const import WeatherAction

    for name in ("strings.json", "translations/en.json"):
        options = _load(name)["selector"]["weather_action"]["options"]
        assert set(options) == {e.value for e in WeatherAction}


def test_cover_type_and_tilt_range_selector_options_present_in_both_files() -> None:
    from custom_components.solar_cover.const import CoverType, TiltRange

    for name in ("strings.json", "translations/en.json"):
        selectors = _load(name)["selector"]
        assert set(selectors["cover_type"]["options"]) == {e.value for e in CoverType}
        assert set(selectors["tilt_range"]["options"]) == {e.value for e in TiltRange}
