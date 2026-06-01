# 基金加仓信号监控

每个交易日自动监控你关注的基金,触发预设加仓规则时推送到微信。**只做提醒,不下单。**

监控对象、阈值完全由你的 `config.json` 决定,代码里不含任何具体基金。支持三类通道:

| 通道 | 数据口径 | 信号 | 适用 |
|---|---|---|---|
| **dividend** | 累计净值(分红还原) | MA250 / MA120 三档 | 低波动、分红型,看中长期回撤 |
| **shortma** | 单位净值 | MA20 单档(`close < MA20`) | 高波动品种,看短期超跌 |
| **ndx**(可选) | 指数点位 + VIX | VIX 超阈值 | 借恐慌指数做美股恐慌加仓提醒 |

三类各走**独立**的 Server 酱微信推送,互不合并。

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
  ]
}
```

- `dividend_assets`:走累计净值 + MA120/MA250 三档信号。
- `shortma_assets`:走单位净值 + MA20 单档信号。可选 `sector` 字段,卡片渲染时作为方括号板块标签(如 `` `159915` [创业板]创业板ETF ``)展示;留空或省略则不展示。
- 任一通道留空 `[]` 即关闭。`config.json` 已 gitignore,不会被提交;`config.example.json` 是模板。

> NDX/VIX 通道默认开启(无需配置基金);若不需要可在 `core/runner.py` 中跳过 `process_ndx`。VIX 阈值与 MA120 两档回撤比例定义在 `core/signals.py` 顶部常量,按需修改。

## 信号规则

### dividend · 三档信号(每只独立判断,全用严格小于 `<`)

| 信号 | 触发条件 | 加仓 |
|---|---|---|
| 信号一 | 净值 < MA250 | 1 份 |
| 信号二 | 净值 < MA120 × (1 − 6%) | 1 份 |
| 信号三 | 净值 < MA120 × (1 − 12%) | 2 份 |

3 个信号独立,可同时激活。"份"是相对加仓单位,**不含具体金额**,实际投入由你自定。

### shortma · MA20 单档

净值 < MA20 → 加仓提醒(不显示份数,节奏自定)。

### ndx · VIX 单档

VIX 超过阈值(默认 30,恐慌区)→ 加仓提醒(不显示份数)。

### 推送时机(适用 dividend + shortma)

| Emoji | 事件 | 触发条件 |
|---|---|---|
| 🔴 | 首次激活 | 信号未触发 → 今天触发 |
| ⬇️ | 探底新低 | 持续激活期间净值刷新最低 |
| 🟢 | 持续激活 | 已激活但净值未刷新最低 |
| 🟡 | 临近 | 距下一档阈值 < 1%(陪跑提示) |
| ⚪ | 未激活 | 距阈值 ≥ 1% |

NDX 通道只在 VIX 首次突破阈值时推送(无状态跟踪)。

## 输出

- 终端 markdown
- `latest_alert_dividend.md` / `latest_alert_shortma.md` / `latest_alert_ndx.md`(对应通道触发时)
- `latest_alert_errors.md`(取数失败诊断,不推送)
- `run.log`(主程序日志)
- `state.json`(状态对比,schema v2,用于"仅首次激活才推送")
- macOS 通知 + **Server 酱微信推送**(各通道独立一条)

## 定时任务(macOS launchd)

复制 `fund-signal-monitor.plist.example`,把里面的 `/path/to/fund-signal-monitor` 改成你的项目绝对路径,放到 `~/Library/LaunchAgents/` 下:

```bash
cp fund-signal-monitor.plist.example ~/Library/LaunchAgents/com.example.fund-signal-monitor.plist
# 编辑路径后:
launchctl load ~/Library/LaunchAgents/com.example.fund-signal-monitor.plist
launchctl list | grep fund-signal               # 查状态
launchctl start com.example.fund-signal-monitor  # 手动触发(会真实推送)
```

默认每个交易日 **10:00** 跑(基金净值是 T-1 的,上午看到后还有 13:00–15:00 申购窗口)。非交易日脚本自动安静退出。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

**121 个单元测试**覆盖:MA / 三档信号 / MA20 / VIX / 首次触发 / 探底新低 / 状态逻辑 / next_threshold / 激活交易日数 / retry / 缓存 / Server 酱(含额度耗尽) / 代理 setup / VIX 双源 / IO 集成 / state v1→v2 迁移 / 配置加载 / NDX 卡片。

## 代码结构

```
monitor.py            launchd 入口薄壳 + 测试 re-export
core/
  config.py           读 config.json / config.example.json
  signals.py          纯函数(MA / 三档信号 / MA20 / VIX / 事件分类 / 阈值定位 / 激活天数)
  data_io.py          IO(代理 / retry / akshare / 缓存 / state v2 迁移 / 日历缓存 / .env / logger)
  notify.py           推送(macOS + Server 酱)
  cards.py            Markdown 卡片(三通道合并卡 + state-cell renderer)
  runner.py           主流程(process_asset / process_shortma_asset / process_ndx / main)
```

## 红线

- 只做提醒,**绝不下单、买卖、转账**。脚本只生成文本。
- 数据取不到一律标"未取到",不编造。
- 技术指标不保证未来有效,**不构成投资建议**。
- 不显示具体加仓金额。

## 数据口径说明

- **累计净值**(dividend 通道):分红还原,走势平滑,避免分红除权对 MA 的扰动 —— 适合做中长期回撤判断。
- **单位净值**(shortma 通道):贴近短线交易习惯,配合 MA20 看短期超跌。
- **NDX/VIX**:指数点位走行情源,VIX 走 Yahoo Finance(主)+ CBOE delayed_quotes(备)双源容错。

## 已知限制

- 公募基金净值 T+1 公布(当晚),10:00 跑时拿到的是 T-1 数据。
- VIX 数据源在境外,部分地区需本地代理(在 plist 的 `EnvironmentVariables` 里配,不需要可删除该块)。
- Server 酱免费版每天 5 条额度,日均 0–2 条属正常使用。

## License

[MIT](LICENSE)
