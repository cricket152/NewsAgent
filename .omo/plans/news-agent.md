# News Agent — 开机日报 + 常驻对话 Agent

## TL;DR

> **Quick Summary**: 双进程 Windows 桌面 Agent — 主进程 pywebview 托盘常驻可对话，Worker 进程每日 2 次抓取 4 类兴趣领域新闻经 DeepSeek 筛选摘要后写入 SQLite，开机自动弹出当日播报窗口（新闻+天气+正经黄历凶吉），关掉后转托盘快捷键唤回。
>
> **Deliverables**:
> - 双进程架构（主进程 pywebview + Worker 纯 CLI），SQLite WAL 通信
> - 4 类兴趣源抓取器（AI/科技、编程/开源、明日方舟、百合+MAD/漫剪），RSSHub-first
> - DeepSeek `deepseek-v4-flash` 筛选+摘要+对话，50K tokens/day 成本上限
> - 开机自启动（HKCU Run key + pythonw.exe），托盘+快捷键唤出窗口
> - 正经黄历凶吉（lunardate）、open-meteo 天气（含超时回退）
> - PyInstaller 打包 + 卸载流程 + 完整测试
>
> **Estimated Effort**: Large
> **Parallel Execution**: YES - 5 waves + final
> **Critical Path**: Task 1 → 6 → 9 → 14 → 15 → 20 → 22 → F1-F4

---

## Context

### Original Request

用户想要一个 agent 项目，每天从用户感兴趣的栏目在网络上搜寻好材料，整理后每天电脑开机时弹出一个窗口，包含感兴趣栏目的新闻资讯、天气、凶吉等信息。后升级为常驻后台可交互 Agent + 分布式多 Agent 架构（新闻内容由另一个 worker 进程完成，通过 skill 配置兴趣领域和爬取站点）。

### Interview Summary

**Key Discussions**:
- **进程拓扑**: 双进程 + SQLite 中转。主进程常驻轻量响应对话，Worker 独立进程抓取+LLM 处理，两进程通过 SQLite 表通信。
- **交互 UX**: 托盘+快捷键唤出窗口。开机自启动，开机直接弹出当日播报窗口，关掉后转托盘常驻，快捷键唤回。pywebview (Edge WebView2) + HTML/CSS/JS。
- **LLM 策略**: 纯云 API，厂商 DeepSeek，模型 `deepseek-v4-flash`（`deepseek-chat` 2026-07-24 退役），每日 50K token 成本上限超额降级。
- **新闻 Agent skill**: 重 prompt 型，兴趣领域固定 4 类（AI/科技前沿、编程/开源、明日方舟、百合+MAD/漫剪），站点白名单见 config.yaml，抓取频率每日 2 次（6AM + 18PM）。
- **凶吉**: 正经黄历（lunardate 本地库），不走 AI 趣版。
- **测试策略**: Tests-after + Agent QA（pytest + pytest-asyncio + pytest-httpx，不设 TDD）。

**Research Findings**:
- DeepSeek `deepseek-chat` 2026-07-24 退役，必须用 `deepseek-v4-flash`
- pywebview 两进程不能共享 WebView2（Issue #1387）— 验证了双进程架构
- Startup folder 有 10 分钟延迟 — 必须用 Registry Run key
- pywebview 冷启动 4 秒+ — 需要 <1000ms splash
- Bilibili 直爬需 wbi 签名且有法律风险 — 必须 RSSHub-first
- Bangumi API (api.bgm.tv) 免费无认证，完美适配百合/GL
- dmhy RSS 标准可用；PRTS Wiki (prts.wiki) 无 CloudFlare 可爬

### Metis Review

**Identified Gaps** (addressed):
- 模型名未指定 → 硬编码 `deepseek-v4-flash`
- 自启动机制 → Registry HKCU Run key + pythonw.exe + --autostart flag
- 抓取策略 → RSSHub-first（本地 docker-compose + 公共实例 fallback）
- SQLite 并发 → WAL + busy_timeout=5000 + 主进程只读连接
- 12 项 scope creep → 全部列入 MUST NOT HAVE
- 10 项实现决策 → 作为 Defaults Applied 记录
- 16 项 edge case → QA 场景必须覆盖
- Worker 超时 → cross-platform watchdog（非 signal.alarm，Unix-only）

---

## Work Objectives

### Core Objective

构建一个 Windows 桌面双进程 Agent：Worker 进程每日 2 次抓取 4 类兴趣领域新闻经 DeepSeek 筛选摘要后写入 SQLite，主进程常驻系统托盘可对话，开机自动弹出当日播报窗口（新闻+天气+正经黄历），关掉后快捷键唤回。

### Concrete Deliverables

- `.omo/plans/news-agent.md` 本计划文件
- `news-agent/` 完整项目目录
  - `pyproject.toml` — Python 项目配置 + 依赖
  - `config.yaml` — 完整配置 schema（api_key_ref / sources / cost_ceiling / weather_city / hotkey / window_position）
  - `src/` — 核心代码（fetchers/ curator/ fortune/ renderer/ viewer/ tray/ main.py worker.py）
  - `templates/daily.html` — Jinja2 播报页面模板
  - `tests/` — pytest 测试套件
  - `scripts/` — Task Scheduler 注册 + 卸载脚本
  - `docker/rsshub-docker-compose.yml` — 本地 RSSHub
  - `news-agent.spec` — PyInstaller 打包配置

### Definition of Done

- [ ] 双进程可独立运行，Worker 崩溃不影响主进程
- [ ] 开机弹出播报窗口，关掉转托盘，快捷键唤回
- [ ] 4 类兴趣源每日 2 次抓取 + DeepSeek 摘要写入 SQLite
- [ ] 天气 + 正经黄历显示正常
- [ ] 可与 Agent 对话（DeepSeek），50K token 上限触发降级
- [ ] PyInstaller 打包后可独立运行（无需 Python 环境）
- [ ] 卸载脚本清理所有残留（Run key + %APPDATA% + Task Scheduler）
- [ ] 所有测试通过 + Agent QA 场景通过

### Must Have

- 双进程架构（主进程 pywebview 托盘 + Worker 纯 CLI），SQLite WAL 通信
- 开机自启动（HKCU Run key + pythonw.exe + --autostart flag）
- 4 类兴趣领域抓取器（RSSHub-first for B站/微博/NGA）
- DeepSeek `deepseek-v4-flash`（thinking disabled，exp backoff，50K token 上限）
- 正经黄历（lunardate 本地库）
- open-meteo 天气（5s 超时，"无法获取天气"回退）
- 系统托盘（pystray）+ 快捷键（Ctrl+Alt+N）唤出
- 单例（Windows named mutex `Global\NewsAgentTray`）
- close=hide 不 destroy；WM_QUERYENDSESSION 存状态
- <1000ms splash 覆盖 WebView2 4s 冷启动
- SQLite WAL + busy_timeout=5000 + schema_version
- 所有时间戳内部 UTC，显示转本地
- Python logging → %APPDATA%/news-agent/logs/，7 天轮转
- 额度超限降级为 headlines-only，对话提示"今日额度已用完"
- PyInstaller frozen exe（--noconsole --windowed --collect-all webview + explicit DLLs）
- 卸载流程（删 Run key + %APPDATA% + Start Menu 快捷方式 + Task Scheduler 任务）
- URL 永久去重 + 3 天内标题相似聚类
- 对话历史 SQLite conversations 表，30 天保留，~64K token 截断
- API key keyring + Credential Manager，fallback .env restricted ACL
- 16 项 edge case 全部覆盖（见 Verification Strategy）

### Must NOT Have (Guardrails)

原 5 项：
- 本地模型部署（纯云 API）
- 部署为多用户 SaaS
- 移动端
- 语音交互
- AI 趣版凶吉（只做正经黄历）

Metis 12 项 scope creep：
1. NewsSource 抽象基类 — 4 域~10 固定源，YAML 配置驱动，勿 OOP 层级
2. config hot-reload/watchdog — 改配置重启即可
3. 插件系统 — 个人工具非平台
4. auth/RBAC — 单机单用户
5. web dashboard/Flask — UI 仅 pywebview 托盘弹窗
6. i18n — 中文专用
7. analytics charts/Matplotlib — 非需求
8. auto-updater — V1 不需要
9. full Markdown renderer — chat 纯文本 + 基础格式够用
10. vector DB/RAG/ChromaDB — 新闻聚合+聊天非文档 QA
11. parallel multi-workers — 2 次/日~10 源，串行 httpx 够快，并行增加封 IP 风险
12. smart recommendation algorithm — 评分规则在 prompt 里，无需 ML

AI slop patterns to avoid:
- 过度抽象（4 个源不需要 ABC 继承体系）
- 过度注释（JSDoc/docstring 泛滥）
- 通用命名（data/result/item/temp）
- 过度验证（3 个输入不需要 15 个错误检查）

### Spec Framework Integration

无 SDD framework 检测到（空目录全新项目）。

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** - ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: NO（全新项目）
- **Automated tests**: YES（Tests-after）
- **Framework**: pytest + pytest-asyncio + pytest-httpx
- **Test 策略**: 不设 TDD（防 infra 不足卡进度）；实现后写测试覆盖核心路径

