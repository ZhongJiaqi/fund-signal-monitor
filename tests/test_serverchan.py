"""send_serverchan 行为:43001/40001 额度耗尽时额外弹原生通知。"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from monitor import send_serverchan, SERVERCHAN_QUOTA_CODES


def _logger():
    return logging.getLogger('test')


def _mock_response(code: int) -> MagicMock:
    r = MagicMock()
    r.headers = {'content-type': 'application/json'}
    r.json.return_value = {'code': code, 'message': 'mock'}
    r.text = f'{{"code": {code}}}'
    return r


def test_no_sendkey_is_noop():
    """无 key 时直接返回,不调用 requests。"""
    with patch('core.notify.requests.post') as m_post:
        send_serverchan('', 'title', 'desp', _logger())
        m_post.assert_not_called()


def test_invalid_sendkey_prefix_is_noop():
    """key 不以 SCT 开头视为无效,不发。"""
    with patch('core.notify.requests.post') as m_post:
        send_serverchan('NOT_SCT_KEY', 't', 'd', _logger())
        m_post.assert_not_called()


def test_success_no_native_notification():
    """code=0 成功 → 不弹 macOS 通知。"""
    with patch('core.notify.requests.post', return_value=_mock_response(0)) as m_post, \
         patch('core.notify.send_macos_notification') as m_notify:
        send_serverchan('SCTabc123', 'title', 'desp', _logger())
        m_post.assert_called_once()
        m_notify.assert_not_called()


@pytest.mark.parametrize('code', list(SERVERCHAN_QUOTA_CODES))
def test_quota_exhausted_triggers_native_notification(code):
    """43001 / 40001 等额度类错误 → 额外弹 macOS 通知警示用户。"""
    with patch('core.notify.requests.post', return_value=_mock_response(code)) as m_post, \
         patch('core.notify.send_macos_notification') as m_notify:
        send_serverchan('SCTabc123', 'title', 'desp', _logger())
        m_post.assert_called_once()
        m_notify.assert_called_once()
        # 校验通知内容含"额度"或具体 code
        args, kwargs = m_notify.call_args
        title_arg = kwargs.get('title') or (args[0] if args else '')
        assert '额度' in title_arg or 'Server 酱' in title_arg


def test_non_quota_error_no_native_notification():
    """其他非 0 错误(如 -1)只 log warning,不弹通知。"""
    with patch('core.notify.requests.post', return_value=_mock_response(-1)), \
         patch('core.notify.send_macos_notification') as m_notify:
        send_serverchan('SCTabc123', 'title', 'desp', _logger())
        m_notify.assert_not_called()


def test_network_exception_no_native_notification():
    """网络异常不算额度问题,不弹通知,但记 log。"""
    with patch('core.notify.requests.post', side_effect=RuntimeError('conn refused')), \
         patch('core.notify.send_macos_notification') as m_notify:
        send_serverchan('SCTabc123', 'title', 'desp', _logger())
        m_notify.assert_not_called()
