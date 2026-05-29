"""fetch_vix_latest 双数据源:Yahoo 主 + CBOE 备份。"""

from unittest.mock import MagicMock, patch

from core.data_io import fetch_vix_latest


def _yahoo_ok(value: float) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        'chart': {
            'result': [{'indicators': {'quote': [{'close': [None, None, value]}]}}],
        },
    }
    return r


def _cboe_ok(value: float) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {'data': {'current_price': value, 'close': value}}
    return r


def _fail_response(status: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    return r


def test_yahoo_primary_returns_value():
    """Yahoo 首次成功 → 不调 CBOE。"""
    with patch('core.data_io.requests.get') as m_get:
        m_get.return_value = _yahoo_ok(17.5)
        result = fetch_vix_latest()
    assert result == 17.5
    # 只调一次:Yahoo
    assert m_get.call_count == 1
    assert 'yahoo' in m_get.call_args.args[0].lower() or 'yahoo' in str(m_get.call_args)


def test_yahoo_fails_cboe_succeeds():
    """Yahoo 全部失败 → 调 CBOE 备份 → 返回备份值。"""
    def side(url, **kw):
        if 'yahoo' in url:
            return _fail_response(503)
        if 'cboe' in url:
            return _cboe_ok(18.2)
        return _fail_response(500)

    # 关键:retry 时 base_delay=0 不 sleep,但函数内部用 FETCH_BASE_DELAY=2,需 mock time.sleep
    with patch('core.data_io.requests.get', side_effect=side), \
         patch('core.data_io.time.sleep') as m_sleep:
        result = fetch_vix_latest()
    assert result == 18.2
    # Yahoo retry 3 次 + CBOE 至少 1 次
    assert m_sleep.called  # 证明走了 retry


def test_both_sources_fail_returns_none():
    """Yahoo + CBOE 都失败 → None,不抛。"""
    with patch('core.data_io.requests.get', return_value=_fail_response(503)), \
         patch('core.data_io.time.sleep'):
        result = fetch_vix_latest()
    assert result is None


def test_network_exception_fallback_to_cboe():
    """Yahoo 抛网络异常也走 CBOE 备份。"""
    def side(url, **kw):
        if 'yahoo' in url:
            raise ConnectionError('yahoo blocked')
        if 'cboe' in url:
            return _cboe_ok(15.7)
        return _fail_response(500)

    with patch('core.data_io.requests.get', side_effect=side), \
         patch('core.data_io.time.sleep'):
        result = fetch_vix_latest()
    assert result == 15.7
