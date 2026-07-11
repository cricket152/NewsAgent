# Draft: news-agent (常驻Agent + 分布式新闻Agent)

## 项目定位
打开电脑时主动推送精选日报（新闻+天气+凶吉），后台常驻可对话Agent随时回答问题。从"一次性弹窗工具"升级为"个人助理 + 多Agent协作系统"。

环境：B:\Code\Dev\news-agent（空目录全新项目），Windows平台，非git repo。

## Requirements (confirmed - 用户已决策)

### 进程拓扑：双进程 + SQLite中转
- 主Agent进程：常驻后台、轻量、响应用户对话
- 新闻Agent worker进程：独立、负责抓取+LLM处理，可崩溃可重试
- 通信：主进程和worker通过SQLite表通信（worker写`articles`表，主Agent读）
- 优势：负载隔离、各崩各的、抓取不阻塞对话

### 交互UX：托盘+快捷键唤出窗口
- 后台常驻系统托盘图标
- 快捷键（如Alt+Space或自定义）唤出HTML窗口
- **开机自启动**：开机直接弹出当日播报窗口，关掉后转托盘常驻
- 关掉窗口后仍可随时用快捷键唤回
- 参考：Clash Verge / Everything 风格
- 前端：pywebview（Edge WebView2）+ HTML/CSS/JS
- 默认无打扰，按需打开

### LLM策略：纯云API（DeepSeek）
- 全部走云API，不在本地跑模型
- **厂商：DeepSeek，模型名 `deepseek-v4-flash`**（已确认 m0010 + Metis m0017 修正）
  - 注意：`deepseek-chat` 将于 2026-07-24 UTC 弃用，必须用 `deepseek-v4-flash`
  - 默认非 thinking 模式（`extra_body={"thinking": {"type": "disabled"}}`），TTFB ~30s 不可接受
  - 系统提示放 messages[0] 利用 auto-caching（98% prefix 重复成本节省）
  - 无官方 DeepSeek SDK，用 OpenAI SDK + `base_url=https://api.deepseek.com`
- 成本控制（Metis default）：
  - 每日上限 50,000 tokens（约 $0.007/day @ v4-flash 费率）
  - 累积 `response.usage.total_tokens` 写 SQLite `daily_usage` 表
  - 超额 → 新闻降级为仅显示标题（不生成 AI 摘要）；chat 提示"今日额度已用完"
- 调用规则：exponential backoff retry (1s/2s/4s/8s/16s, max 5)、timeout=30s/请求；已知 2026-03-30 有过 7 小时大故障，retry 逻辑必须有

### 新闻Agent的skill：重prompt型
- skill包含完整Agent instruction：兴趣领域 + 站点白名单 + 评分标准 + 抓取方式提示 + 输出格式 + 去重/聚类策略
- 拿到skill能独立运行一段时间，不只是config
- **兴趣领域（已确认 m0010）**：
  - AI / 科技前沿
  - 编程 / 开源动态
  - 游戏：明日方舟（肉鸽版本/活动/卡池/攻略等）
  - 动画：百合、MAD / 漫剪
- **站点白名单**：由 Prometheus 在 plan 阶段推荐第一批源（按兴趣领域对应中文/英文学界+社区+官方），用户可在 config.yaml 调整
- **抓取频率（已确认 m0010）**：每日2次（6AM + 18PM），按计划抓取写SQLite

## Technical Decisions (已确认)
- Python后端
- pywebview前端（Edge WebView2）
- SQLite作为进程间通信和数据存储
- httpx + bs4 抓取，feedparser RSS
- open-meteo 天气（免费免key）
- 黄历（lunardate/cnlunar本地库或API）
- Jinja2 渲染HTML

## Research Findings
- pywebview是Windows上跑HTML UI的最佳选择（启动快、用本地Edge WebView2、原生窗口感）
- open-meteo是免费免key的天气API，无需注册
- 黄历可用Python本地库lunardate/cnlunar，不必依赖外部API

## 已确认问题（用户 m0010 一次性回答）

