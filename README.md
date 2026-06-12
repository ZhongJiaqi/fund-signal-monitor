# 基金加仓信号监控

每个 A 股交易日 10:00 北京自动监控你关注的基金,触发预设加仓规则时推送通知。**只做提醒,不下单。**

监控对象、阈值完全由 `config.json` 决定,代码里不含任何具体基金。

## 4 类信号通道

| 通道 | 数据口径 | 信号 | 推送 |
|---|---|---|---|
| **dividend** | 累计净值(分红还原) | MA250 / MA120 三档 | 有事件才推 |
| **shortma**(国内) | 单位净值 | MA20 单档(`close < MA20`) | 有事件才推 |
| **shortma_overseas** | 单位净值 | MA20 单档 | **每日固定播报** |
| **ndx**(可选) | 指数点位 + VIX | VIX 超阈值(默认 30) | VIX 首次突破才推 |

## 2 个推送渠道(可二选一或并存)

| 渠道 | 触达 | 详情承载 | 状态 |
|---|---|---|---|
| **飞书**(默认) | 群机器人 webhook 发摘要卡片 + 按钮 | 飞书云文档原生渲染 3 张完整表格(列宽控制 / emoji / 板块独立列) | ✅ 主通道 |
| **ServerChan**(备选) | 方糖服务号微信公众号 | 微信卡片渲染 markdown 表格 | ⚠️ `sctapi.ftqq.com` 当前对 Cloudflare Workers + GH runner 出口都反爬,用前需 curl 实测链路 |

`core/notify.py` 同时保留 `send_feishu_summary_card` 和 `send_serverchan` 函数,`core/runner.py` 默认调飞书。完整迁移背景见 [HANDOFF.md](HANDOFF.md)。

## 快速开始

```bash
git clone <your-fork-url> fund-signal-monitor
cd fund-signal-monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp config.example.json config.json && $EDITOR config.json   # 1. 配监控基金
cp .env.example .env && $EDITOR .env                        # 2. 配推送凭证
.venv/bin/python monitor.py --dry-run                       # 3. 先 dry-run 预览
.venv/bin/python monitor.py                                 # 4. 真实跑(推送 + 写 state.json)
```

`.env` 字段:
- `FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/<uuid>` — 飞书必填
- `LARK_DOC_ID=<docx_token>` — 飞书云文档,详情见下
- `SERVERCHAN_SENDKEY=SCT...` — 微信可选

飞书云文档承载完整表格(避开飞书消息流移动端折叠限制),需要 [`@larksuite/cli`](https://github.com/larksuite/cli)。**首次设置 5 分钟**:飞书开放平台建自建应用(勾云文档读写 + 群消息发送权限)→ `lark-cli config init` 非交互鉴权 → `lark-cli docs +create` 一次拿到 doc_id 写进 `.env`。之后 monitor.py 每天 `lark-cli docs +update --doc-format xml` overwrite 同一 doc_id。

## 信号规则

### dividend · 三档(净值严格 `<` 阈值)

| 信号 | 触发条件 | 加仓 |
|---|---|---|
| 信号一 | 净值 < MA250 | 1 份 |
| 信号二 | 净值 < MA120 × (1 − 6%) | 1 份 |
| 信号三 | 净值 < MA120 × (1 − 12%) | 2 份 |

3 个信号独立,可同时激活。「份」是相对加仓单位,不含具体金额。

### shortma / shortma_overseas · MA20 单档

净值 `< MA20` → 跌破 MA20 提醒。**国内有事件才推,海外每天必推。**

### ndx · VIX 单档

VIX > 30(默认,恐慌区)→ 加仓提醒。

### 事件分类(所有通道共用)

| Emoji | 事件 | 触发 |
|---|---|---|
| 🔴 | 首次激活 | 未触发 → 今天触发 |
| ⬇️ | 探底新低 | 已激活期间净值刷新最低 |
| 🟢 | 持续激活 | 已激活但未刷新最低 |
| 🟡 | 临近 | 距下一档阈值 < 1% |
| ⚪ | 未激活 | 距阈值 ≥ 1% |

行排序按事件优先级:🔴 → ⬇️ → 🟢 → 🟡 → ⚪。

## 定时调度

**推荐 Cloudflare Workers cron + GH Actions** —— Workers cron 精度 ±10 秒,调 GitHub Dispatch API 启动 workflow,微信/飞书约 10:00–10:02 收到。GH Actions 原生 `schedule` 也兜底(`15 3 * * 1-5` 北京 11:15)防 CF 平台漏跑。

Worker 源码: [`cf-cron-trigger/`](cf-cron-trigger/)

**不推荐 macOS launchd 与云端并行**:两条独立链路 state.json 互不知情会双发(6/9 实测踩坑)。若想留 launchd 作回退,plist 必须重命名 `.plist.disabled` 防开机/登录被 launchd auto-load。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

161 个单元测试覆盖 MA / 三档信号 / MA20 / VIX / 事件分类 / next_threshold / 激活天数 / retry / 缓存 / 推送通道(含额度耗尽 / 代理 setup / VIX 双源)/ 卡片渲染 / dry-run 副作用阻断 / 配置加载。

## 代码结构

```
monitor.py                入口薄壳 + 测试 re-export
core/
  config.py               读 config.json
  signals.py              纯函数(MA / 三档信号 / MA20 / VIX / 事件分类)
  data_io.py              IO(代理 / retry / akshare / 缓存 / state.json / 日历缓存 / .env / logger)
  notify.py               推送(macOS / 飞书摘要卡 / ServerChan)
  cards.py                Markdown 卡片 + 飞书云文档 XML(build_combined_xml)
  runner.py               主流程
.github/workflows/
  daily-monitor.yml       monitor.py 主工作流(由 CF Worker 或 GH schedule 触发)
cf-cron-trigger/          Cloudflare Workers 调度器(±10s 精度调 GitHub Dispatch API)
```

## 红线

- 只做提醒,**绝不下单、买卖、转账**
- 数据取不到一律标"未取到",不编造
- 技术指标不保证未来有效,**不构成投资建议**
- 不显示具体加仓金额(dividend 只显示"X 份",其他通道完全不显示份数)

## 已知限制

- 公募基金净值 T+1 公布(当晚),10:00 跑时拿到的是 T-1 数据。海外 QDII 比国内多延迟 1 个交易日
- VIX 数据源在境外,本地 launchd 跑可能需代理(plist `EnvironmentVariables` 配);GH Actions runner 在境外可直连
- ServerChan 免费版 5 条/天额度。飞书 webhook 100 条/分钟 + 5 条/秒,无每日额度

## License

[MIT](LICENSE)
