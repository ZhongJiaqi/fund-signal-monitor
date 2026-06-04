# 基金加仓信号监控

每个交易日自动监控你关注的基金,触发预设加仓规则时推送到微信。**只做提醒,不下单。**

监控对象、阈值完全由你的 `config.json` 决定,代码里不含任何具体基金。支持 4 类通道:

| 通道 | 数据口径 | 信号 | 推送规则 | 适用 |
|---|---|---|---|---|
| **dividend** | 累计净值(分红还原) | MA250 / MA120 三档 | 有事件才推 | 低波动、分红型,看中长期回撤 |
| **shortma**(国内) | 单位净值 | MA20 单档(`close < MA20`) | 有事件才推 | 国内高波动品种,看短期超跌 |
| **shortma_overseas** | 单位净值 | MA20 单档 | **每日固定播报** | 海外 QDII / 跨境指数,每天扫一眼相对 MA20 位置 |
| **ndx**(可选) | 指数点位 + VIX | VIX 超阈值(默认 30) | 仅 VIX 首次突破时推 | 借恐慌指数做美股恐慌加仓提醒 |

4 类各走**独立**的 Server 酱微信推送,互不合并。海外通道是唯一"无事件也推"的——做日常状态汇报;其余三通道只在状态变化时推。

## 快速开始

```bash
git clone <your-fork-url> fund-signal-monitor
cd fund-signal-monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # akshare / pandas / requests

# 1. 配置你要监控的基金
cp config.example.json config.json
$EDITOR config.json

# 2. 配置微信推送密钥(Server 酱:https://sct.ftqq.com)
cp .env.example .env
$EDITOR .env

# 3. 先 dry-run 预览(不真发、不耗 Server 酱免费 5/天 额度)
.venv/bin/python monitor.py --dry-run

# 4. 确认无误后真实跑(会推到微信 + 弹 macOS 通知 + 写 state.json)
.venv/bin/python monitor.py
```

> 改推送内容/卡片格式/信号阈值时,**先 `--dry-run` 用真实数据预览一遍**再走真实推送 —— 避免误推、浪费当日额度。

## 配置 `config.json`

```json
{
  "dividend_assets": [
    { "fund_code": "510300", "fund_name": "沪深300ETF（示例）" }
  ],
  "shortma_assets": [
    { "fund_code": "159915", "fund_name": "创业板ETF（示例）", "sector": "创业板" }
  ],
  "shortma_overseas_assets": [
    { "fund_code": "513100", "fund_name": "纳指ETF（示例）" }
  ]
}
```

- `dividend_assets`:累计净值 + MA120/MA250 三档信号。
- `shortma_assets`:单位净值 + MA20 单档信号(**国内**,只在有事件时推)。可选 `sector` 字段,卡片渲染时作为方括号板块标签(如 `` `159915` [创业板]创业板ETF ``)展示。
- `shortma_overseas_assets`:单位净值 + MA20 单档信号(**海外**,每日必推一卡)。规则同 `shortma_assets`,但推送行为不同 —— 即使 7 只全在 MA20 之上无事件也会推一条状态卡。仅在 *全部* 取数失败时才跳过。`sector` 字段同样可选(QDII 一般不填,基金名已含"全球科技"等关键词)。
- 任一通道留空 `[]` 即关闭(海外留空 → 跳过每日播报)。`config.json` 已 gitignore,不会被提交;`config.example.json` 是模板。

> NDX/VIX 通道默认开启(无需配置基金);若不需要可在 `core/runner.py` 中跳过 `process_ndx`。VIX 阈值与 MA120 两档回撤比例定义在 `core/signals.py` 顶部常量,按需修改。

## 信号规则

### dividend · 三档信号(每只独立判断,全用严格小于 `<`)

| 信号 | 触发条件 | 加仓 |
|---|---|---|
| 信号一 | 净值 < MA250 | 1 份 |
| 信号二 | 净值 < MA120 × (1 − 6%) | 1 份 |
| 信号三 | 净值 < MA120 × (1 − 12%) | 2 份 |

3 个信号独立,可同时激活。"份"是相对加仓单位,**不含具体金额**,实际投入由你自定。

### shortma / shortma_overseas · MA20 单档

