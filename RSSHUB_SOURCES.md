# RSSHub Sources

Local RSSHub is the primary source for Bilibili/Weibo/NGA content.
**Public instances are unreliable and rate-limited — do not depend on them for production.**
Always start the local Docker container (`scripts/start-rsshub.ps1`) before running the worker.

---

## Routes Used by news-agent

All routes below are served by the local RSSHub instance at `http://localhost:1200`.
Replace `:uid` / `:fid` / `:category` placeholders with actual IDs during Wave 2 T9 implementation.

### AI / 科技

| Route | Description |
|-------|-------------|
| `/36kr/motif/:category` | 36kr themed articles by category |
| `/solidot/all` | Solidot latest tech news |
| `/chinadigitaltimes/multi` | Chinese Digital Times aggregated feed |

### 编程 / 开源

| Route | Description |
|-------|-------------|
| `/github/trending/:since/:language` | GitHub trending repos (e.g. `/github/trending/daily/python`) |
| `/v2ex/topics/:tab` | V2EX topics by tab (e.g. `/v2ex/topics/tech`) |

### 明日方舟

| Route | Description |
|-------|-------------|
| `/bilibili/user/dynamic/:uid` | Bilibili user dynamic feed — TODO: replace `:uid` with actual Arknights official account UIDs (e.g. `USTC_Vagabond`, 鹰角网络 official) |
| `/bilibili/partion/24` | Bilibili anime/MAD partition (动漫区) |
| `/nga/forum/:fid` | NGA forum posts — TODO: replace `:fid` with Arknights board ID (e.g. `607` for 明日方舟板) |

### 百合 + MAD/漫剪

| Route | Description |
|-------|-------------|
| `/bilibili/partion/24` | Bilibili anime/MAD partition (动漫区) |

> **Note on dmhy**: Use native dmhy RSS feed (`https://dmhy.org/topics/rss/rss.xml?keyword=百合`) instead of RSSHub — dmhy provides a standard RSS endpoint directly.
>
> **Note on Bangumi**: Use the Bangumi API directly (`https://api.bgm.tv/v0/subjects?type=2&tag=百合`) instead of RSSHub — Bangumi has a free, no-auth REST API.
>
> **Note on Bilibili zone vs partion**: The RSSHub route `/bilibili/partion/24` covers the 动漫区 (MAD/anime) category. For sub-zone filtering, check RSSHub docs at https://docs.rsshub.app/routes/social-media#bilibili for available parameters.

---

## Public Fallback Instances

> **⚠️ Last resort only.** Public instances may rate-limit, drop requests, or change routes without notice.
> Always run local Docker for production.

| # | Instance URL | Status |
|---|-------------|--------|
| 1 | <https://rsshub.app> | Official public instance — strict rate limiting |
| 2 | <https://rsshub.rssforever.com> | Community-maintained, may have uptime variance |
| 3 | <https://rsshub.feeded.xyz> | Community-maintained, route coverage may differ |

> **Note on fallback strategy** (implemented in Wave 2 T9 `src/fetchers/rsshub.py`):
> The fetcher attempts local RSSHub first; on failure, it iterates through the fallback list above.
> If all instances fail, the worker logs the error and returns an empty result set — it never crashes.

---

## How to Use

```powershell
# Start (idempotent — re-runs are safe)
.\scripts\start-rsshub.ps1

# Stop
.\scripts\stop-rsshub.ps1
```

After starting, verify with:

```powershell
curl http://localhost:1200
```

For route reference and parameter details, see the official RSSHub documentation at <https://docs.rsshub.app/>.

---

For personal use only under fair use. See `README.md` disclaimer.
