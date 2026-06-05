"""推送通道:macOS 原生通知 + Server 酱微信。"""

from __future__ import annotations

import logging
import os
import subprocess

import requests


# Server 酱已知的"额度耗尽 / 频控"错误码,触发额外原生通知警示用户
SERVERCHAN_QUOTA_CODES = frozenset({40001, 43001})


def send_macos_notification(title: str, message: str) -> None:
    """通过 osascript 弹 macOS 通知。失败静默,不影响主流程。"""
    try:
        t = title.replace('"', "'")
        m = message.replace('"', "'")
        subprocess.run(
            ['osascript', '-e', f'display notification "{m}" with title "{t}"'],
            check=False, timeout=5,
        )
    except Exception:
        pass


def send_serverchan(sendkey: str, title: str, desp: str, log: logging.Logger) -> None:
    """Server 酱推送到微信。无 key/失败 时静默(并打 warning 日志)。

    遇到 SERVERCHAN_QUOTA_CODES 中的错误码,额外弹 macOS 通知警示用户 —
    否则用户只在 run.log 里看到 warning,launchd.err.log 看不到。

    代理模式:配 SERVERCHAN_PROXY_URL + SERVERCHAN_PROXY_TOKEN 时,POST 到
    Cloudflare Worker /push 端点中转(Worker 内调 sctapi)。用于 GitHub
    Actions runner(US 出口被 sctapi 端 RST)等场景。配置不完整时降级直连。
    Worker 响应透传 sctapi JSON,本函数解析逻辑(code 解释)不变。
    """
    if not sendkey or not sendkey.startswith('SCT'):
        return
    proxy_url = os.environ.get('SERVERCHAN_PROXY_URL', '').strip()
    proxy_token = os.environ.get('SERVERCHAN_PROXY_TOKEN', '').strip()
    title_trim = title[:32]  # Server 酱 title 上限 32 字
    try:
        if proxy_url and proxy_token:
            r = requests.post(
                proxy_url,
                json={'title': title_trim, 'desp': desp},
                headers={'Authorization': f'Bearer {proxy_token}'},
                timeout=15,
            )
        else:
            r = requests.post(
                f'https://sctapi.ftqq.com/{sendkey}.send',
                data={'title': title_trim, 'desp': desp},
                timeout=8,
            )
        body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
        code = body.get('code', body.get('data', {}).get('errno', 0))
        if code not in (0, None):
            log.warning(f'Server 酱推送返回非 0: {r.text[:200]}')
            if code in SERVERCHAN_QUOTA_CODES:
                send_macos_notification(
                    title=f'⚠ Server 酱额度耗尽 (code {code})',
                    message=f'今日推送可能失败,本应推:{title[:40]}',
                )
    except Exception as e:
        log.warning(f'Server 酱推送失败: {e}')
