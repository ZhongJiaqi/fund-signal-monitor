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

  // HTTP: /trigger 手动测试 / /push 推送中转 / /probe-sctapi(-post) 诊断 / / 状态
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/push') {
      // Server 酱推送中转(2026-06-05 起):GitHub-hosted runner US 出口被 sctapi 端
      // 强制 RST,改由 GitHub Actions → 本 Worker → sctapi。CF Worker SJC colo 实测
      // 同样 US 区域但出口路径通(probe-sctapi-post HTTP 400 + JSON 业务响应)。
      // Authorization: Bearer TRIGGER_TOKEN(与 /trigger 共享)。
      // Body: JSON {title, desp}。
      // 响应:透传 sctapi 的 status + body(monitor.py 解析 code 不变)。
      if (request.method !== 'POST') {
        return new Response('Method Not Allowed', { status: 405 });
      }
      const auth = request.headers.get('Authorization') || '';
      if (auth !== `Bearer ${env.TRIGGER_TOKEN}`) {
        return new Response('Unauthorized', { status: 401 });
      }
      if (!env.SERVERCHAN_KEY) {
        return new Response('SERVERCHAN_KEY not configured on worker', { status: 500 });
      }
      let payload;
      try {
        payload = await request.json();
      } catch (e) {
        return new Response('Invalid JSON body', { status: 400 });
      }
      const title = (payload?.title || '').toString();
      const desp = (payload?.desp || '').toString();
      if (!title || !desp) {
        return new Response('Missing title or desp', { status: 400 });
      }
      const sctapiRes = await fetch(
        `https://sctapi.ftqq.com/${env.SERVERCHAN_KEY}.send`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ title, desp }).toString(),
        }
      );
      const sctapiBody = await sctapiRes.text();
      return new Response(sctapiBody, {
        status: sctapiRes.status,
        headers: {
          'Content-Type': sctapiRes.headers.get('Content-Type') || 'application/json',
        },
      });
    }

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

    if (url.pathname === '/probe-sctapi-post') {
      // 带 sendkey POST 路径探活:用故意无效的 sendkey 调真实 .send 端点。
      // Server 酱业务返回 code != 0(invalid sendkey)= HTTP+TLS+POST 链路全通,
      // 仅 sendkey 鉴权失败 → 证明 /push 中转方案的 POST 路径可行。
      // 不耗任何真实额度(无效 sendkey 不计费)。
      const auth = request.headers.get('Authorization') || '';
      if (auth !== `Bearer ${env.TRIGGER_TOKEN}`) {
        return new Response('Unauthorized', { status: 401 });
      }
      const startedAt = Date.now();
      try {
        const res = await fetch('https://sctapi.ftqq.com/SCT_INVALID_PROBE_KEY.send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ title: 'probe', desp: 'probe' }).toString(),
        });
        const body = await res.text();
        return Response.json({
          ok: true,
          httpStatus: res.status,
          body: body.slice(0, 500),
          elapsedMs: Date.now() - startedAt,
          colo: request.cf?.colo || 'unknown',
          note: 'HTTP 任何 2xx/4xx + Server 酱 JSON 业务响应 = POST 路径通;ConnectionReset/timeout = 不通',
        });
      } catch (e) {
        return Response.json({
          ok: false,
          error: e.message,
          elapsedMs: Date.now() - startedAt,
          colo: request.cf?.colo || 'unknown',
        }, { status: 502 });
      }
    }

    if (url.pathname === '/probe-sctapi') {
      // 诊断:从 Cloudflare Worker 出口能否稳定连通 sctapi.ftqq.com?
      // GitHub-hosted runner(US 出口)2026-06-05 实测被 sctapi 强制 RST 连接,
      // 若 CF 此处通,则 worker /push 路由是可行的 Server 酱推送中转方案。
      // 仅做 GET / 探活,**不发推送**,不耗 sendkey 额度。
      const auth = request.headers.get('Authorization') || '';
      const expected = `Bearer ${env.TRIGGER_TOKEN}`;
      if (auth !== expected) {
        return new Response('Unauthorized', { status: 401 });
      }
      const startedAt = Date.now();
      try {
        const res = await fetch('https://sctapi.ftqq.com/', {
          method: 'GET',
          cf: { cacheTtl: 0 },
        });
        return Response.json({
          ok: true,
          httpStatus: res.status,
          elapsedMs: Date.now() - startedAt,
          colo: request.cf?.colo || 'unknown',
          probedAt: new Date().toISOString(),
          note: 'GET / 探活;HTTP 404/200 都算通,意味着 TCP+TLS 建立 + Server 酱接受请求,只是无 sendkey 路径',
        });
      } catch (e) {
        return Response.json({
          ok: false,
          error: e.message,
          elapsedMs: Date.now() - startedAt,
          colo: request.cf?.colo || 'unknown',
          probedAt: new Date().toISOString(),
          note: 'CF 出口到 sctapi 不通 → /push 中转方案不可行,需走 Telegram/VPS/launchd 方案',
        }, { status: 502 });
      }
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