净值 < MA20 → 跌破 MA20 提醒(不显示份数,节奏自定)。**国内有事件才推,海外每天必推。**

### ndx · VIX 单档

VIX 超过阈值(默认 30,恐慌区)→ 加仓提醒(不显示份数)。

### 事件分类与卡片状态列(dividend + shortma + shortma_overseas 共用)

| Emoji | 事件 | 触发条件 |
|---|---|---|
| 🔴 | 首次激活 | 信号未触发 → 今天触发 |
| ⬇️ | 探底新低 | 持续激活期间净值刷新最低 |
| 🟢 | 持续激活 | 已激活但净值未刷新最低 |
| 🟡 | 临近 | 距下一档阈值 < 1%(陪跑提示) |
| ⚪ | 未激活 | 距阈值 ≥ 1% |

行排序按事件优先级:🔴 → ⬇️ → 🟢 → 🟡 → ⚪。同档按 fund_code 字典序。NDX 通道无状态跟踪,只在 VIX 首次突破阈值时推送。

## 输出

- 终端 markdown
- `latest_alert_dividend.md` / `latest_alert_shortma.md` / `latest_alert_shortma_overseas.md` / `latest_alert_ndx.md`(对应通道推送时)
- `latest_alert_errors.md`(取数失败诊断,不推送)
- `run.log`(主程序日志)
- `state.json`(状态对比,用于"首次激活才推送"机制)
- macOS 通知 + **Server 酱微信推送**(各通道独立一条,海外每日固定一条)

## 定时调度

### 方案 A:Cloudflare Workers cron 触发 GitHub Actions(推荐 — 准时、零本地依赖)

> **为什么不直接用 GitHub Actions schedule:** schedule cron 整点高负载会延迟数分钟到数小时,极端情况下整次跳过(本仓库 2026-06-04 实测漏跑)。Cloudflare Workers cron 精度 ±10 秒,调 GitHub Dispatch API 启动 workflow,微信约 10:00~10:02 收到。

架构:
```
Cloudflare Workers cron `0 2 * * 1-5` (±10s)
    → POST GitHub Dispatch API
    → daily-monitor.yml `workflow_dispatch`
    → monitor.py + Server 酱推送
```

子目录 `cf-cron-trigger/` 即 Cloudflare Worker 源码(详见该目录 README)。要点:

1. fork / 拷贝本仓库
2. fund-signal-monitor 仓库 Settings → Secrets and variables → Actions 配 2 个 secret:
   - `SERVERCHAN_SENDKEY` — Server 酱密钥
   - `FUND_CONFIG_B64` — 本地 `base64 -i config.json` 后粘贴(避免 commit)
3. workflow_dispatch 手动跑一次 dry-run 验证跨境取数 + 凭证 OK
4. 创建 GitHub Fine-grained PAT(仅本仓库 Actions:write)
5. `cd cf-cron-trigger && npx wrangler login && npx wrangler secret put GH_TOKEN`(粘贴 PAT)+ `wrangler secret put TRIGGER_TOKEN`(随机) + 可选 `wrangler secret put SERVERCHAN_KEY`(失败告警)
6. `npx wrangler deploy` 启用 worker cron
7. state.json 仍通过 `actions/cache` 持久化(key 带 run_id 写新版、restore-keys 模糊匹配读最近一次)

> 首次启用前建议先用 `bootstrap-state-cache.yml` 把本地 state.json 写进 cache(通过 `STATE_JSON_SEED_B64` secret),否则第一次跑会把"持续激活"误判为"首次激活"。
>
> GitHub-hosted runner 在境外,akshare 取国内基金净值通过腾讯/新浪 OSS 仍可访问(实测正常)。

### 方案 B:GitHub Actions schedule(不推荐,作历史保留)

直接用 `daily-monitor.yml` 启用 `schedule: [{cron: '0 2 * * 1-5'}]`。**不推荐**:整点高负载常延迟/跳过,做不到准时,本仓库已踩坑。仅作为 Cloudflare 故障时临时回滚选项。

### 方案 C:macOS launchd(本地后台,适合一直开机的 Mac 用户)

