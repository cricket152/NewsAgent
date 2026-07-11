"""Curator: orchestrates fetchers + DeepSeek LLM to build a daily bundle for the viewer.

Receives a Config, calls each fetcher per source, dedupes by URL, takes top 5 per
domain, requests 50字 AI summaries from DeepSeek, builds a 100字 daily summary, and
returns a single dict ready for Jinja2 rendering.

Never raises. Returns a dict with ``headlines_only_mode=True`` on cost ceiling or
LLM failure.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from news_agent.config import Config, SourceEntry
from news_agent.llm import (
    CostCeilingExceeded,
    chat,
    get_today_remaining_tokens,
)
from news_agent.logging_setup import get_logger

logger = get_logger()

MAX_ARTICLES_PER_DOMAIN = 5

# ── AI prompt templates ──────────────────────────────────────────────────────

_ARTICLE_SUMMARY_SYSTEM = (
    "你是一个新闻编辑助手。请将用户提供的新闻标题和摘要改写为50字以内的中文精炼摘要。"
    "只输出摘要文本，不要解释、不要前缀。"
)

_DAILY_SUMMARY_SYSTEM = (
    "你是一个新闻编辑助手。请基于用户提供的今日新闻标题列表，用100字以内的中文总结今天"
    "最值得关注的话题。只输出总结文本，不要前缀不要列表格式。"
)


# ── private helpers ──────────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 with Z suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _dispatch_fetcher(
    source: SourceEntry, config: Config
) -> list[dict[str, Any]]:
    """Dispatch a single source entry to the correct fetcher function.

    Returns an empty list on unknown type or fetcher failure — never raises.
    """
    try:
        if source.type == "rss":
            from news_agent.fetchers.rss import fetch_rss

            return fetch_rss(source)
        elif source.type == "rsshub":
            from news_agent.fetchers.rsshub import fetch_rsshub

            return fetch_rsshub(source, rsshub_url=config.rsshub_url)
        elif source.type == "html":
            from news_agent.fetchers.html_src import fetch_html

            return fetch_html(source)
        elif source.type == "api":
            from news_agent.fetchers.bangumi import fetch_bangumi

            return fetch_bangumi(source)
        elif source.type == "mediawiki_api":
            from news_agent.fetchers.mediawiki import fetch_mediawiki_recent

            return fetch_mediawiki_recent(source)
        else:
            logger.warning(
                "Unknown source type '%s' for %s", source.type, source.url
            )
            return []
    except Exception:
        logger.exception(
            "fetcher failed: source=%s type=%s", source.url, source.type
        )
        return []


def _make_emergency_fortune() -> dict[str, Any]:
    """Return a minimal fallback fortune dict used when everything else fails."""
    return {
        "solar_date": "",
        "lunar_date": "",
        "ganzi_year": "",
        "lunar_month_name": "",
        "lunar_day_name": "",
        "is_leap_month": False,
        "zodiac": "",
        "weekday": "",
        "yi": [],
        "ji": [],
        "fetched_at": _utcnow_iso(),
        "source": "emergency-fallback",
    }


# ── public API ───────────────────────────────────────────────────────────────


def run_curator(
    config: Config, db_path: Path | str | None = None
) -> dict[str, Any]:
    """Orchestrate fetchers + DeepSeek LLM to produce a daily curated bundle.

    Args:
        config: Application configuration (sources, weather city, RSSHub URL,
            cost ceiling, etc.).
        db_path: Path to SQLite state database for token-tracking.  When
            ``None``, cost-ceiling checks are skipped and token usage is not
            recorded (useful for smoke tests / offline runs).

    Returns:
        A dict with keys ``articles_by_domain``, ``weather``, ``fortune``,
        ``daily_summary``, ``headlines_only_mode``, and ``fetched_at``.

        Never raises — returns a minimally valid dict on total failure.
    """
    if isinstance(db_path, str):
        db_path = Path(db_path)

    try:
        return _run_curator_impl(config, db_path)
    except Exception:
        logger.critical("run_curator crashed", exc_info=True)
        return {
            "articles_by_domain": {},
            "weather": None,
            "fortune": _make_emergency_fortune(),
            "daily_summary": "",
            "headlines_only_mode": True,
            "fetched_at": _utcnow_iso(),
        }


# ── implementation ───────────────────────────────────────────────────────────


def _run_curator_impl(
    config: Config, db_path: Path | None
) -> dict[str, Any]:
    # 1. Timestamp
    fetched_at = _utcnow_iso()

    # 2. Fetch non-article channels first (fortune is offline, weather may fail)
    try:
        from news_agent.fetchers.fortune import fetch_fortune

        fortune: dict[str, Any] = fetch_fortune(None)
    except Exception:
        logger.warning("fortune fetch failed", exc_info=True)
        fortune = _make_emergency_fortune()

    try:
        from news_agent.fetchers.weather import fetch_weather

        weather: dict[str, Any] | None = fetch_weather(
            config.weather_city, timeout=5.0
        )
    except Exception:
        logger.warning("weather fetch failed", exc_info=True)
        weather = None

    # 3. Fetch articles per source
    articles_by_domain_raw: defaultdict[str, list[dict[str, Any]]] = (
        defaultdict(list)
    )

    for source in config.sources:
        entries = _dispatch_fetcher(source, config)
        for article in entries:
            articles_by_domain_raw[article["domain"]].append(article)

    # 4. Aggregate by domain: dedupe, sort, truncate
    seen_urls: set[str] = set()
    articles_by_domain: dict[str, list[dict[str, Any]]] = {}

    for domain, articles in articles_by_domain_raw.items():
        unique: list[dict[str, Any]] = []
        for article in articles:
            url_key = article["url"].lower().strip()
            if url_key and url_key not in seen_urls:
                seen_urls.add(url_key)
                unique.append(article)

        # Sort by published_at descending; empty strings sort last
        unique.sort(
            key=lambda a: (a["published_at"] != "", a["published_at"] or ""),
            reverse=True,
        )

        articles_by_domain[domain] = unique[:MAX_ARTICLES_PER_DOMAIN]

    # Flatten domain lists for LLM iteration (preserve domain grouping)
    flat_articles: list[dict[str, Any]] = []
    for domain in sorted(articles_by_domain):
        flat_articles.extend(articles_by_domain[domain])

    # 5. LLM AI summaries
    headlines_only_mode = False

    if db_path is not None and get_today_remaining_tokens(db_path) <= 0:
        logger.warning(
            "Daily token ceiling exhausted — skipping all LLM summarisation"
        )
        headlines_only_mode = True

    if not headlines_only_mode:
        for article in flat_articles:
            messages: list[dict[str, str]] = [
                {"role": "system", "content": _ARTICLE_SUMMARY_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"标题: {article['title']}\n"
                        f"原始摘要: {article['summary'][:300]}\n"
                        "50字摘要:"
                    ),
                },
            ]
            try:
                ai_summary = chat(
                    messages,
                    temperature=0.3,
                    max_tokens=200,
                    db_path=db_path,
                )
                article["ai_summary"] = ai_summary.strip()
            except CostCeilingExceeded:
                logger.warning(
                    "Cost ceiling exceeded during article summarisation — "
                    "headlines-only mode from now on"
                )
                headlines_only_mode = True
                article["ai_summary"] = ""
            except Exception:
                logger.exception(
                    "LLM article summary failed for %s", article["title"][:60]
                )
                article["ai_summary"] = ""

        # Fill ai_summary for articles not yet processed (when aborted mid-loop)
        for article in flat_articles:
            if "ai_summary" not in article:
                article["ai_summary"] = ""
    else:
        # Cost ceiling exhausted from the start — blank all ai_summary fields
        for article in flat_articles:
            article["ai_summary"] = ""

    # 6. Daily overall summary (only when NOT headlines_only_mode)
    daily_summary = ""

    if not headlines_only_mode and flat_articles:
        # Collect up to 3 titles per domain (max ~15 total)
        titles: list[str] = []
        for domain in sorted(articles_by_domain):
            domain_articles = articles_by_domain[domain]
            for article in domain_articles[:3]:
                titles.append(article["title"])

        if titles:
            daily_messages: list[dict[str, str]] = [
                {"role": "system", "content": _DAILY_SUMMARY_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"今日新闻标题:\n{chr(10).join(titles)}\n100字总结:"
                    ),
                },
            ]
            try:
                daily_summary = chat(
                    daily_messages,
                    temperature=0.5,
                    max_tokens=400,
                    db_path=db_path,
                ).strip()
            except CostCeilingExceeded:
                logger.warning(
                    "Cost ceiling exceeded during daily summary — skipping"
                )
                headlines_only_mode = True
                daily_summary = ""
            except Exception:
                logger.exception("LLM daily summary failed")
                daily_summary = ""

    # 7. Construct return dict
    return {
        "articles_by_domain": articles_by_domain,
        "weather": weather,
        "fortune": fortune,
        "daily_summary": daily_summary,
        "headlines_only_mode": headlines_only_mode,
        "fetched_at": fetched_at,
    }


# ── smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import os

    from news_agent.config import Config, get_default_config

    # Only use real sources when explicitly opted in via env var
    if os.environ.get("NEWS_AGENT_LIVE"):
        config = get_default_config()
        print("Live mode — using default sources (may make network calls)")
    else:
        config = Config(sources=[])
        print("Smoke mode — empty sources, no network calls")

    result = run_curator(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
