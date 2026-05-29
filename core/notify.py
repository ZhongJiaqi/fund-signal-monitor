"""推送通道:macOS 原生通知 + Server 酱微信。"""

from __future__ import annotations

import logging
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
    """
    if not sendkey or not sendkey.startswith('SCT'):
        return
    try:
        r = requests.post(
            f'https://sctapi.ftqq.com/{sendkey}.send',
            data={'title': title[:32], 'desp': desp},  # title 上限 32 字
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