复制 `fund-signal-monitor.plist.example`,把里面的 `/path/to/fund-signal-monitor` 改成你的项目绝对路径,放到 `~/Library/LaunchAgents/` 下:

```bash
cp fund-signal-monitor.plist.example ~/Library/LaunchAgents/com.example.fund-signal-monitor.plist
# 编辑路径后:
launchctl load ~/Library/LaunchAgents/com.example.fund-signal-monitor.plist
launchctl list | grep fund-signal               # 查状态
launchctl start com.example.fund-signal-monitor  # 手动触发(会真实推送)
```

默认每个交易日 **10:00** 跑(基金净值是 T-1 的,上午看到后还有 13:00–15:00 申购窗口)。非交易日脚本自动安静退出。

**注意 launchd 的隐性脆弱性**:macOS 睡眠时 launchd 不会主动唤醒电脑,合盖期间 `StartCalendarInterval` 错过的任务靠 Dark Wake 补跑(整点常延迟 10-30 分钟,带电池或出门则可能 miss 当天)。如果不希望推送依赖电脑唤醒,优先选方案 A。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

**147 个单元测试**覆盖:MA / 三档信号 / MA20 / VIX / 首次触发 / 探底新低 / 状态逻辑 / next_threshold / 激活交易日数 / retry / 缓存 / Server 酱(含额度耗尽) / 代理 setup / VIX 双源 / IO 集成 / dividend·shortma·NDX 卡片渲染 / dry-run 副作用阻断 / 海外通道每日必推 / 配置加载。

## 代码结构

```
monitor.py            入口薄壳 + 测试 re-export
core/
  config.py           读 config.json / config.example.json
  signals.py          纯函数(MA / 三档信号 / MA20 / VIX / 事件分类 / 阈值定位 / 激活天数)
  data_io.py          IO(代理 / retry / akshare / 缓存 / state.json / 日历缓存 / .env / logger)
  notify.py           推送(macOS + Server 酱)
  cards.py            Markdown 卡片(三通道合并卡 + state-cell renderer,shortma 国内/海外复用同一 builder)
  runner.py           主流程(process_asset / process_shortma_asset / process_ndx / main)
.github/workflows/
  daily-monitor.yml         monitor.py 主工作流(由 Cloudflare Worker workflow_dispatch 触发)
  bootstrap-state-cache.yml 一次性 cache seed 工具(避免首次跑误判)
cf-cron-trigger/            Cloudflare Workers 调度器(±10s 精度调 GitHub Dispatch API)
  src/index.js              纯 fetch worker:cron / scheduled + HTTP /trigger 端点
  wrangler.toml             worker 名 + cron 配置
```

## 红线

- 只做提醒,**绝不下单、买卖、转账**。脚本只生成文本。
- 数据取不到一律标"未取到",不编造。
- 技术指标不保证未来有效,**不构成投资建议**。
- 不显示具体加仓金额(dividend 只显示"X 份",shortma / shortma_overseas / ndx 完全不显示份数)。

## 数据口径说明

- **累计净值**(dividend 通道):分红还原,走势平滑,避免分红除权对 MA 的扰动 —— 适合做中长期回撤判断。
- **单位净值**(shortma / shortma_overseas 通道):贴近短线交易习惯,配合 MA20 看短期超跌。
- **NDX/VIX**:指数点位走行情源,VIX 走 Yahoo Finance(主)+ CBOE delayed_quotes(备)双源容错。

## 已知限制

- 公募基金净值 T+1 公布(当晚),10:00 跑时拿到的是 T-1 数据。
- **海外 QDII 净值披露通常比国内基金晚一个交易日**(根据海外市场收盘后才算 NAV),所以海外通道卡片的 `数据截至` 字段会比国内通道旧一天 —— 正常,不是 bug。
- VIX 数据源在境外,本地 launchd 跑时部分地区需本地代理(在 plist 的 `EnvironmentVariables` 里配,不需要可删除该块);GitHub Actions runner 在境外可直连,无需配代理。
- Server 酱免费版每天 5 条额度,日均 2-4 条属正常使用(海外通道固定占 1 条)。
- macOS launchd 依赖电脑唤醒,详见上方"定时调度"章节的脆弱性提醒。

## License

[MIT](LICENSE)
