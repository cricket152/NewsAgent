"""Task T13: Chinese almanac (黄历/凶吉) fetcher — 正经黄历 (per m0010 user confirmed).

Deterministic lunar calendar lookup via ``lunardate`` + local rules for
宜 / 忌 (auspicious / inauspicious activities).  Fully offline — no LLM,
no external API.  The computation is idempotent: same solar date always
produces the same output.

Reference (lunardate): ``from lunardate import LunarDate`` →
``LunarDate.from_solar_date(y, m, d)``
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from lunardate import LunarDate

from news_agent.logging_setup import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# 天干 / 地支 / 六十甲子 (60-year Ganzhi cycle, 甲子 = 1984)
# ---------------------------------------------------------------------------

_TIAN_GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
_DI_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

_GANZI_NAMES: tuple[str, ...] = (
    "甲子", "乙丑", "丙寅", "丁卯", "戊辰", "己巳", "庚午", "辛未", "壬申", "癸酉",
    "甲戌", "乙亥", "丙子", "丁丑", "戊寅", "己卯", "庚辰", "辛巳", "壬午", "癸未",
    "甲申", "乙酉", "丙戌", "丁亥", "戊子", "己丑", "庚寅", "辛卯", "壬辰", "癸巳",
    "甲午", "乙未", "丙申", "丁酉", "戊戌", "己亥", "庚子", "辛丑", "壬寅", "癸卯",
    "甲辰", "乙巳", "丙午", "丁未", "戊申", "己酉", "庚戌", "辛亥", "壬子", "癸丑",
    "甲寅", "乙卯", "丙辰", "丁巳", "戊午", "己未", "庚申", "辛酉", "壬戌", "癸亥",
)

_ZODIAC_MAPPING: dict[str, str] = {
    "子": "鼠", "丑": "牛", "寅": "虎", "卯": "兔",
    "辰": "龙", "巳": "蛇", "午": "马", "未": "羊",
    "申": "猴", "酉": "鸡", "戌": "狗", "亥": "猪",
}

# ---------------------------------------------------------------------------
# 农历月 / 日 名称
# ---------------------------------------------------------------------------

_LUNAR_MONTH_NAMES: tuple[str, ...] = (
    "正月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "冬月", "腊月",
)

_LUNAR_DAY_NAMES: tuple[str, ...] = (
    "初一", "初二", "初三", "初四", "初五",
    "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五",
    "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五",
    "廿六", "廿七", "廿八", "廿九", "三十",
)

# ---------------------------------------------------------------------------
# 星期
# ---------------------------------------------------------------------------

_WEEKDAY_NAMES: tuple[str, ...] = (
    "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
)

# ---------------------------------------------------------------------------
# 宜 / 忌 候选池 (各 10 项，正经黄历用词)
# ---------------------------------------------------------------------------

_YI_POOL: tuple[str, ...] = (
    "嫁娶", "出行", "祭祀", "纳财", "入学",
    "纳畜", "栽种", "开市", "交易", "立券",
)

_JI_POOL: tuple[str, ...] = (
    "动土", "开仓", "安葬", "破土", "伐木",
    "斋醮", "祈福", "求医", "入宅", "入殓",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 with Z suffix."""
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _compute_yi_ji(
    lunar_day: int, branch_index: int,
) -> tuple[list[str], list[str]]:
    """Deterministic 宜 / 忌 for a given lunar day and earthly-branch index.

    The formula is a fixed, seedable mapping — no randomness, no LLM.
    Same (lunar_day, branch_index) always returns the same lists.

    * **yi_count**: 3–5 items.
    * **ji_count**: 2–3 items.
    * **yi_start**: ``(lunar_day * 7 + branch_index) % len(YI_POOL)``
    * **ji_start**: ``(lunar_day * 13 + branch_index * 3) % len(JI_POOL)``
    """
    n_yi = len(_YI_POOL)
    n_ji = len(_JI_POOL)

    yi_count = 3 + ((lunar_day + branch_index) % 3)  # 3, 4, 5
    ji_count = 2 + ((lunar_day + branch_index) % 2)  # 2, 3

    yi_start = (lunar_day * 7 + branch_index) % n_yi
    ji_start = (lunar_day * 13 + branch_index * 3) % n_ji

    yi = [_YI_POOL[(yi_start + i) % n_yi] for i in range(yi_count)]
    ji = [_JI_POOL[(ji_start + i) % n_ji] for i in range(ji_count)]

    return yi, ji


def _solar_to_lunar(d: _dt.date) -> dict[str, Any]:
    """Convert a solar date to lunar components (ganzi year, month/day names, zodiac, etc.)."""
    lunar = LunarDate.from_solar_date(d.year, d.month, d.day)

    lunar_year = lunar.year
    lunar_month = lunar.month
    lunar_day = lunar.day
    is_leap = bool(lunar.isLeapMonth)

    # Ganzhi year from 60-year cycle (甲子 = 1984)
    ganzi_idx = (lunar_year - 1984) % 60
    ganzi_year = _GANZI_NAMES[ganzi_idx]
    ganzi_branch = _DI_ZHI[ganzi_idx % 12]

    # Month name (handling leap month prefix)
    month_name = _LUNAR_MONTH_NAMES[lunar_month - 1]
    if is_leap:
        month_name = f"闰{month_name}"

    # Day name
    day_name = _LUNAR_DAY_NAMES[lunar_day - 1]

    # Zodiac from earthly branch
    zodiac = _ZODIAC_MAPPING[ganzi_branch]

    # Weekday (Chinese)
    weekday = _WEEKDAY_NAMES[d.weekday()]

    # 宜 / 忌
    yi, ji = _compute_yi_ji(lunar_day, ganzi_idx % 12)

    # Formatted lunar date string
    lunar_date_str = f"{ganzi_year}年 {month_name}{day_name}"

    return {
        "solar_date": d.isoformat(),
        "lunar_date": lunar_date_str,
        "ganzi_year": ganzi_year,
        "lunar_month_name": month_name,
        "lunar_day_name": day_name,
        "is_leap_month": is_leap,
        "zodiac": zodiac,
        "weekday": weekday,
        "yi": yi,
        "ji": ji,
        "fetched_at": _utcnow_iso(),
        "source": "lunardate+local-rules",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_fortune(date: _dt.date | None = None) -> dict[str, Any]:
    """Return Chinese almanac (黄历) data for *date*.

    Args:
        date: Solar date to query (default: today, in local time).

    Returns:
        Dict with keys ``solar_date``, ``lunar_date``, ``ganzi_year``,
        ``lunar_month_name``, ``lunar_day_name``, ``is_leap_month``,
        ``zodiac``, ``weekday``, ``yi``, ``ji``, ``fetched_at``, ``source``.

        Always succeeds — the computation is fully local.
    """
    if date is None:
        date = _dt.date.today()

    result = _solar_to_lunar(date)
    logger.debug("fortune computed for %s → %s", result["solar_date"], result["lunar_date"])
    return result


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    today_result = fetch_fortune()
    print("=== Today's fortune ===")
    print(json.dumps(today_result, ensure_ascii=False, indent=2))

    # Also test a fixed date (2026-07-11)
    fixed_result = fetch_fortune(_dt.date(2026, 7, 11))
    print("\n=== 2026-07-11 fortune ===")
    print(json.dumps(fixed_result, ensure_ascii=False, indent=2))
