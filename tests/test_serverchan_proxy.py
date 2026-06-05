"""send_serverchan 代理模式测试。

场景:GitHub Actions runner(US 出口)被 sctapi.ftqq.com 强制 RST(2026-06-05 实测),
CF Worker(SJC colo)出口能稳定连通。改 send_serverchan 在配 SERVERCHAN_PROXY_URL +
SERVERCHAN_PROXY_TOKEN 环境变量时,POST 到 CF Worker /push 端点中转。

Worker 透传 sctapi JSON 响应,monitor.py 的额度耗尽(40001/43001)判断逻辑不变。
"""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from core.notify import send_serverchan, SERVERCHAN_QUOTA_CODES


def _logger():
    return logging.getLogger('test')


def _resp(code: int, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.headers = {'content-type': 'application/json'}
    r.json.return_value = {'code': code, 'message': 'mock'}
    r.text = f'{{"code": {code}}}'
    return r


def test_no_proxy_env_posts_to_sctapi_directly(monkeypatch):
    """无 SERVERCHAN_PROXY_URL → 走直连 sctapi(回归保护原有行为)。"""
    monkeypatch.delenv('SERVERCHAN_PROXY_URL', raising=False)
    monkeypatch.delenv('SERVERCHAN_PROXY_TOKEN', raising=False)
    with patch('core.notify.requests.post', return_value=_resp(0)) as m_post:
        send_serverchan('SCTabc123', 'title', 'desp', _logger())
        m_post.assert_called_once()
        called_url = m_post.call_args[0][0]
        assert 'sctapi.ftqq.com' in called_url, '无 proxy 配置应走直连 sctapi'
        assert 'SCTabc123' in called_url, '直连模式 URL 含 sendkey'


def test_proxy_env_posts_to_worker_endpoint(monkeypatch):
    """有 SERVERCHAN_PROXY_URL + TOKEN → 走 Worker /push,不直连 sctapi。"""
    proxy_url = 'https://fund-monitor-cron.zhongjiaqi.workers.dev/push'
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', proxy_url)
    monkeypatch.setenv('SERVERCHAN_PROXY_TOKEN', 'tok_test_64hex')
    with patch('core.notify.requests.post', return_value=_resp(0)) as m_post:
        send_serverchan('SCTabc123', '红利低波 · 2026-06-05', '正文 markdown', _logger())
        m_post.assert_called_once()
        called_url = m_post.call_args[0][0]
        assert called_url == proxy_url, '配 proxy 后必须 POST 到 Worker /push,不能直连 sctapi'
        assert 'sctapi.ftqq.com' not in called_url


def test_proxy_mode_sends_bearer_token_in_header(monkeypatch):
    """Worker /push 用 Bearer 鉴权,monitor.py 必须正确组装 Authorization header。"""
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', 'https://w/push')
    monkeypatch.setenv('SERVERCHAN_PROXY_TOKEN', 'tok_xyz')
    with patch('core.notify.requests.post', return_value=_resp(0)) as m_post:
        send_serverchan('SCTabc123', 't', 'd', _logger())
        kwargs = m_post.call_args.kwargs
        headers = kwargs.get('headers', {})
        assert headers.get('Authorization') == 'Bearer tok_xyz'


def test_proxy_mode_sends_title_and_desp_in_json(monkeypatch):
    """Worker 期望 JSON body {title, desp},而非 form。"""
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', 'https://w/push')
    monkeypatch.setenv('SERVERCHAN_PROXY_TOKEN', 'tok')
    with patch('core.notify.requests.post', return_value=_resp(0)) as m_post:
        send_serverchan('SCTabc123', 'my-title', 'my-desp-md', _logger())
        kwargs = m_post.call_args.kwargs
        # 接受 json= 参数(requests 自动序列化) 或 data= + 正确 Content-Type
        if 'json' in kwargs:
            payload = kwargs['json']
        else:
            import json
            payload = json.loads(kwargs.get('data') or '{}')
        assert payload.get('title') == 'my-title'
        assert payload.get('desp') == 'my-desp-md'


def test_proxy_mode_title_still_truncated_to_32(monkeypatch):
    """Server 酱 title 32 字符上限的截断仍在 monitor.py 侧做(Worker 不重复实现)。"""
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', 'https://w/push')
    monkeypatch.setenv('SERVERCHAN_PROXY_TOKEN', 'tok')
    long_title = '红' * 50
    with patch('core.notify.requests.post', return_value=_resp(0)) as m_post:
        send_serverchan('SCTabc123', long_title, 'd', _logger())
        kwargs = m_post.call_args.kwargs
        payload = kwargs.get('json') or {}
        assert len(payload['title']) == 32, 'title 必须截断到 32 字符,与直连模式一致'


def test_proxy_mode_passes_through_quota_code(monkeypatch):
    """Worker 透传 sctapi 响应,40001/43001 仍触发 macOS 通知(额度告警机制不能丢)。"""
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', 'https://w/push')
    monkeypatch.setenv('SERVERCHAN_PROXY_TOKEN', 'tok')
    with patch('core.notify.requests.post', return_value=_resp(43001)), \
         patch('core.notify.send_macos_notification') as m_notify:
        send_serverchan('SCTabc123', 't', 'd', _logger())
        m_notify.assert_called_once(), '代理模式下额度告警同样应触发'


def test_proxy_mode_empty_sendkey_still_noop(monkeypatch):
    """sendkey 校验仍生效 —— 无 sendkey 时即使配了 proxy 也不发(防误配)。"""
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', 'https://w/push')
    monkeypatch.setenv('SERVERCHAN_PROXY_TOKEN', 'tok')
    with patch('core.notify.requests.post') as m_post:
        send_serverchan('', 't', 'd', _logger())
        m_post.assert_not_called()


def test_proxy_mode_missing_token_falls_back_to_direct(monkeypatch):
    """配了 URL 但 TOKEN 缺失 = 配置不完整 → 降级直连(避免裸 POST 给 Worker 被 401)。"""
    monkeypatch.setenv('SERVERCHAN_PROXY_URL', 'https://w/push')
    monkeypatch.delenv('SERVERCHAN_PROXY_TOKEN', raising=False)
    with patch('core.notify.requests.post', return_value=_resp(0)) as m_post:
        send_serverchan('SCTabc123', 't', 'd', _logger())
        kwargs = m_post.call_args.kwargs
        url = m_post.call_args[0][0]
        assert 'sctapi.ftqq.com' in url, '配置不完整应降级直连,不应 POST 裸到 worker'