1. **兴趣领域**：
   - AI / 科技前沿
   - 编程 / 开源动态
   - 游戏：明日方舟
   - 动画：百合、MAD / 漫剪
2. **凶吉风格**：正经黄历（宜忌/方向/值神），不走AI趣版 → 走本地库 cnlunar/lunardate
3. **LLM厂商**：DeepSeek
4. **抓取频率**：每日2次（6AM + 18PM）
5. **窗口触发**：开机直接弹出 + 后续快捷键唤出

## Scope Boundaries（已确认的边界）
- INCLUDE：
  - 双进程架构（主Agent + 新闻Agent worker）
  - 托盘+快捷键弹窗 + 开机自启动
  - 每日播报（新闻+天气+正经黄历凶吉）
  - 常驻可对话Agent（云LLM驱动，DeepSeek）
  - skill化新闻抓取（重prompt型）
  - 泛化信息（天气/凶吉）走权威源/本地库，不走LLM生成
- EXCLUDE：
  - 本地模型部署（用户选纯云API）
  - 多用户/SaaS（这是单机单人工具）
  - 移动端（仅Windows桌机）
  - 语音交互（暂定）
  - AI趣版凶吉（用户选正经黄历）
  - **MUST NOT HAVE（Metis m0017 锁定的 12 项 scope creep）**：
    1. `NewsSource` 抽象基类/OOP 源层级（4 域 ~10 源用 YAML config + 函数足够）
    2. config 文件热重载 / watchdog 监控
    3. 插件系统 / extension architecture
    4. 用户认证 / RBAC / 多角色
    5. Web admin dashboard / Flask 后台
    6. i18n / 多语言国际化
    7. 新闻分析图表 / Matplotlib 趋势图 / 情感分析可视化
    8. 自动更新器 / 自升级机制
    9. 完整 Markdown 渲染器（marked.js + highlight.js）；chat 用 `<pre>`+`<p>` 足够
    10. 向量库 / RAG / ChromaDB / 本地知识库检索
    11. 并行多 worker 抓取（2 次/日 ×~10 源，串行 httpx 已够快且降低封号风险）
    12. "智能"推荐算法 / 协同过滤（评分规则写在 prompt 里，无 ML）

## Test Strategy Decision（已确认 - 用户 m0010 / m0016）
- **Infrastructure exists**: NO（全新空项目）
- **Automated tests**: YES - Tests-after（不设 TDD 防止因 infra 不足卡进度）
- **Framework**: pytest + pytest-asyncio；网络请求 mock 用 `pytest-httpx`
- **Agent-Executed QA**: ALWAYS（每任务必带，覆盖 happy path + 失败/边缘场景）
  - UI / 交互：Playwright（启动 → 断言 DOM + 截图）
  - 抓取 / 存储：worker 跑一次 → `sqlite3 articles.db` 查 `articles` 表结构 + 行数
  - LLM 调用：真实 DeepSeek 调用 1 次 mock 新闻输入 → 断言返回非空 + token 计入 `daily_usage`
  - 自启动：`reg query HKCU\...\Run` / `schtasks /Query` 验证注册项存在
  - 双进程：worker 进程崩溃注入 → 断言主进程不崩、UI 继续可用
  - 黄历：`lunardate` 对照已知 2026 农历日期断言正确
  - 天气：`httpx.get(open-meteo)` 断言 200 + 含 temperature 字段；注入 5s 延迟 mock → 断言降级"无法获取天气"
  - DB 并发：worker 写入时主进程读 → 断言不阻塞、`PRAGMA integrity_check`=ok

## Important Technical Implementation Details（Metis m0017 11 项关键修正，plan 必须强制）