### QA Policy

Every task MUST include agent-executed QA scenarios.
Evidence saved to `.omo/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Frontend/UI**: Playwright — 导航、交互、断言 DOM、截图
- **CLI/TUI**: tmux/Bash — 运行命令、校验输出、检查退出码
- **API/Backend**: Bash (curl / python -c) — 发请求、断言状态+响应字段
- **DB**: Bash (sqlite3) — 查询表结构、数据、PRAGMA
- **Registry**: Bash (reg query) — 检查 Run key / StartupApproved
- **Process**: Bash (tasklist / wmic) — 检查进程状态、PID、mutex
- **LLM**: Bash (python -c real DeepSeek call) — 验证 API 调用、cost tracking
- **Packaging**: Bash (PyInstaller build + exe run) — 验证 frozen exe 运行

### 16 Edge Cases (QA scenarios MUST cover)

1. 开机无网 → 显示缓存 + "上次更新:X小时前"，Worker 静默退出
2. API key 失效 → 托盘通知"API Key 已失效"，不崩溃
3. DeepSeek 7+ 小时中断 → headlines-only，对话优雅降级
4. 多日不开机 → StartWhenAvailable 触发 Worker，不回填历史，弹窗"已X天未获取新闻"
5. Worker 重叠 → PID lock + 15min 超时强制释放
6. SQLite 锁（WAL 后仍可能）→ retry 3x 5s 间隔，log 后 exit
7. 时钟跳跃 → 内部 UTC 不受影响
8. 磁盘满 → stderr + clean exit，UI 警告，30 天文章保留自动删
9. 杀软杀进程 → frozen 签名 exe（如可能），5min heartbeat log
10. 多用户 Windows 登录 → per-user %APPDATA%，HKCU per-user，无跨用户干扰
11. 高 DPI 125%/150%/200% → HTML rem/em，Playwright 模拟
12. PyInstaller 缺 WebView2Loader.dll → --collect-all webview + explicit DLLs
13. config 损坏 → try/except 加载，fallback 默认，不崩溃
14. 源 HTML 变更 → 日志"selector returned 0"，不崩溃
15. RSSHub 宕 → 本地 docker-compose 主，公共实例 fallback
16. python.exe 控制台闪 → Run key 必须 pythonw.exe

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation + scaffolding, 7 parallel):
├── 1. Project scaffolding + pyproject.toml + config.yaml schema [quick]
├── 2. DB schema + init module (WAL, busy_timeout, schema_version) [quick]
├── 3. Logging module + %APPDATA% paths [quick]
├── 4. API key management (keyring + Credential Manager + .env fallback) [quick]
├── 5. DeepSeek client wrapper (v4-flash, thinking disabled, backoff, cost ceiling) [deep]
├── 6. RSSHub docker-compose + config [quick]
├── 7. Config loader + validator (try/except, fallback default) [quick]

Wave 2 (After Wave 1 - fetchers, 6 parallel):
├── 8. Fetcher: RSS via feedparser (HN, GitHub trending, dmhy) [quick]
├── 9. Fetcher: RSSHub via httpx (Bilibili, Weibo, NGA终末地) [quick]
├── 10. Fetcher: HTML via bs4 (PRTS Wiki) [quick]
├── 11. Fetcher: Bangumi API (api.bgm.tv, Yuri/GL) [quick]
├── 12. Fetcher: open-meteo weather (5s timeout, fallback) [quick]
├── 13. Fortune module (lunardate 正经黄历) [quick]

Wave 3 (After Wave 2 - processing + template, 3 parallel):
├── 14. Curator: dedup + scoring + top N + 50-word summary (depends: 2,5,8-13) [deep]
├── 15. Worker process entry (PID lock, watchdog, orchestrate fetch→curate→SQLite) (depends: 2,6,8-13,14) [deep]
├── 16. HTML template (Jinja2 daily.html: news+weather+fortune+chat) [visual-engineering]

Wave 4 (After Wave 3 - UI + main process, 5 parallel):
├── 17. pywebview viewer (Edge WebView2 detect, splash, singleton, close=hide, WM_QUERYENDSESSION) (depends: 16) [visual-engineering]
├── 18. System tray (pystray, hotkey Ctrl+Alt+N, tray menu) (depends: 17) [quick]
├── 19. Conversation Agent (chat history SQLite, 30-day retention, context truncation, DeepSeek chat) (depends: 2,5) [deep]
├── 20. Main process entry (orchestrate tray+viewer+--autostart+single instance) (depends: 17,18,19) [deep]
├── 21. Windows autostart module (HKCU Run key, pythonw.exe, StartupApproved clear) (depends: 20) [quick]

Wave 5 (After Wave 4 - integration + packaging + tests, 4 parallel):
├── 22. Task Scheduler registration (schtasks, StartWhenAvailable) (depends: 15,21) [quick]
├── 23. PyInstaller packaging (spec, --noconsole --windowed --collect-all webview, DLLs) (depends: 20,22) [unspecified-high]
├── 24. Uninstall flow (delete Run key+%APPDATA%+Start Menu+Task Scheduler) (depends: 21,22) [quick]
├── 25. Tests suite (pytest + pytest-asyncio + pytest-httpx, per-domain) (depends: all impl) [unspecified-high]

Wave FINAL (After ALL — 4 parallel reviews):
├── F1. Plan compliance audit (oracle)
├── F2. Code quality review (unspecified-high)
├── F3. Real manual QA (unspecified-high + playwright)
├── F4. Scope fidelity check (deep)

Critical Path: Task 1 → 6 → 9 → 14 → 15 → 20 → 22 → F1-F4
Parallel Speedup: ~70% faster than sequential
Max Concurrent: 7 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Blocks | Wave |
|------|-----------|--------|------|
| 1 | - | 2-7,16 | 1 |
| 2 | 1 | 14,15,19 | 1 |
| 3 | 1 | all logging users | 1 |
| 4 | 1 | 5,19 | 1 |
| 5 | 1,4 | 14,19 | 1 |
| 6 | 1 | 9,15 | 1 |
| 7 | 1 | all config users | 1 |
| 8 | 1,7 | 14,15 | 2 |
| 9 | 1,6,7 | 14,15 | 2 |
| 10 | 1,7 | 14,15 | 2 |
| 11 | 1,7 | 14,15 | 2 |
| 12 | 1,7 | 15,16 | 2 |
| 13 | 1,7 | 15,16 | 2 |
| 14 | 2,5,8-13 | 15 | 3 |
| 15 | 2,6,8-13,14 | 22 | 3 |
| 16 | 1,7 | 17 | 3 |
| 17 | 16 | 18,20 | 4 |
| 18 | 17 | 20 | 4 |
| 19 | 2,5 | 20 | 4 |
| 20 | 17,18,19 | 21,23 | 4 |
| 21 | 20 | 22,23,24 | 4 |
| 22 | 15,21 | 23 | 5 |
| 23 | 20,22 | F1-F4 | 5 |
| 24 | 21,22 | F1-F4 | 5 |
| 25 | all impl | F1-F4 | 5 |
| F1-F4 | all | user okay | FINAL |

### Agent Dispatch Summary

- **Wave 1**: **7** - T1-T4 → `quick`, T5 → `deep`, T6-T7 → `quick`
- **Wave 2**: **6** - T8-T13 → `quick`
- **Wave 3**: **3** - T14 → `deep`, T15 → `deep`, T16 → `visual-engineering`
- **Wave 4**: **5** - T17 → `visual-engineering`, T18 → `quick`, T19 → `deep`, T20 → `deep`, T21 → `quick`
- **Wave 5**: **4** - T22 → `quick`, T23 → `unspecified-high`, T24 → `quick`, T25 → `unspecified-high`
- **FINAL**: **4** - F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **FORMAT**: Task labels use bare numbers: `1.`, `2.`, `3.` — NOT `T1.`, `Task 1.`, `Phase 1:`.

- [ ] 1. Project scaffolding + pyproject.toml + config.yaml full schema

  **What to do**:
  - 创建 `news-agent/` 目录结构：`src/{fetchers,curator,viewer,tray,db,llm,conversation,autostart}/`、`templates/`、`tests/`、`scripts/`、`docker/`、`data/`（.gitignore 忽略）
  - 创建 `pyproject.toml`：声明依赖 `pywebview>=6.2, pystray>=0.19, httpx, bs4, feedparser, openai, jinja2, lunardate, keyring, pyinstaller, pytest, pytest-asyncio, pytest-httpx`
  - 创建 `config.yaml` 完整 schema：`api_key_ref`（keyring service name） / `sources`（per-domain YAML list，每源含 type/rss|rsshub|html|api + url + params） / `cost_ceiling_daily_tokens: 50000` / `weather_city` / `hotkey_binding: "ctrl+alt+n"` / `window_position: {x,y,w,h}` / `worker_schedule: ["06:00","18:00"]` / `rsshub_base: "http://localhost:1200"` / `rsshub_fallback: ["https://rsshub.app"]` / `article_retention_days: 30` / `conversation_retention_days: 30` / `conversation_max_tokens: 64000`
  - sources 四域配置：AI/科技（HN frontpage RSS + 36kr RSSHub + ArXiv RSS）、编程/开源（GitHub trending atom + Reddit r/programming RSS）、明日方舟（PRTS Wiki HTML + NGA 方舟板 RSSHub）、百合+MAD/漫剪（Bangumi API + dmhy RSS 百合 keyword + Bilibili MAD 分区 RSSHub）

  **Must NOT do**:
  - 不创建 NewsSource ABC 或继承层级
  - 不加 config hot-reload/watchdog
  - 不加插件系统
  - 不加 i18n

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 脚手架 + 配置文件，无逻辑复杂度
  - **Skills**: []
    - 无特定 skill 需要匹配

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 2-7)
  - **Parallel Group**: Wave 1
  - **Blocks**: 2,3,4,5,6,7,16
  - **Blocked By**: None (可立即开始)

  **References**:

  **Pattern References**:
  - 无（空目录全新项目）

  **API/Type References**:
  - DeepSeek API docs: `https://api-docs.deepseek.com/quick_start/pricing` — `deepseek-chat` 2026-07-24 退役，用 `deepseek-v4-flash`
  - Bangumi API: `https://api.bgm.tv/v0/subjects` — type=2, tag="百合", 无需认证
  - open-meteo API: `https://api.open-meteo.com/v1/forecast` — 免费无 key

  **External References**:
  - pywebview docs: `https://pywebview.flowrl.com/` — Edge WebView2 backend
  - RSSHub docs: `https://docs.rsshub.app/` — 路由参数格式（/bilibili/partion/24, /36kr/motif/...）

  **WHY Each Reference Matters**:
  - DeepSeek 定价页确认模型名 `deepseek-v4-flash` 非退役的 `deepseek-chat`
  - Bangumi API 确认 type=2 + tag=百合 的 Yuri/GL 调用方式
  - RSSHub 路由文档确认 B站/微博/NGA 的正确 URL 格式

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 项目结构完整
    Tool: Bash
    Preconditions: 项目目录已创建
    Steps:
      1. ls news-agent/src/{fetchers,curator,viewer,tray,db,llm,conversation,autostart}/ — 每目录存在
      2. ls news-agent/templates/ news-agent/tests/ news-agent/scripts/ news-agent/docker/ — 每目录存在
      3. ls news-agent/pyproject.toml news-agent/config.yaml — 文件存在
    Expected Result: 所有序列存在，无 "No such file" 错误
    Failure Indicators: 任一目录/文件不存在
    Evidence: .omo/evidence/task-1-project-structure.txt

  Scenario: config.yaml schema 完整且可解析
    Tool: Bash
    Preconditions: config.yaml 已创建
    Steps:
      1. python -c "import yaml; cfg=yaml.safe_load(open('news-agent/config.yaml')); assert 'api_key_ref' in cfg; assert 'sources' in cfg; assert 'cost_ceiling_daily_tokens' in cfg; assert 'weather_city' in cfg; assert 'hotkey_binding' in cfg; assert 'window_position' in cfg; assert len(cfg['sources'])==4; print('config OK')"
    Expected Result: 输出 "config OK"
    Failure Indicators: KeyError / AssertionError / yaml parse error
    Evidence: .omo/evidence/task-1-config-schema.txt

  Scenario: config 损坏时不崩溃（edge case 13）
    Tool: Bash
    Preconditions: 配置文件已创建
    Steps:
      1. echo "INVALID: [[{{" > news-agent/config.yaml.broken
      2. python -c "import yaml; cfg=yaml.safe_load(open('news-agent/config.yaml.broken'))" 2>&1 | grep -i "error\|exception"
    Expected Result: YAML 解析报错（预期行为，后续 Task 7 config loader 会 try/except 处理）
    Failure Indicators: 无报错输出（说明 YAML 意外合法）
    Evidence: .omo/evidence/task-1-config-corrupt-edge.txt
  ```

  **Evidence to Capture**:
  - [ ] task-1-project-structure.txt — ls 输出
  - [ ] task-1-config-schema.txt — python assert 输出
  - [ ] task-1-config-corrupt-edge.txt — YAML break 测试

  **Commit**: YES (Wave 1)
  - Message: `feat(scaffold): project setup + pyproject.toml + config.yaml schema`
  - Files: `pyproject.toml, config.yaml, src/*/__init__.py, .gitignore`
  - Pre-commit: `python -c "import yaml; yaml.safe_load(open('config.yaml'))"`

- [ ] 2. DB schema + init module (WAL, busy_timeout, schema_version)

  **What to do**:
  - 创建 `src/db/init.py`：`init_db(db_path) -> sqlite3.Connection` 函数
  - 设置 `PRAGMA journal_mode=WAL;` + `PRAGMA busy_timeout=5000;`
  - 创建 `schema_version` 表（`version INTEGER`）+ 初始 version=1
  - 创建 `articles` 表：`id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL, domain TEXT NOT NULL, summary TEXT, score REAL, fetched_at TEXT NOT NULL, raw_json TEXT`
  - 创建 `conversations` 表：`id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, tokens INTEGER, created_at TEXT NOT NULL`（按日期分区查询）
  - 创建 `daily_usage` 表：`date TEXT NOT NULL, total_tokens INTEGER DEFAULT 0, PRIMARY KEY(date)`
  - 创建索引：`articles.url` (UNIQUE), `articles.fetched_at`, `articles.domain`, `conversations.created_at`
  - 所有时间戳用 `datetime.utcnow().isoformat()` 格式
  - Schema migration：`init_db` 检查 `schema_version`，如不存在则建表写入 version=1；如存在则比对版本执行迁移

  **Must NOT do**:
  - 不加 ORM（SQLAlchemy 等），直接 sqlite3
  - 不加连接池（两进程各自单连接）
  - 不加外键联动约束（简单表即可）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 标准 SQLite schema + init，模式固定
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1,3-7; depends on Task 1 for目录)
  - **Parallel Group**: Wave 1
  - **Blocks**: 14,15,19
  - **Blocked By**: 1（需要目录结构）

  **References**:

  **Pattern References**:
  - SQLite WAL 跨进程模式：`https://www.sqlite.org/wal.html` — WAL 允许读写并发

  **API/Type References**:
  - articles schema 基于 Task 14 curator 输出格式

  **External References**:
  - sqlite3 Python docs: `https://docs.python.org/3/library/sqlite3.html` — PRAGMA / URI 连接

  **WHY Each Reference Matters**:
  - WAL 文档解释为何必须启用（否则 main 读时 Worker 写会"database is locked"）
  - URI `file:path?mode=ro` 允许主进程只读连接防止误写

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: DB 初始化正确
    Tool: Bash
    Preconditions: Task 1 完成，data/ 目录存在
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from db.init import init_db; conn=init_db('news-agent/data/state.db'); assert conn.execute('PRAGMA journal_mode').fetchone()==('wal',); assert conn.execute('PRAGMA busy_timeout').fetchone()==(5000,); assert conn.execute('SELECT version FROM schema_version').fetchone()==(1,); print('DB OK')"
    Expected Result: 输出 "DB OK"
    Failure Indicators: journal_mode 非 wal / busy_timeout 非 5000 / schema_version 无记录
    Evidence: .omo/evidence/task-2-db-init.txt

  Scenario: articles URL 去重（UNIQUE 约束）
    Tool: Bash
    Preconditions: DB 已初始化
    Steps:
      1. python -c "import sqlite3; conn=sqlite3.connect('news-agent/data/state.db'); conn.execute(\"INSERT INTO articles(url,title,source,domain,fetched_at) VALUES('https://test.com/1','T','S','D','2025-01-01T00:00:00')\"); conn.commit()"
      2. python -c "import sqlite3; conn=sqlite3.connect('news-agent/data/state.db'); conn.execute(\"INSERT INTO articles(url,title,source,domain,fetched_at) VALUES('https://test.com/1','T','S','D','2025-01-01T00:00:00')\")" 2>&1 | grep -i "UNIQUE constraint failed"
    Expected Result: 第二次插入报 "UNIQUE constraint failed: articles.url"
    Failure Indicators: 无 UNIQUE 约束错误
    Evidence: .omo/evidence/task-2-db-dedup.txt

  Scenario: 主进程只读连接（edge case: 防误写）
    Tool: Bash
    Preconditions: DB 已初始化且有数据
    Steps:
      1. python -c "import sqlite3; conn=sqlite3.connect('file:news-agent/data/state.db?mode=ro',uri=True); conn.execute(\"INSERT INTO articles(url,title,source,domain,fetched_at) VALUES('https://readonly-test.com','T','S','D','2025-01-01T00:00:00')\")" 2>&1 | grep -i "attempt to write\|readonly"
    Expected Result: 报 "attempt to write a readonly database"
    Failure Indicators: 写入成功（说明只读连接未生效）
    Evidence: .omo/evidence/task-2-db-readonly.txt

  Scenario: SQLite 锁重试（edge case 6）
    Tool: Bash
    Preconditions: DB 已初始化
    Steps:
      1. 开两个 python 进程同时写 articles 表
      2. 后写进程在 5 秒内 retry 3 次 5s 间隔
    Expected Result: 一个成功一个等待后成功，无死锁
    Failure Indicators: "database is locked" 异常（说明 busy_timeout 未生效）
    Evidence: .omo/evidence/task-2-db-concurrency.txt
  ```

  **Commit**: YES (Wave 1, 与 Task 1 合并或单独 commit)
  - Message: `feat(db): SQLite schema + WAL + busy_timeout`
  - Files: `src/db/__init__.py, src/db/init.py`

- [ ] 3. Logging module + %APPDATA% paths

  **What to do**:
  - 创建 `src/logging_setup.py`：`setup_logging(process_name: str) -> logging.Logger`
  - 日志目录：`%APPDATA%/news-agent/logs/`（使用 `os.environ['APPDATA']` 获取路径，fallback `~/.news-agent/logs/`）
  - 每进程独立日志文件：`main.log` / `worker.log`
  - 日志格式：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`
  - 日志级别：默认 INFO（环境变量 `NEWS_AGENT_LOG_LEVEL=DEBUG` 可调）
  - 日志轮转：`logging.handlers.TimedRotatingFileHandler`，daily rotation，`backupCount=7`（7 天保留）
  - Worker 进程额外写入 stderr（便于 Task Scheduler 存档）
  - 30 天文章保留：加 `cleanup_old_articles(db_path, days=30)` 函数在 worker 日志中记录删除条数

  **Must NOT do**:
  - 不用 loguru/structlog 等第三方日志库（Python logging 足够）
  - 不加 ELK/Loki 等远程日志发送

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 标准 Python logging 配置
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1,2,4-7)
  - **Parallel Group**: Wave 1
  - **Blocks**: 所有使用 logging 的任务（5,14,15,19,20,22 等）
  - **Blocked By**: 1（目录）

  **References**:

  **External References**:
  - Python logging docs: `https://docs.python.org/3/library/logging.html`
  - TimedRotatingFileHandler: `https://docs.python.org/3/library/logging.handlers.html#timedrotatingfilehandler`

  **WHY Each Reference Matters**:
  - TimedRotatingFileHandler 实现 7 天轮转，自动删除旧日志

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 日志写入正确目录
    Tool: Bash
    Preconditions: Task 1 完成
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from logging_setup import setup_logging; log=setup_logging('worker'); log.info('test message'); import os; path=os.path.join(os.environ['APPDATA'],'news-agent','logs','worker.log'); assert os.path.exists(path); print('logging OK')"
    Expected Result: 输出 "logging OK"，文件 %APPDATA%/news-agent/logs/worker.log 存在且含 "test message"
    Failure Indicators: 文件不存在 / 无 "test message" 内容
    Evidence: .omo/evidence/task-3-logging-write.txt

  Scenario: 日志轮转 7 天保留
    Tool: Bash
    Preconditions: 日志已配置
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from logging_setup import setup_logging; import logging; log=setup_logging('main'); h=[h for h in log.handlers if isinstance(h,logging.handlers.TimedRotatingFileHandler)][0]; assert h.backupCount==7; print('rotation OK')"
    Expected Result: 输出 "rotation OK"
    Failure Indicators: backupCount 非 7
    Evidence: .omo/evidence/task-3-logging-rotation.txt
  ```

  **Commit**: YES (Wave 1)
  - Message: `feat(logging): process-specific logging with 7-day rotation`
  - Files: `src/logging_setup.py`

- [ ] 4. API key management (keyring + Credential Manager + .env fallback)

  **What to do**:
  - 创建 `src/llm/apikey.py`：`get_api_key() -> str` 函数
  - 主路径：`keyring.get_password("news-agent", "deepseek_api_key")` → Windows Credential Manager
  - Fallback：读取 `%APPDATA%/news-agent/.env` 文件中 `DEEPSEEK_API_KEY=xxx`，文件 ACL restricted（仅当前用户可读）
  - `set_api_key(key: str)` 函数：优先写入 keyring，不可用则写 .env
  - key 不存在时 raise `ApiKeyNotFoundError`（非返回空字符串，防误传空 key 给 API）
  - 测试命令：`python -c "from llm.apikey import get_api_key; print(get_api_key()[:8]+'...')"` 应输出 key 前 8 字符

  **Must NOT do**:
  - 不在 config.yaml 中明文存 key
  - 不在日志中打印 key 完整值
  - 不加 key 轮换/过期机制（个人项目，改了重启即可）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: keyring 库封装简单
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1,2,3,5-7)
  - **Parallel Group**: Wave 1
  - **Blocks**: 5,19
  - **Blocked By**: 1（目录）

  **References**:

  **External References**:
  - keyring docs: `https://keyring.readthedocs.io/` — Windows Credential Manager backend
  - DeepSeek API key 获取: `https://platform.deepseek.com/` — 注册后生成

  **WHY Each Reference Matters**:
  - keyring 库在 Windows 上自动使用 Credential Manager，无需手动 Win32 API

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: API key 读取成功
    Tool: Bash
    Preconditions: 已通过 set_api_key 设置 key
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from llm.apikey import set_api_key,get_api_key; set_api_key('sk-test1234567890'); k=get_api_key(); assert k=='sk-test1234567890'; print('apikey OK')"
    Expected Result: 输出 "apikey OK"
    Failure Indicators: KeyError / key 不匹配
    Evidence: .omo/evidence/task-4-apikey-read.txt

  Scenario: API key 不存在时报错（edge case: API key 失效）
    Tool: Bash
    Preconditions: 清除 keyring + .env 中的 key
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from llm.apikey import get_api_key; get_api_key()" 2>&1 | grep -i "ApiKeyNotFoundError\|KeyError"
    Expected Result: 抛出 ApiKeyNotFoundError（不返回空字符串）
    Failure Indicators: 返回空字符串或 None（会导致后续 DeepSeek API 报 401 而非友好提示）
    Evidence: .omo/evidence/task-4-apikey-missing.txt

  Scenario: .env fallback 在 keyring 不可用时工作
    Tool: Bash
    Preconditions: keyring 服务不可用（模拟：monkeypatch keyring.get_password 返回 None）
    Steps:
      1. 创建 %APPDATA%/news-agent/.env 含 DEEPSEEK_API_KEY=sk-envfallback123
      2. python -c "import sys; sys.path.insert(0,'news-agent/src'); from llm.apikey import get_api_key; k=get_api_key(); assert k=='sk-envfallback123'; print('fallback OK')"
    Expected Result: 输出 "fallback OK"
    Failure Indicators: ApiKeyNotFoundError（说明 fallback 未生效）
    Evidence: .omo/evidence/task-4-apikey-fallback.txt
  ```

  **Commit**: YES (Wave 1)
  - Message: `feat(apikey): keyring + Credential Manager with .env fallback`
  - Files: `src/llm/apikey.py`

- [ ] 5. DeepSeek client wrapper (v4-flash, thinking disabled, backoff, cost ceiling)

  **What to do**:
  - 创建 `src/llm/client.py`：`DeepSeekClient` 类封装 OpenAI SDK（`pip install openai`，`base_url="https://api.deepseek.com"`）
  - 模型名硬编码：`MODEL = "deepseek-v4-flash"`（NOT `deepseek-chat`，2026-07-24 退役）
  - 每次调用包含 `extra_body={"thinking": {"type": "disabled"}}`（非 thinking 模式，TTFB 30s 不可接受）
  - 指数退避重试：HTTP 429/503 → sleep 1s, 2s, 4s, 8s, 16s，max 5 次
  - 每次请求 timeout=30 秒
  - system prompt 放 messages[0]（DeepSeek auto-caching，前缀重复 98% 成本降低）
  - 成本追踪：每次调用后 `response.usage.total_tokens` 写入 `daily_usage` 表
  - 检查日成本上限：调用前查询 `daily_usage` 当日累计 + 本次预估，如超 `config.cost_ceiling_daily_tokens`（默认 50000）则 raise `CostCeilingExceededError`
  - `summarize(articles: list[dict]) -> list[dict]`：接收去重后文章列表，调用 DeepSeek 生成 50 字摘要 + 打分（0-10），返回含 summary + score 的文章列表
  - `chat(messages: list[dict], system_prompt: str) -> str`：流式/非流式对话
  - 超限降级：caller（curator/worker）捕获 `CostCeilingExceededError` → headlines-only 模式（不调 AI summary）
  - caller（conversation）捕获 → 返回 "今日额度已用完，明天 0:00 重置"

  **Must NOT do**:
  - 不加本地模型回退（纯云 API）
  - 不加 multi-model 路由
  - 不加 prompt template 引擎（system prompt 直接在代码里）
  - 不加密 / 不加水印生成内容

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: API 封装含重试逻辑 + 成本追踪 + 降级策略，需要细心实现
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1-4,6,7; depends on Task 1 目录 + Task 4 apikey)
  - **Parallel Group**: Wave 1（严格说依赖 Task 4，但 Task 4 是 quick，可与 Task 5 同时启动先写其余部分）
  - **Blocks**: 14,19
  - **Blocked By**: 1, 4（apikey 接口）

  **References**:

  **API/Type References**:
  - DeepSeek API: `https://api-docs.deepseek.com/` — OpenAI SDK 兼容，`base_url=https://api.deepseek.com`
  - DeepSeek 定价: `https://api-docs.deepseek.com/quick_start/pricing` — v4-flash $0.14/M input, $0.28/M output

  **Pattern References**:
  - OpenAI SDK 用法: `https://platform.openai.com/docs/api-reference/chat` — `client.chat.completions.create()`

  **External References**:
  - DeepSeek auto-caching: 官方文档说明 system prompt 前缀重复输入 token 命中缓存 98% 成本降低

  **WHY Each Reference Matters**:
  - 模型名必须写对（`deepseek-chat` 13 天后退役）
  - base_url 必须设为 DeepSeek 端点（否则请求发到 OpenAI）
  - auto-caching 要求 messages[0] 为稳定的 system prompt（不能每次变化）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: DeepSeek API 调用成功（真实 API call）
    Tool: Bash
    Preconditions: API key 已设置（Task 4），网络可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from llm.client import DeepSeekClient; c=DeepSeekClient(); r=c.chat([{'role':'user','content':'说OK'}],system_prompt='你是测试助手'); assert 'OK' in r or 'ok' in r.lower(); print('deepseek OK')"
    Expected Result: 输出 "deepseek OK"，API 返回含 "OK"
    Failure Indicators: 401 unauthorized / 404 model not found / timeout
    Evidence: .omo/evidence/task-5-deepseek-call.txt

  Scenario: 模型名硬编码为 v4-flash
    Tool: Bash
    Preconditions: 代码已写
    Steps:
      1. grep -r "deepseek-chat" news-agent/src/ 应零匹配
      2. grep -r "deepseek-v4-flash" news-agent/src/llm/client.py 应有匹配
    Expected Result: deepseek-chat 零匹配，deepseek-v4-flash 有匹配
    Failure Indicators: 发现 deepseek-chat 引用（会导致 13 天后 API 失效）
    Evidence: .omo/evidence/task-5-model-name.txt

  Scenario: 429 重试指数退避（edge case: DeepSeek 中断）
    Tool: Bash
    Preconditions: mock pytest-httpx 模拟 429
    Steps:
      1. pytest tests/test_llm_client.py::test_retry_backoff -v
      2. 测试代码 mock DeepSeek API 返回 429 三次后 200，断言 retry 间隔 >= 1, 2, 4 秒
    Expected Result: 测试通过，retry 逻辑正确
    Failure Indicators: 测试失败 / 无重试直接 raise
    Evidence: .omo/evidence/task-5-retry-backoff.txt

  Scenario: 50K token 成本上限触发降级（edge case: 成本控制）
    Tool: Bash
    Preconditions: daily_usage 表当日已累计 50000 tokens
    Steps:
      1. python -c "import sqlite3; conn=sqlite3.connect('news-agent/data/state.db'); conn.execute(\"INSERT OR REPLACE INTO daily_usage(date,total_tokens) VALUES(date('now'),50000)\"); conn.commit()"
      2. python -c "import sys; sys.path.insert(0,'news-agent/src'); from llm.client import DeepSeekClient; c=DeepSeekClient(); c.chat([{'role':'user','content':'test'}],system_prompt='x')" 2>&1 | grep -i "CostCeilingExceeded"
    Expected Result: 抛出 CostCeilingExceededError
    Failure Indicators: API 调用成功（说明上限检查未生效）
    Evidence: .omo/evidence/task-5-cost-ceiling.txt

  Scenario: thinking 模式已禁用
    Tool: Bash
    Preconditions: 代码已写
    Steps:
      1. grep "thinking.*disabled\|extra_body" news-agent/src/llm/client.py 应有匹配
    Expected Result: 匹配到 thinking disabled 配置
    Failure Indicators: 无 extra_body 参数（TTFB 30s 不可接受）
    Evidence: .omo/evidence/task-5-thinking-disabled.txt
  ```

  **Commit**: YES (Wave 1)
  - Message: `feat(llm): DeepSeek client with v4-flash + backoff + cost ceiling`
  - Files: `src/llm/client.py, src/llm/exceptions.py`

- [ ] 6. RSSHub docker-compose + config

  **What to do**:
  - 创建 `docker/rsshub-docker-compose.yml`：
    ```yaml
    version: '3'
    services:
      rsshub:
        image: diygod/rsshub:latest
        ports:
          - "1200:1200"
        restart: unless-stopped
        environment:
          - CACHE_TYPE=memory
          - CACHE_EXPIRE=600
    ```
  - 创建 `scripts/start-rsshub.ps1`：检查 Docker 可用 → `docker compose -f docker/rsshub-docker-compose.yml up -d` → 等待 1200 端口可用
  - 在 config.yaml 已有 `rsshub_base` + `rsshub_fallback` 字段（Task 1 定义）
  - 文档说明：如果用户不想用 Docker，可 fallback 到公共实例 `https://rsshub.app`（限制更严，但可用）

  **Must NOT do**:
  - 不加 RSSHub 自定义路由/插件开发
  - 不加 RSSHub 健康检查 daemon（worker 调用失败时 fallback 即可）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: docker-compose + 简单脚本
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1-5,7)
  - **Parallel Group**: Wave 1
  - **Blocks**: 9,15
  - **Blocked By**: 1（目录）

  **References**:

  **External References**:
  - RSSHub docs: `https://docs.rsshub.app/` — 路由列表 + docker 部署
  - diygod/rsshub Docker: `https://hub.docker.com/r/diygod/rsshub` — 官方镜像

  **WHY Each Reference Matters**:
  - RSSHub 路由文档确认 B站(/bilibili/partion/24)/微博/NGA(/nga/forum/607) 的正确 URL 格式
  - Docker 镜像文档确认环境变量 + 端口配置

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: docker-compose 文件有效
    Tool: Bash
    Preconditions: Docker 可用（如不可用则跳过并标 N/A）
    Steps:
      1. docker compose -f news-agent/docker/rsshub-docker-compose.yml config --quiet
    Expected Result: 无输出（配置有效），退出码 0
    Failure Indicators: 报错 "invalid compose" / 退出码非 0
    Evidence: .omo/evidence/task-6-compose-valid.txt

  Scenario: RSSHub 启动后端口可用
    Tool: Bash
    Preconditions: Docker 可用
    Steps:
      1. docker compose -f news-agent/docker/rsshub-docker-compose.yml up -d
      2. timeout 60 bash -c 'until curl -s http://localhost:1200 > /dev/null 2>&1; do sleep 2; done'
      3. curl -s http://localhost:1200 | grep -i "rsshub\|RSSHub"
    Expected Result: 页面含 RSSHub 标识
    Failure Indicators: 60 秒内端口不可用 / 页面空白
    Evidence: .omo/evidence/task-6-rsshub-start.txt

  Scenario: RSSHub 路由可用（B站分区）
    Tool: Bash
    Preconditions: RSSHub 已启动
    Steps:
      1. curl -s "http://localhost:1200/bilibili/partition/24" | grep -i "<item>\|<title>"
    Expected Result: 返回 RSS XML 含 <item>（MAD/AMV 分区有内容）
    Failure Indicators: 404 / 空内容（说明路由参数有误）
    Evidence: .omo/evidence/task-6-rsshub-route-bili.txt

  Scenario: 公共实例 fallback（edge case 15: RSSHub 宕）
    Tool: Bash
    Preconditions: 本地 RSSHub 停止
    Steps:
      1. docker compose -f news-agent/docker/rsshub-docker-compose.yml stop
      2. curl -s --max-time 10 "https://rsshub.app/bilibili/partition/24" | head -c 200
    Expected Result: 公共实例返回内容（注意：公共实例可能限流，部分路由不可用属预期）
    Failure Indicators: 无 fallback 机制（Worker 应代码层 fallback，Task 9 实现）
    Evidence: .omo/evidence/task-6-rsshub-fallback.txt
  ```

  **Commit**: YES (Wave 1)
  - Message: `feat(rsshub): local docker-compose + start script`
  - Files: `docker/rsshub-docker-compose.yml, scripts/start-rsshub.ps1`

- [ ] 7. Config loader + validator (try/except, fallback default)

  **What to do**:
  - 创建 `src/config.py`：`load_config(path: str = "config.yaml") -> dict` 函数
  - try/except 包裹 `yaml.safe_load`：解析失败 → log warning + 返回 `DEFAULT_CONFIG`（含 4 域空 sources + 默认参数）
  - 验证必需字段存在：`api_key_ref`、`sources`（至少 1 域）、`cost_ceiling_daily_tokens`、`weather_city`、`hotkey_binding`、`window_position`
  - 缺失字段用默认值填充并 log warning（不崩溃）
  - `window_position` 缺失时默认 `{x: null, y: null, w: 900, h: 700}`（null 表示主屏居中）
  - `get_config() -> dict`：缓存单例 config（首次调用 load_config，后续返回缓存）
  - 支持环境变量覆盖：`NEWS_AGENT_CONFIG_PATH` 指定备用配置路径

  **Must NOT do**:
  - 不加 config hot-reload/watchdog（scope creep #2）
  - 不加 config schema 校验库（pydantic 等），简单 isinstance + key 检查
  - 不加 config 加密

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: yaml 加载 + 默认值填充，标准模式
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 1, with Tasks 1-6)
  - **Parallel Group**: Wave 1
  - **Blocks**: 所有使用 config 的任务（8-15,17-21）
  - **Blocked By**: 1（目录 + config.yaml）

  **References**:

  **External References**:
  - PyYAML docs: `https://pyyaml.org/wiki/PyYAMLDocumentation` — `safe_load` 避免 `load` 的代码执行风险

  **WHY Each Reference Matters**:
  - safe_load 防止 YAML 中嵌入 Python 代码执行（`!!python/object`）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 正常加载 config
    Tool: Bash
    Preconditions: config.yaml 存在且有效（Task 1）
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from config import load_config; cfg=load_config('news-agent/config.yaml'); assert 'sources' in cfg; assert len(cfg['sources'])==4; print('config load OK')"
    Expected Result: 输出 "config load OK"
    Failure Indicators: KeyError / 缺少字段
    Evidence: .omo/evidence/task-7-config-load.txt

  Scenario: config 损坏 fallback 默认（edge case 13）
    Tool: Bash
    Preconditions: 创建无效 config 文件
    Steps:
      1. echo "INVALID: [[{{" > /tmp/broken-config.yaml
      2. python -c "import sys; sys.path.insert(0,'news-agent/src'); from config import load_config; cfg=load_config('/tmp/broken-config.yaml'); assert 'sources' in cfg; print('fallback OK')" 2>&1
    Expected Result: 输出含 warning + "fallback OK"，返回 DEFAULT_CONFIG
    Failure Indicators: 抛异常崩溃 / 返回 None
    Evidence: .omo/evidence/task-7-config-fallback.txt

  Scenario: 缺失字段用默认填充
    Tool: Bash
    Preconditions: 创建缺失 window_position 的 config
    Steps:
      1. python -c "import yaml; yaml.safe_dump({'api_key_ref':'test','sources':{'ai_tech':[]},'cost_ceiling_daily_tokens':50000,'weather_city':'北京','hotkey_binding':'ctrl+alt+n'}, open('/tmp/partial.yaml','w'))"
      2. python -c "import sys; sys.path.insert(0,'news-agent/src'); from config import load_config; cfg=load_config('/tmp/partial.yaml'); assert cfg['window_position']['w']==900; print('default fill OK')"
    Expected Result: 输出 "default fill OK"，window_position 用默认值填充
    Failure Indicators: KeyError on window_position
    Evidence: .omo/evidence/task-7-config-defaults.txt
  ```

  **Commit**: YES (Wave 1)
  - Message: `feat(config): yaml loader with fallback defaults`
  - Files: `src/config.py`

- [ ] 8. Fetcher: RSS via feedparser (HN, GitHub trending, dmhy)

  **What to do**:
  - 创建 `src/fetchers/rss.py`：`fetch_rss(url: str, limit: int = 20) -> list[dict]` 函数
  - 使用 `feedparser.parse(url)` 解析 RSS 2.0 / Atom
  - 返回标准化 dict 列表：`{url, title, source, summary, published_at, raw_json}`
  - `published_at` 用 `entry.published_parsed` 转 ISO 格式（UTC）；缺失则用 `datetime.utcnow()`
  - 失败处理：feedparser 不抛异常（网络/解析错误写入 `feed.bozo` 标志），检查 `bozo` + `bozo_exception` → log warning + 返回空列表
  - 超时：feedparser 无原生 timeout，外层用 `httpx` 先 fetch 再 parse（5 秒 timeout）
  - 调用方：Task 14 curator 组合调用，Task 15 worker 编排
  - 支持的源（config.yaml 中配置）：Hacker News frontpage (`https://hnrss.org/frontpage`)、GitHub trending (`https://github.com/trending.atom`)、dmhy 百合 keyword (`https://dmhy.org/topics/rss/rss.xml?keyword=百合`)

  **Must NOT do**:
  - 不加 RSS 缓存（WAL SQLite 去重在 curator 层处理）
  - 不加 RSS 全文抓取（summary 字段足够，全文 LLM 处理成本高）
  - 不加 ETag/Last-Modified 增量抓取（去重在 DB 层用 URL UNIQUE）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: feedparser 封装标准化
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 9-13)
  - **Parallel Group**: Wave 2
  - **Blocks**: 14,15
  - **Blocked By**: 1, 7（config + 目录）

  **References**:

  **API/Type References**:
  - 返回结构对齐 Task 2 articles 表 schema（url, title, source, summary, fetched_at）

  **External References**:
  - feedparser docs: `https://feedparser.readthedocs.io/` — `parse()`, `bozo`, `published_parsed`
  - dmhy RSS: `https://dmhy.org/topics/rss/rss.xml` — 支持 keyword 参数

  **WHY Each Reference Matters**:
  - feedparser `bozo` 标志区分解析失败 vs 成功（不抛异常的设计）
  - dmhy keyword 参数确认 `?keyword=百合` URL 格式

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: HN RSS 抓取成功
    Tool: Bash
    Preconditions: 网络可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.rss import fetch_rss; items=fetch_rss('https://hnrss.org/frontpage',limit=5); assert len(items)>0; assert 'url' in items[0]; assert 'title' in items[0]; print(f'rss OK, got {len(items)} items')"
    Expected Result: 输出 "rss OK, got 5 items"
    Failure Indicators: 空列表 / KeyError
    Evidence: .omo/evidence/task-8-rss-hn.txt

  Scenario: 失效 URL 返回空列表不崩溃
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.rss import fetch_rss; items=fetch_rss('https://invalid-domain-xxx.com/rss.xml'); assert items==[]; print('graceful fail OK')"
    Expected Result: 输出 "graceful fail OK"，返回空列表
    Failure Indicators: 抛异常崩溃
    Evidence: .omo/evidence/task-8-rss-fail.txt

  Scenario: dmhy 百合 keyword 过滤
    Tool: Bash
    Preconditions: 网络可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.rss import fetch_rss; items=fetch_rss('https://dmhy.org/topics/rss/rss.xml?keyword=百合',limit=5); print(f'dmhy got {len(items)} items')"
    Expected Result: 返回 0-5 条百合相关条目（可能为空——dmhy 关键词匹配数不稳定）
    Failure Indicators: 抛异常
    Evidence: .omo/evidence/task-8-rss-dmhy.txt
  ```

  **Commit**: YES (Wave 2)
  - Message: `feat(fetchers): RSS via feedparser (HN/GitHub/dmhy)`
  - Files: `src/fetchers/rss.py`

- [ ] 9. Fetcher: RSSHub via httpx (Bilibili, Weibo, NGA终末地)

  **What to do**:
  - 创建 `src/fetchers/rsshub.py`：`fetch_rsshub(path: str, limit: int = 20) -> list[dict]`
  - 使用 `httpx.get(f"{config['rsshub_base']}{path}", timeout=10)` 先尝试本地 RSSHub
  - 失败 → 遍历 `config['rsshub_fallback']` 公共实例列表
  - 返回结构同 Task 8（标准化 dict 列表），内部调用 Task 8 `fetch_rss` 解析返回的 RSS XML
  - 所有实例失败 → log error + 返回空列表（edge case 15）
  - 支持的源（config.yaml 中配置）：Bilibili MAD 分区 (`/bilibili/partition/24`)、NGA 方舟板 (`/nga/forum/607`)、微博话题（如需要）
  - 注意 Bilibili 直爬需 wbi 签名 + 有法律风险 → 必须 RSSHub-first

  **Must NOT do**:
  - 不直接调用 Bilibili/NGA/微博 API（wbi 签名脆弱 + CloudFlare + 法律风险）
  - 不缓存 RSSHub 响应（去重在 DB 层）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: httpx + feedparser 封装
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 8,10-13)
  - **Parallel Group**: Wave 2
  - **Blocks**: 14,15
  - **Blocked By**: 1, 6, 7, 8（RSSHub config + rss.py）

  **References**:

  **API/Type References**:
  - 同 Task 8 返回结构

  **External References**:
  - RSSHub 路由: `https://docs.rsshub.app/routes/social-media` — bilibili, weibo
  - RSSHub 路由: `https://docs.rsshub.app/routes/discussion` — nga
  - pywebview Issue #1387 参考：无（此为 fetcher 无 UI）

  **WHY Each Reference Matters**:
  - RSSHub 路由文档确认正确 path 参数（/bilibili/partition/24 非分区名 24 像 `/bilibili/partion/24`，需验证确切格式）

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 本地 RSSHub B站分区抓取成功
    Tool: Bash
    Preconditions: 本地 RSSHub 已启动（Task 6）
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.rsshub import fetch_rsshub; items=fetch_rsshub('/bilibili/partition/24',limit=10); print(f'rsshub bili got {len(items)} items')"
    Expected Result: 返回 >0 条 B站 MAD 分区条目
    Failure Indicators: 空列表 + 日志报"all RSSHub instances failed"
    Evidence: .omo/evidence/task-9-rsshub-bili.txt

  Scenario: RSSHub 宕时 fallback 公共实例（edge case 15）
    Tool: Bash
    Preconditions: 本地 RSSHub 停止，公共实例可用
    Steps:
      1. docker compose -f news-agent/docker/rsshub-docker-compose.yml stop
      2. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.rsshub import fetch_rsshub; items=fetch_rsshub('/bilibili/partition/24',limit=5); print(f'fallback got {len(items)} items')"
    Expected Result: 公共实例返回数据（可能限流，>0 或 0 均可接受但不应崩溃）
    Failure Indicators: 抛异常崩溃
    Evidence: .omo/evidence/task-9-rsshub-fallback.txt

  Scenario: 全部实例失败返回空列表
    Tool: Bash
    Preconditions: 本地 + 公共实例均不可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from config import get_config; cfg=get_config(); cfg['rsshub_base']='http://localhost:99999'; cfg['rsshub_fallback']=[]; from fetchers.rsshub import fetch_rsshub; items=fetch_rsshub('/test'); assert items==[]; print('all fail graceful OK')"
    Expected Result: 输出 "all fail graceful OK"
    Failure Indicators: 抛异常
    Evidence: .omo/evidence/task-9-rsshub-allfail.txt
  ```

  **Commit**: YES (Wave 2)
  - Message: `feat(fetchers): RSSHub via httpx with fallback`
  - Files: `src/fetchers/rsshub.py`

- [ ] 10. Fetcher: HTML via bs4 (PRTS Wiki)

  **What to do**:
  - 创建 `src/fetchers/html_fetcher.py`：`fetch_html(url: str, selectors: dict, limit: int = 20) -> list[dict]`
  - 使用 `httpx.get(url, timeout=10)` + `bs4.BeautifulSoup(resp.text, 'html.parser')`
  - `selectors` dict 含：`{item_selector: "CSS选择器", title_selector: "...", url_selector: "...", summary_selector: "..."}`
  - 返回结构同 Task 8
  - selector 返回 0 结果 → log warning "selector returned 0 results for source {url}"（edge case 14）
  - PRTS Wiki (prts.wiki) 特化：抓取首页新闻版块或公告页
  - 失败处理：HTTP 错误 / 解析异常 → log + 返回空列表

  **Must NOT do**:
  - 不加 CloudFlare 绕过（PRTS Wiki 无 CF，直接 httpx 可行）
  - 不加浏览器渲染（PRTS Wiki 是静态 HTML）
  - 不加 headless 浏览器

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: httpx + bs4 标准 web scraping
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 8,9,11-13)
  - **Parallel Group**: Wave 2
  - **Blocks**: 14,15
  - **Blocked By**: 1, 7

  **References**:

  **API/Type References**:
  - 同 Task 8 返回结构

  **External References**:
  - PRTS Wiki: `https://prts.wiki/` — 明日方舟 Wiki
  - Beautiful Soup: `https://www.crummy.com/software/BeautifulSoup/bs4/doc/` — CSS selectors

  **WHY Each Reference Matters**:
  - PRTS Wiki 确认无 CloudFlare（直接 httpx 抓取可行）
  - bs4 CSS 选择器语法确认

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: PRTS Wiki 抓取成功
    Tool: Bash
    Preconditions: 网络可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.html_fetcher import fetch_html; items=fetch_html('https://prts.wiki/w/%E9%A6%96%E9%A1%B5', {'item_selector': '.article','title_selector': 'h2','url_selector': 'a','summary_selector': 'p'}, limit=5); print(f'prts got {len(items)} items')"
    Expected Result: 返回 0-5 条（PRTS 首页结构需实际验证）
    Failure Indicators: 抛异常崩溃
    Evidence: .omo/evidence/task-10-prts-wiki.txt

  Scenario: selector 返回 0 不崩溃（edge case 14）
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.html_fetcher import fetch_html; items=fetch_html('https://prts.wiki/w/首页', {'item_selector': '.nonexistent-class-xxx','title_selector': 'h2','url_selector': 'a','summary_selector': 'p'}, limit=5); assert items==[]; print('zero selector OK')"
    Expected Result: 输出 "zero selector OK"，日志含 warning
    Failure Indicators: 抛异常
    Evidence: .omo/evidence/task-10-html-zero-selector.txt

  Scenario: HTTP 错误不崩溃
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.html_fetcher import fetch_html; items=fetch_html('https://httpbin.org/status/404', {'item_selector': 'div'}, limit=5); assert items==[]; print('404 graceful OK')"
    Expected Result: 输出 "404 graceful OK"
    Failure Indicators: 抛异常
    Evidence: .omo/evidence/task-10-html-404.txt
  ```

  **Commit**: YES (Wave 2)
  - Message: `feat(fetchers): HTML via bs4 (PRTS Wiki)`
  - Files: `src/fetchers/html_fetcher.py`

- [ ] 11. Fetcher: Bangumi API (api.bgm.tv, Yuri/GL)

  **What to do**:
  - 创建 `src/fetchers/bangumi.py`：`fetch_bangumi(params: dict, limit: int = 20) -> list[dict]`
  - 使用 `httpx.get("https://api.bgm.tv/v0/subjects", params=..., timeout=10)`
  - 默认参数：`{"type": 2, "tag": "百合", "sort": "rank", "limit": 20}`（type=2 为动画）
  - 响应 JSON 含 `data` 数组，每元素含 `id, name, name_cn, summary, tags, date, rating`
  - 返回结构对齐 Task 8：`{url: f"https://api.bgm.tv/subject/{id}", title: name_cn or name, source: "bangumi", summary: summary, published_at: date, raw_json: element}`
  - 失败处理：HTTP 错误 → log + 返回空列表
  - 无需认证（免费 API）；无需 wbi 签名

  **Must NOT do**:
  - 不抓取角色/章节子表（只需 subject 列表）
  - 不加 Bangumi OAuth 登录
  - 不缓存（DB 层去重）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: httpx + JSON 解析简单封装
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 8-10,12,13)
  - **Parallel Group**: Wave 2
  - **Blocks**: 14,15
  - **Blocked By**: 1, 7

  **References**:

  **API/Type References**:
  - Bangumi API: `https://api.bgm.tv/v0/subjects` — type=2 动画, tag filter, sort

  **External References**:
  - Bangumi API docs: `https://bangumi.github.io/api/` — v0 接口规范

  **WHY Each Reference Matters**:
  - 确认 type=2 是动画分类（type=1 书, 3 音乐, 4 真人剧, 6 三次元）
  - 确认 tag 参数支持 "百合" 过滤

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Bangumi 百合主题抓取成功
    Tool: Bash
    Preconditions: 网络可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.bangumi import fetch_bangumi; items=fetch_bangumi({'type':2,'tag':'百合','sort':'rank','limit':5}); assert len(items)>0; assert 'title' in items[0]; print(f'bangumi OK got {len(items)} items')"
    Expected Result: 返回 5 条百合主题动画
    Failure Indicators: 空列表 / KeyError
    Evidence: .omo/evidence/task-11-bangumi-yuri.txt

  Scenario: API 超时不崩溃
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.bangumi import fetch_bangumi; items=fetch_bangumi({'type':2,'tag':'不存在的xxx标签'}, limit=5); print(f'empty tag got {len(items)} items')"
    Expected Result: 返回空列表，不崩溃
    Failure Indicators: 抛异常
    Evidence: .omo/evidence/task-11-bangumi-empty.txt
  ```

  **Commit**: YES (Wave 2)
  - Message: `feat(fetchers): Bangumi API yuri/GL`
  - Files: `src/fetchers/bangumi.py`

- [ ] 12. Fetcher: open-meteo weather (5s timeout, fallback)

  **What to do**:
  - 创建 `src/fetchers/weather.py`：`fetch_weather(city: str) -> dict | None`
  - 内置城市经纬度查表（北京 39.9/116.4、上海 31.2/121.5 等；config.yaml `weather_city` 指定）
  - 使用 `httpx.get("https://api.open-meteo.com/v1/forecast", params={latitude, longitude, daily: "temperature_2m_max,temperature_2m_min,weather_code", timezone: "auto"}, timeout=5)`
  - 5 秒超时（open-meteo 在德国，中国大陆可能限流）
  - 失败/超时 → log warning + 返回 None（caller 在 renderer 层显示 "无法获取天气"）
  - 返回结构：`{today: {temp_max, temp_min, weather_code, description}}`
  - `weather_code` 转 description 用 open-meteo WMO 天气码表（内建映射：0=晴, 1-3=多云, 51-67=雨, 71-77=雪...）

  **Must NOT do**:
  - 不加 AccuWeather/和风天气等付费 API
  - 不缓存天气（每日报一次性抓取）
  - 不加 GPS 自动定位（config 写死城市）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: httpx + JSON + 静态映射表
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 8-11,13)
  - **Parallel Group**: Wave 2
  - **Blocks**: 15,16
  - **Blocked By**: 1, 7

  **References**:

  **External References**:
  - open-meteo API: `https://open-meteo.com/en/docs` — 参数 + 免费无 key
  - WMO 天气码: `https://open-meteo.com/en/docs#weathervariables` — weather_code 对照表

  **WHY Each Reference Matters**:
  - 确认免 key 免注册
  - WMO 天气码表用于数字转中文描述

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 天气获取成功
    Tool: Bash
    Preconditions: 网络可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.weather import fetch_weather; w=fetch_weather('北京'); assert w is not None; assert 'today' in w; assert 'temp_max' in w['today']; print(f'weather OK {w}')"
    Expected Result: 返回 dict 含今日温度 + 天气描述
    Failure Indicators: 返回 None / KeyError
    Evidence: .omo/evidence/task-12-weather-ok.txt

  Scenario: 超时回退"无法获取天气"（edge case: open-meteo 限流）
    Tool: Bash
    Preconditions: mock 网络不可用
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); import httpx; from unittest.mock import patch; from fetchers.weather import fetch_weather; 
      with patch('httpx.get', side_effect=httpx.TimeoutException('timeout')):
          w=fetch_weather('北京'); assert w is None; print('timeout fallback OK')"
    Expected Result: 输出 "timeout fallback OK"，返回 None
    Failure Indicators: 抛 TimeoutException 崩溃
    Evidence: .omo/evidence/task-12-weather-timeout.txt

  Scenario: 未知城市返回 None
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from fetchers.weather import fetch_weather; w=fetch_weather('不存在的城市名'); assert w is None; print('unknown city OK')"
    Expected Result: 返回 None
    Failure Indicators: 抛 KeyError
    Evidence: .omo/evidence/task-12-weather-unknown.txt
  ```

  **Commit**: YES (Wave 2)
  - Message: `feat(fetchers): open-meteo weather with 5s timeout`
  - Files: `src/fetchers/weather.py`

- [ ] 13. Fortune module (lunardate 正经黄历)

  **What to do**:
  - 创建 `src/fortune/fortune.py`：`get_fortune(date: date | None = None) -> dict`
  - 默认 `date=date.today()`
  - 使用 `lunardate` 库计算农历日期：`LunarDate.fromSolarDate(year, month, day)`
  - 返回结构：`{lunar_date: "农历X月X日", year_ganzhi: "甲辰年", shengxiao: "龙", yi: ["嫁娶", "出行", ...], ji: ["动土", "安葬", ...]}`
  - 宜忌列表从 lunardate 提取（如 lunardate 不直接提供宜忌，需内建简表或换用 `cnlunar` 库对比）
  - 严肃正经黄历风格，不生成 AI 趣版凶吉（scope EXCLUDE）
  - 验证 2026-07-11 农历日期正确：应匹配在线黄历查询结果
  - 闰月处理：测试已知闰月日期确保正确识别

  **Must NOT do**:
  - 不生成 AI 趣版凶吉（scope EXCLUDE）
  - 不加风水/八字深化（只宜忌 + 农历日期 + 干支 + 生肖）
  - 不加每日运势分数/幸运色（超范围）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 本地库查询 + 字段格式化
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (Wave 2, with Tasks 8-12)
  - **Parallel Group**: Wave 2
  - **Blocks**: 15,16
  - **Blocked By**: 1

  **References**:

  **External References**:
  - lunardate docs: `https://pypi.org/project/lunardate/` — `LunarDate.fromSolarDate()`
  - cnlunar docs: `https://pypi.org/project/cnlunar/` — 含宜忌（2022 后未更新，对比验证用）

  **WHY Each Reference Matters**:
  - lunardate 使用天文算法无年份 cap，稳定
  - cnlunar 可能含宜忌表，作为 fallback / 对比验证

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: 今日黄历正确
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from datetime import date; from fortune.fortune import get_fortune; f=get_fortune(date(2026,7,11)); assert f['lunar_date'] is not None; assert f['year_ganzhi'] is not None; assert 'yi' in f; assert 'ji' in f; print(f'fortune OK: {f}')"
    Expected Result: 返回含农历日期 + 干支 + 宜忌的非空 dict
    Failure Indicators: 空宜忌列表 / Key 缺失
    Evidence: .omo/evidence/task-13-fortune-today.txt

  Scenario: 2026-07-11 农历日期匹配在线参考
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from datetime import date; from fortune.fortune import get_fortune; f=get_fortune(date(2026,7,11)); print(f'lunar={f[\"lunar_date\"]}'); assert f['lunar_date'] is not None"
    Expected Result: 2026-07-11 应为农历五月廿八或廿九（需用在线黄历验证确切值并 assert）
    Failure Indicators: 农历日期偏差 > 1 天
    Evidence: .omo/evidence/task-13-fortune-validity.txt

  Scenario: 中文字符 UTF-8 正确编码
    Tool: Bash
    Preconditions: 无
    Steps:
      1. python -c "import sys; sys.path.insert(0,'news-agent/src'); from datetime import date; from fortune.fortune import get_fortune; f=get_fortune(date(2026,7,11)); s=str(f); s.encode('utf-8'); print('utf8 OK')"
    Expected Result: 输出 "utf8 OK"（无 UnicodeEncodeError）
    Failure Indicators: UnicodeEncodeError
    Evidence: .omo/evidence/task-13-fortune-utf8.txt
  ```

  **Commit**: YES (Wave 2)
  - Message: `feat(fortune): lunardate 正经黄历`
  - Files: `src/fortune/fortune.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .omo/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `pytest`, `pyinstaller --check`, lint. Review all changed files for: type suppression, empty catches, debug logging in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp), NewsSource ABC or any of 12 forbidden scope creep items.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (Worker 写入 → 主进程读取 → 渲染展示). Test 16 edge cases. Save to `.omo/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [16 tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `feat(scaffold): project setup + foundation modules` - pyproject.toml, config.yaml, src/db/, src/logging/, src/llm/, docker/, src/config/
- **Wave 2**: `feat(fetchers): RSS + RSSHub + HTML + Bangumi + weather + fortune` - src/fetchers/, src/fortune/
- **Wave 3**: `feat(curator): dedup + scoring + summary + worker entry + template` - src/curator/, src/worker.py, templates/
- **Wave 4**: `feat(ui): viewer + tray + conversation + main entry + autostart` - src/viewer/, src/tray/, src/conversation/, src/main.py, src/autostart/
- **Wave 5**: `feat(packages): task scheduler + pyinstaller + uninstall + tests` - scripts/, news-agent.spec, tests/
- **Final**: `test: full QA + plan compliance` - .omo/evidence/

---

## Success Criteria

### Verification Commands
```bash
# 项目结构
ls news-agent/src/                    # Expected: fetchers/ curator/ viewer/ tray/ db/ llm/ conversation/ main.py worker.py
ls news-agent/templates/              # Expected: daily.html
ls news-agent/tests/                  # Expected: test_*.py
ls news-agent/docker/                 # Expected: rsshub-docker-compose.yml

# 配置
cat news-agent/config.yaml             # Expected: 完整 schema (api_key_ref/sources/cost_ceiling/weather_city/hotkey/window_position)
python -c "import yaml; yaml.safe_load(open('news-agent/config.yaml'))"  # Expected: 无异常

# DB
python -c "import sqlite3; conn=sqlite3.connect('news-agent/data/state.db'); print(conn.execute('PRAGMA journal_mode').fetchone())"  # Expected: ('wal',)
python -c "import sqlite3; conn=sqlite3.connect('news-agent/data/state.db'); print(conn.execute('PRAGMA busy_timeout').fetchone())"  # Expected: (5000,)

# Worker 独立运行
pythonw news-agent/src/worker.py      # Expected: 抓取+处理+写入 SQLite，exit 0

# 主进程
pythonw news-agent/src/main.py --autostart  # Expected: 弹出播报窗口 → 关掉 → 托盘常驻 → Ctrl+Alt+N 唤回

# 测试
pytest news-agent/tests/ -v           # Expected: all pass

# Registry
reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v NewsAgent  # Expected: 运行后存在

# Task Scheduler
schtasks /Query /TN NewsAgentWorker   # Expected: 06:00 + 18:00 触发器存在

# PyInstaller
cd news-agent && pyinstaller news-agent.spec  # Expected: dist/news-agent/news-agent.exe
.\dist\news-agent\news-agent.exe       # Expected: 独立运行无 Python 依赖
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent（含 12 项 scope creep + 5 项原 EXCLUDE）
- [ ] All tests pass
- [ ] 16 edge cases 全部覆盖
- [ ] PyInstaller frozen exe 运行正常
- [ ] 卸载脚本清理干净（Run key + %APPDATA% + Task Scheduler + Start Menu）