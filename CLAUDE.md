# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目本质

每个交易日自动监控基金加仓时机,触发预设规则时推送到微信。**只发提醒,绝不下单**(红线)。

监控对象由 `config.json`(gitignore,模板见 `config.example.json`)决定,代码不含任何具体基金。三类通道:

- **dividend**:累计净值口径,MA250 / MA120 三档信号
- **shortma**:单位净值口径,MA20 单档信号(`close < MA20`)
- **ndx**:VIX 超阈值(默认 30)触发,数据走 Yahoo 主 + CBOE 备双源

三类各走**独立**的 Server 酱推送通道,不合并。**每类只有一种合并卡片**,推送标题与卡片标题语义一致 = `{通道} · {today}`。

## 不可变量(红线)

- **绝不下单/转账/买卖**。脚本只生成文本提醒,任何买入/卖出决策由人手动完成
- **数据未取到一律标"未取到",不编造**
- **不显示加仓的具体金额**。dividend 通道只显示相对"X 份",shortma / ndx 不显示份数
- **Server 酱免费版每天 5 条额度上限**。改动涉及推送内容/触发逻辑时:
  - 先 dry-run 生成最终 markdown 检视,确认再发真实推送
  - 不要为测试触发额外推送(浪费当日额度 + 误发消息)
  - 正常一天 1–3 条(三通道各最多 1 条),远低于上限

## 核心架构决策(读多文件才能理解)

### 1. 数据口径:dividend 用累计净值,shortma 用单位净值

- **累计净值**(`fund_open_fund_info_em(symbol, indicator='累计净值走势')`):分红已"加回"还原,走势平滑,避免分红除权对 MA 的扰动 —— 用于 dividend 通道的中长期回撤判断。
- **单位净值**(`indicator='单位净值走势'`):贴近短线交易习惯,配合 MA20 看短期超跌 —— 用于 shortma 通道。

`Asset` 只有 `fund_code` + `fund_name` 两字段,由 `core/config.py` 从配置构建。

### 2. 首次触发对比(state.json 机制)

只在"信号由未激活变为激活"时推送,避免持续满足条件时反复打扰。

`state.json` 记录上一次跑的每个信号状态。`first_triggered(prev, today)` 的语义:
- `today=True` 且 `prev != True` → 触发(prev 为 False / None / 缺失都视为基线未激活)
- `today=False/None` → 永远不触发

**调试时强制重推一次**:`rm state.json && launchctl start <你的 launchd label>`。

### 3. 各通道独立推送

dividend / shortma / ndx 各自一条独立 Server 酱推送:
- 标题各通道独立,正文 Markdown 各自构建(`build_dividend_card_md` / `build_shortma_card_md` / `build_ndx_card_md`)
- 触发判断各自独立

不要把多个通道混在一条消息里。

### 4. 代理处理的两面性

- **国内站点**(akshare 用的腾讯/新浪/中证 OSS):必须**不走代理**。脚本顶部主动清空 `HTTP_PROXY` 等环境变量并设 `NO_PROXY=*`
- **境外站点**(VIX 的 Yahoo Finance):**需要代理**(若你所在地区可直连则不需要)。脚本启动时把原代理变量存进 `_ORIG_PROXIES`,`fetch_vix_latest` 显式传 `proxies=_ORIG_PROXIES`
- **launchd 跑时**:进程默认不继承 shell 的代理变量,所以 plist 通过 `EnvironmentVariables` 显式注入 `http_proxy/https_proxy`。**这个坑只在 launchd 触发时暴露,手动跑发现不了**(若直连可删除该块)

### 5. 整体 120s 超时

akshare 内部 `requests` 不带 timeout,某数据源接口偶尔让脚本挂死。`main()` 启动时用 `signal.SIGALRM` 设 120s 整体硬超时,到点抛 `TimeoutError` 退出码 2。改这部分时不要去掉这个守护。

## 常用命令

```bash
# 运行(手动,会真实推送)
.venv/bin/python monitor.py

# 单元测试
.venv/bin/python -m pytest tests/ -q

# launchd 操作(label 以你的 plist 为准;改时间需同步改 plist 并 reload)
launchctl list | grep fund-signal
launchctl start <你的 launchd label>
launchctl unload ~/Library/LaunchAgents/<你的 plist>
launchctl load ~/Library/LaunchAgents/<你的 plist>

# 重置状态(让所有信号下次都"首次触发")
rm state.json && launchctl start <你的 launchd label>
```

## 代码组织

```
monitor.py            launchd 入口薄壳 + re-export 给测试(`from monitor import xxx` 仍 work)
core/
  config.py           读 config.json / config.example.json
  signals.py          纯函数:ma / evaluate_signals / evaluate_ma20_signal / detect_signal_event / next_threshold / compute_active_days
  data_io.py          IO:setup_proxy_env / with_retry / akshare 取数 / 缓存 / state.json(v1→v2 迁移)/ 交易日历(本地缓存 7 天)/ .env / logger
  notify.py           推送:send_macos_notification + send_serverchan(额度耗尽时额外弹 macOS 通知)
  cards.py            Markdown 卡片:build_dividend_card_md / build_shortma_card_md / build_ndx_card_md
  runner.py           主流程:process_asset / process_shortma_asset / process_ndx / main
tests/                121 个测试全过:纯函数 + IO 集成 + 通知 + 缓存 + retry + 配置加载 全覆盖
```

