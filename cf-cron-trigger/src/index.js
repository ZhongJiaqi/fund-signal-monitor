// fund-signal-monitor Cron Trigger
//
// 工作日北京 10:00 调 GitHub Dispatch API 触发 daily-monitor.yml (production mode)。
// Cloudflare Workers cron 精度 ±10 秒 → GitHub Actions runner 启动 ~30 秒 → 微信收到 ~10:01。
//
// Secrets (set via `wrangler secret put`):
//   GH_TOKEN       — Fine-grained PAT, repo: ZhongJiaqi/fund-signal-monitor, Actions: read-write
//   TRIGGER_TOKEN  — 自定义 bearer token, 保护 /trigger 端点的手动测试
//   SERVERCHAN_KEY — (可选) Server 酱 sendkey, dispatch 失败时告警

const REPO = 'ZhongJiaqi/fund-signal-monitor';
const WORKFLOW = 'daily-monitor.yml';
const USER_AGENT = 'fund-monitor-cf-cron-trigger';

async function dispatchWorkflow(env, mode = 'production') {
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': USER_AGENT,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: 'main', inputs: { mode } }),
  });
  const text = await res.text();
  return {
    ok: res.ok,
    status: res.status,
    body: text || '(empty)',
    triggeredAt: new Date().toISOString(),
    mode,
  };
}

async function alertServerChan(env, title, desp) {
  if (!env.SERVERCHAN_KEY) return;
  try {
    await fetch(`https://sctapi.ftqq.com/${env.SERVERCHAN_KEY}.send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ title, desp }).toString(),
    });
  } catch (e) {
    console.error('ServerChan alert failed:', e.message);
  }
}

export default {
  // cron: workers 启动 scheduled 事件,wrangler.toml 里配 crons
  async scheduled(event, env, ctx) {
    const result = await dispatchWorkflow(env, 'production');
    if (!result.ok) {
      console.error('cron dispatch failed', JSON.stringify(result));
      ctx.waitUntil(alertServerChan(
        env,
        '⚠️ fund-monitor cron 触发失败',
        `Cloudflare Worker 调 GitHub Dispatch API 返回 ${result.status}\n\n` +
        `时间: ${result.triggeredAt}\n响应: ${result.body.slice(0, 500)}`
      ));
      throw new Error(`Dispatch ${result.status}: ${result.body.slice(0, 200)}`);
    }
    console.log('cron dispatch ok', JSON.stringify(result));
  },

  // HTTP: /trigger 手动测试, / 返回状态
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/trigger') {
      const auth = request.headers.get('Authorization') || '';
      const expected = `Bearer ${env.TRIGGER_TOKEN}`;
      if (auth !== expected) {
        return new Response('Unauthorized', { status: 401 });
      }
      const mode = url.searchParams.get('mode') === 'dry-run' ? 'dry-run' : 'production';
      const result = await dispatchWorkflow(env, mode);
      return Response.json(result, { status: result.ok ? 200 : 502 });
    }

    return new Response(
      `fund-signal-monitor cron trigger\n\n` +
      `Schedule: workdays 02:00 UTC (Beijing 10:00)\n` +
      `Target: ${REPO} / ${WORKFLOW}\n\n` +
      `Manual test:\n` +
      `  curl -H "Authorization: Bearer <TRIGGER_TOKEN>" \\\n` +
      `    https://<worker-url>/trigger?mode=dry-run\n`,
      { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }
    );
  },
};
