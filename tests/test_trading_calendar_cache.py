"""交易日历本地缓存:首次拉网络,后续 7 天内读缓存。"""

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.data_io import (
    CALENDAR_CACHE_MAX_AGE_DAYS,
    load_trading_calendar_cached,
)


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    p = tmp_path / 'trading_calendar.json'
    monkeypatch.setattr('core.data_io.CALENDAR_CACHE_PATH', p)
    return p


def test_first_call_fetches_from_network(cache_path):
    """缓存不存在 → 拉网络 + 写盘。"""
    sample = {date(2026, 5, 14), date(2026, 5, 22)}
    with patch('core.data_io.load_trading_calendar', return_value=sample) as m_load:
        result = load_trading_calendar_cached()
    assert result == sample
    m_load.assert_called_once()
    assert cache_path.exists()


def test_second_call_uses_cache_within_max_age(cache_path):
    """缓存存在且新鲜 → 读盘不调网络。"""
    sample = {date(2026, 5, 14), date(2026, 5, 22)}
    # 预热缓存
    with patch('core.data_io.load_trading_calendar', return_value=sample):
        load_trading_calendar_cached()
    # 第二次调用
    with patch('core.data_io.load_trading_calendar') as m_load:
        result = load_trading_calendar_cached()
    m_load.assert_not_called()
    assert result == sample


def test_stale_cache_refetches(cache_path):
    """缓存超过 max_age → 重新拉网络。"""
    sample_old = {date(2026, 1, 1)}
    sample_new = {date(2026, 5, 14), date(2026, 5, 22)}

    # 写一个过期缓存(写入时间设为 max_age+1 天前)
    stale_ts = (datetime.now() - timedelta(days=CALENDAR_CACHE_MAX_AGE_DAYS + 1)).isoformat()
    payload = {'fetched_at': stale_ts, 'dates': [d.isoformat() for d in sample_old]}
    cache_path.write_text(json.dumps(payload), encoding='utf-8')

    with patch('core.data_io.load_trading_calendar', return_value=sample_new) as m_load:
        result = load_trading_calendar_cached()
    m_load.assert_called_once()
    assert result == sample_new


def test_corrupt_cache_refetches(cache_path):
    """缓存文件损坏(非合法 JSON)→ 重新拉网络,不崩。"""
    cache_path.write_text('not-json-{{{', encoding='utf-8')
    sample = {date(2026, 5, 14)}
    with patch('core.data_io.load_trading_calendar', return_value=sample) as m_load:
        result = load_trading_calendar_cached()
    m_load.assert_called_once()
    assert result == sample


def test_network_fails_with_cache_returns_cache(cache_path):
    """网络失败但缓存存在(即使过期)→ 用过期缓存,不抛。

    场景:akshare 挂了,我们宁可用 1 个月前的交易日历也比啥都没有强。
    """
    sample_cached = {date(2026, 5, 14), date(2026, 5, 15)}
    # 写过期缓存
    stale_ts = (datetime.now() - timedelta(days=CALENDAR_CACHE_MAX_AGE_DAYS + 5)).isoformat()
    payload = {'fetched_at': stale_ts, 'dates': [d.isoformat() for d in sample_cached]}
    cache_path.write_text(json.dumps(payload), encoding='utf-8')

    with patch('core.data_io.load_trading_calendar', side_effect=RuntimeError('akshare down')):
        result = load_trading_calendar_cached()
    assert result == sample_cached  # 降级用过期缓存


def test_network_fails_no_cache_raises(cache_path):
    """网络失败且无缓存 → 抛异常(调用方决定怎么办)。"""
    with patch('core.data_io.load_trading_calendar', side_effect=RuntimeError('akshare down')):
        with pytest.raises(RuntimeError, match='akshare down'):
            load_trading_calendar_cached()