### 1. Windows 自启动
- 使用 Registry Run key `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`（**禁止 Startup 文件夹** - Win10/11 有 SmartScreen 最多 10 分钟延迟）
- 启用时同时删除 `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run\NewsAgent`（避免用户在 Task Manager 禁过后永久不启）
- Run key 值必须用 `pythonw.exe`（**禁止 `python.exe`** - 会闪黑框）
- 设 `--autostart` flag 区分"开机弹出" vs "快捷键唤出"行为
- 显式 `os.chdir(os.path.dirname(os.path.abspath(__file__)))` 处理 Run key 默认 CWD=`C:\Windows\System32` 问题
- 分发后：PyInstaller frozen exe 加 `--noconsole --windowed`

### 2. 双进程 Worker 防护
- Worker 是纯 CLI — **禁止 import `webview`/`tkinter`/任何 GUI 库**（pywebview Issue #1387 两进程不能共享 WebView2）
- Worker 仅可 import: `httpx, bs4, feedparser, sqlite3, openai, lunardate, yaml`
- Task Scheduler 直接触发 `pythonw.exe worker.py`（**不通过主进程**），主崩 worker 不停
- PID lock file `%TEMP%/news-agent-worker.lock` 防止 6AM/18PM 重叠
- 硬超时 15 分钟（`signal.alarm(900)` 或 watchdog timer）防网络挂起僵尸进程
- Task Scheduler 设 `StartWhenAvailable=True`：错过的触发在下次开机即补跑，不补历史

### 3. pywebview 单例 + 窗口行为
- 单例锁：Windows named mutex `Global\NewsAgentTray`；第二实例用 WM_COPYDATA 发信号给第一实例后退出
- close=hide NOT destroy；只有托盘菜单"退出"才真正退出进程
- **禁止 `hidden=True` + `window.show()`** 模式（pywebview Issue #1822 - focus stealing）
- WebView2 冷启动 4s+，需 <1000ms splash（tkinter Toplevel 或 Win32 MessageBox）在 WebView2 init 前展示
- 拦截 `WM_QUERYENDSESSION` 保存对话状态到 SQLite、释放 mutex
- 窗口位置持久化：`window_x/y/w/h` 写 config，下次启动恢复
- 多显示器：默认主显示器居中，保存上次位置

### 4. SQLite WAL + 并发
- `PRAGMA journal_mode=WAL;` + `PRAGMA busy_timeout=5000;` 在 DB init 强制执行
- Worker：批 INSERT → 立即 COMMIT；**禁止**持有 transaction 进行 HTTP 请求
- 主进程：只读连接 `sqlite3.connect("file:articles.db?mode=ro", uri=True)`
- Schema 版本管理：`CREATE TABLE schema_version (version INTEGER);` + 启动检查 + 迁移
- articles.url UNIQUE 约束（永久去重）；3 天内标题相似的聚类为"同一事件变体"

### 5. DeepSeek API 规则
- 模型名硬编码 `deepseek-v4-flash`（**禁用 `deepseek-chat`**，2026-07-24 弃用）
- 每次 `chat.completions.create(..., extra_body={"thinking": {"type": "disabled"}}, timeout=30)`
- 429/503 exponential backoff: 1s→2s→4s→8s→16s, max 5 次
- 成本上限 50K tokens/day（每日 0.007 USD），超额 → news 仅显示标题、chat 提示"今日额度已用完"
- 系统提示放 messages[0] 利用 auto-caching 98% 成本节省
- 用 OpenAI SDK + `base_url=https://api.deepseek.com`（无官方 DeepSeek SDK）

### 6. RSSHub-first 抓取
- B 站/微博/NGA **强制走 RSSHub**（直接 API 需 wbi 签名 + CloudFlare；B 站 2026-01 法务威胁 API doc 仓库）
- 项目内置本地 RSSHub docker-compose（`docker run -d -p 1200:1200 diygod/rsshub`）作为主路径
- 公共 RSSHub 实例仅作 fallback
- 配置源 pattern：`type: rss | rsshub | html | api`
- dhmy RSS、Bangumi api.bgm.tv（百合/GL 元数据免费免认证）、PRTS Wiki（prts.wiki 无 CF）都直连

### 7. 时间戳全部 UTC
- 内部存储用 `datetime.utcnow()`；只在前端展示时转 local time
- 免疫 DST、手动改时钟、NTP 同步对数据的影响

