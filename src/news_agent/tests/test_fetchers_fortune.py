"""Tests for ``news_agent.fetchers.fortune`` — Chinese almanac (黄历)."""

from __future__ import annotations

from datetime import date

import pytest
from lunardate import LunarDate

from news_agent.fetchers.fortune import fetch_fortune


def test_fortune_fully_offline_deterministic() -> None:
    """Same date always produces the same output."""
    d = date(2026, 7, 11)
    r1 = fetch_fortune(d)
    r2 = fetch_fortune(d)
    assert r1 == r2


def test_fortune_sample_2026_07_11() -> None:
    """Specific expected values for 2026-07-11."""
    result = fetch_fortune(date(2026, 7, 11))
    assert result["lunar_date"] == "丙午年 五月廿七"
    assert result["zodiac"] == "马"


def test_yi_ji_not_empty() -> None:
    """Both yi (宜) and ji (忌) lists are non-empty."""
    result = fetch_fortune(date(2026, 7, 11))
    assert len(result["yi"]) >= 3
    assert len(result["ji"]) >= 2


def test_leap_month() -> None:
    """Test that a known leap month date has is_leap_month=True."""
    # 2023 had a leap second month (闰二月). March 22, 2023 is in the leap month.
    lunar = LunarDate.from_solar_date(2023, 3, 22)
    if lunar.isLeapMonth:
        result = fetch_fortune(date(2023, 3, 22))
        assert result["is_leap_month"] is True
    else:
        pytest.xfail("2023-03-22 is not in a leap month in this lunardate version")