依赖方向:`runner → {cards, notify, data_io, signals, config}`,`cards → signals`,`signals` / `config` 零依赖。
**修改纯函数时严格 TDD**;修改 IO/取数函数时先在 REPL 探查 akshare 返回结构,不要假设字段名。

### mock 测试 patch 路径陷阱

`runner.py` 用 `from core.data_io import fetch_xxx` 把名字 binding 到 `core.runner` namespace。
测试要 patch **使用处**,不是定义处:

| 要 mock 的函数 | 正确 patch 路径 | 错误路径(无效) |
|---|---|---|
| fetch_fund_cumulative_nav 在 process_asset 内 | `core.runner.fetch_fund_cumulative_nav` | ~~`core.data_io.fetch_...`~~ |
| fetch_ndx / fetch_vix_latest 在 process_ndx 内 | `core.runner.fetch_xxx` | ~~`core.data_io.fetch_xxx`~~ |
| send_macos_notification 在 send_serverchan 内 | `core.notify.send_macos_notification` | ~~`monitor.send_macos_notification`~~ |
| requests.post 在 send_serverchan 内 | `core.notify.requests.post` | ~~`monitor.requests.post`~~ |

### shortma 通道要点

| 项 | 决定 |
|---|---|
| 数据口径 | **单位净值**(与 dividend 累计净值口径区分) |
| 取数接口 | `fetch_fund_unit_nav(code)`,akshare `indicator='单位净值走势'` |
| 缓存路径 | `nav_history_<code>_unit.csv` |
| 信号 | `close < MA20` → 激活(`evaluate_ma20_signal`) |
| 加仓金额 | **不显示**(高波动品种,节奏自定) |
| state.json 字段 | `shortma_assets` |
| 事件时机 | 沿用 first / new_low / still_active 三类,与 dividend 一致 |

### 信号编号(dividend,从浅到深)

| 信号 | 触发条件 | 加仓(份) | 阈值常量 |
|---|---|---|---|
| **信号一** | 净值 `<` MA250 | 1 | — |
| **信号二** | 净值 `<` MA120 × (1 − 6%) | 1 | `SIGNAL_2_DROP` |
| **信号三** | 净值 `<` MA120 × (1 − 12%) | 2 | `SIGNAL_3_DROP` |

**全部严格小于 `<`**。阈值常量(`SIGNAL_2_DROP` / `SIGNAL_3_DROP` / `VIX_THRESHOLD`)在 `core/signals.py` 顶部,按需修改。state.json 在 load 时自动从 v1 schema 迁移到 v2(信号 key 重映射,数据保留)。

### 三类事件(同一卡片,事件细节融入"状态"列)

dividend / shortma 通道有三类事件,**共用一种合并卡片**,事件细节下沉到"状态"列的 emoji + 文案:

| 事件 | 触发条件 | state.json 变化 |
|---|---|---|
| 🔴 首次激活 | 信号未触发 → 今天触发 | `signal_meta[sig].activated_at` 写入今天 |
| ⬇️ 探底新低 | 持续激活期间 close < lowest | `lowest_close` 刷新 |
| 🟢 持续激活 | 激活但 close ≥ lowest | meta 不变 |
| 🟡 临近 | 距下一档阈值 < 1% | — |
| ⚪ 未激活 | 距下一档阈值 ≥ 1% | — |

行排序按事件优先级:🔴 → ⬇️ → 🟢 → 🟡 → ⚪。`detect_signal_event` 返回 `('first' / 'new_low' / 'still_active' / None, new_lowest)`。失活时 signal_meta 该 key 整个清空,下次再激活算"首次"。

### VIX 双源 + 交易日历缓存

- **VIX**:Yahoo 主(3 次重试)→ 失败 fallback CBOE delayed_quotes(2 次重试)→ 仍失败 None。两源都在境外,不同 CDN 不同时挂的概率高
- **交易日历**:`trading_calendar.json` 本地缓存 7 天;`load_trading_calendar_cached()` 优先读盘;网络失败时若有缓存(即使过期)降级使用,无缓存才抛
- **akshare 取数**:`with_retry(fn, max_attempts=3, base_delay=2.0)` 指数退避,失败时 `latest_alert_errors.md` 写本地诊断**不推送**

### 设计取舍(不要再"优化"掉)

- **MA250 失活宽限带**:阈值附近反复触发就是设计本意,每次跨过 = 一次入场机会,不做去抖
- **持续激活每日推一条**:这是日常存在感汇报,本意如此,不做降频

## 凭证 / 配置

- `.env` 存 `SERVERCHAN_SENDKEY`(微信推送),已 gitignore。代码用 `load_env()` 解析,不依赖第三方
- `config.json` 存监控的基金列表,已 gitignore。模板 `config.example.json`