## Defaults Applied（用户可推翻 - 来自 Metis 10 问）

1. **API key 存储** → `keyring` + Windows Credential Manager；fallback `%APPDATA%/news-agent/.env` with restricted ACL
2. **对话历史持久化** → SQLite `conversations` 表，按日期分区，30 天保留；接近 ~64K 有效 token 时截断最旧消息带 "[已省略早期对话]" 标记
3. **Worker 触发** → Task Scheduler 直接 `pythonw.exe worker.py` + PID lock（详见 Implementation Details #2）
4. **config.yaml 完整 schema** → `api_key_ref` / `sources`(per-domain list) / `cost_ceiling_daily_tokens` / `weather_city` / `hotkey_binding` / `window_position`
5. **分发方式** → PyInstaller frozen exe（`--noconsole --windowed --collect-all webview`；显式打包 `WebView2Loader.dll` + `Microsoft.Web.WebView2.Core.dll`）
6. **卸载流程** → 删除 Run key → 删 `%APPDATA%/news-agent/` → 删 Start Menu 快捷方式 → 删 Task Scheduler 任务
7. **多显示器** → 默认主显示器居中；保存上次位置到 config
8. **日志** → Python `logging` → `%APPDATA%/news-agent/logs/`，daily rotation 7 天保留；每进程独立 `main.log` / `worker.log`
9. **新闻去重** → URL 永久去重（SQLite UNIQUE on `articles.url`）；3 天内标题相似的聚类为变体
10. **成本上限** → 50,000 tokens/day（约 $0.007/day @ v4-flash）；超额降级（详见 #5）

## Edge Cases（plan QA 必须覆盖 16 项）

1. **开机无网** → 主进程显示缓存数据+"上次更新:X小时前"；chat 显示"当前无网络连接"；Worker 静默退出（下次触发重试）
2. **API key 失效** → 托盘通知"API Key 已失效，请更新配置"；不崩、显示上次成功缓存
3. **DeepSeek 7+ 小时大故障** → 新闻 headlines-only；chat 降级"DeepSeek 服务暂时不可用，请稍后重试"；exp backoff
4. **多日未开机** → StartWhenAvailable 下次开机立即跑 Worker；不补历史；弹窗"已X天未获取新闻"
5. **上次 Worker 还在跑就到下次触发** → PID lock + 15 分钟 force-release 后新 worker 接续
6. **SQLite 还是被 lock（极小概率）** → Worker retry 3 × 5s，仍失败则 log 错误退出；主进程显示 stale data 不崩
7. **系统时钟跳变** → 内部 UTC 不受影响；展示时按时区转换
8. **磁盘满** → SQLite write 失败 → 写 stderr + clean exit；UI 提示；30 天 article 保留策略自动删旧
9. **杀毒软件杀进程** → PyInstaller signed exe（若可能）；5 分钟心跳 log 便于排查
10. **多用户 Windows 同时登录** → 各用户独立 `%APPDATA%/news-agent/`、独立 HKCU Run key、互不干扰
11. **高 DPI 125%/150%/200%** → HTML 用 rem/em；Playwright 模拟 100/125/150/200% 连续断言排版无错
12. **PyInstaller 漏 WebView2Loader.dll** → `--collect-all webview` + explicit include `webview/lib/win-x64/WebView2Loader.dll`、`Microsoft.Web.WebView2.Core.dll`
13. **config 文件损坏** → try/except 加载失败时弹对话框提示、回退默认值、不崩
14. **源站点改 HTML 结构** → Worker 日志警告 "selector '.news-title' returned 0 results for source X"；不崩
15. **本地 RSSHub 容器挂了** → docker-compose primary 失败时降级到公共实例 fallback（只作 fallback 不依赖）
16. **python.exe 而非 pythonw.exe 控制台闪现** → Run key 必须用 `pythonw.exe`；frozen exe 用 `--noconsole`

## Open Questions
- （已清空 — 所有用户决策完成，可进入 Plan Generation）