# fund-monitor-cf-cron-trigger

Cloudflare Worker 用 cron 触发 [fund-signal-monitor](https://github.com/ZhongJiaqi/fund-signal-monitor) 的 GitHub Actions `daily-monitor.yml` workflow。

## 为什么

GitHub Actions `schedule` cron 整点延迟/跳过严重(6/04 就漏跑一次)。Cloudflare Workers cron 精度 ±10 秒,调 GitHub Dispatch API → runner 启动 ~30 秒 → 微信 10:01 收到。**实用意义上的 10:00 准时**。

## Secrets

```bash
npx wrangler secret put GH_TOKEN        # GitHub Fine-grained PAT, Actions:write, repo: ZhongJiaqi/fund-signal-monitor
npx wrangler secret put TRIGGER_TOKEN   # 自定义 bearer, 保护 /trigger HTTP 端点
npx wrangler secret put SERVERCHAN_KEY  # (可选) dispatch 失败时告警到 Server 酱
```

## Deploy

```bash
npx wrangler deploy
```

## 手动测试

```bash
# dry-run (推荐先测)
curl -H "Authorization: Bearer <TRIGGER_TOKEN>" \
  "https://fund-monitor-cron.<account>.workers.dev/trigger?mode=dry-run"

# production
curl -H "Authorization: Bearer <TRIGGER_TOKEN>" \
  "https://fund-monitor-cron.<account>.workers.dev/trigger?mode=production"
```

## 日志

```bash
npx wrangler tail
```
