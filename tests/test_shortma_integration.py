"""短线 MA20 process_shortma_asset 集成测试 — mock 单位净值取数,覆盖事件分类。"""

import logging
from datetime import date
from unittest.mock import patch

import pandas as pd

from core.data_io import Asset
from core.runner import process_shortma_asset


def _logger():
    return logging.getLogger('test-shortma')


def _make_unit_df(closes: list[float], start='2026-01-02') -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(closes), freq='B').date
    return pd.DataFrame({'date': dates, 'close': closes})


def test_first_activation_when_close_below_ma20(tmp_path, monkeypatch):
    """close < MA20 + 之前未激活 → first 事件。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    # 20 个单位净值 1.0,最后一天 0.95 → ma20 = ~0.9975,close < ma20 → 激活
    closes = [1.0] * 19 + [0.95]
    df = _make_unit_df(closes)

    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', return_value=df):
        result = process_shortma_asset(asset, prev_asset_state={}, log=_logger())

    assert result['signal'] is True
    assert result['fired_first'] is True
    assert result['fired_new_low'] is False
    assert result['fired_still_active'] is False
    assert result['signal_meta']['lowest_close'] == 0.95


def test_new_low_when_already_active_and_dips_lower(tmp_path, monkeypatch):
    """已激活 + 今日 close 刷新 lowest → new_low。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    closes = [1.0] * 19 + [0.92]
    df = _make_unit_df(closes)

    prev = {'signal': True, 'signal_meta': {'lowest_close': 0.95, 'activated_at': '2026-05-20'}}
    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', return_value=df):
        result = process_shortma_asset(asset, prev_asset_state=prev, log=_logger())

    assert result['fired_new_low'] is True
    assert result['fired_first'] is False
    assert result['signal_meta']['lowest_close'] == 0.92
    assert result['signal_meta']['activated_at'] == '2026-05-20'  # 保留旧值


def test_still_active_when_no_new_low(tmp_path, monkeypatch):
    """已激活 + 今日 close > 历史 lowest → still_active。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    closes = [1.0] * 19 + [0.96]
    df = _make_unit_df(closes)

    prev = {'signal': True, 'signal_meta': {'lowest_close': 0.93, 'activated_at': '2026-05-20'}}
    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', return_value=df):
        result = process_shortma_asset(asset, prev_asset_state=prev, log=_logger())

    assert result['fired_still_active'] is True
    assert result['signal_meta']['lowest_close'] == 0.93  # 不刷新


def test_deactivation_clears_signal_meta(tmp_path, monkeypatch):
    """close 回到 MA20 之上 → 信号失活,signal_meta 清空。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    closes = [1.0] * 19 + [1.05]  # 远高于 MA20
    df = _make_unit_df(closes)

    prev = {'signal': True, 'signal_meta': {'lowest_close': 0.93, 'activated_at': '2026-05-20'}}
    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', return_value=df):
        result = process_shortma_asset(asset, prev_asset_state=prev, log=_logger())

    assert result['signal'] is False
    assert result['signal_meta'] == {}
    assert result['fired_first'] is False
    assert result['fired_new_low'] is False
    assert result['fired_still_active'] is False


def test_fetch_failure_records_error_safely(tmp_path, monkeypatch):
    """fetch 抛异常 → errors 含 unit_nav_fetch_failed,close/ma20 都 None,不抛。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', side_effect=RuntimeError('akshare 503')):
        result = process_shortma_asset(asset, prev_asset_state={}, log=_logger())

    assert any('unit_nav_fetch_failed' in e for e in result['errors'])
    assert result['close'] is None
    assert result['ma20'] is None
    assert result['signal'] is None


def test_new_fund_with_less_than_20_history_ma20_none(tmp_path, monkeypatch):
    """新基金历史 <20 个交易日 → MA20 算不出,signal=None,不误推。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    closes = [1.0] * 15  # 只有 15 条
    df = _make_unit_df(closes)

    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', return_value=df):
        result = process_shortma_asset(asset, prev_asset_state={}, log=_logger())

    assert result['ma20'] is None
    assert result['signal'] is None
    assert result['fired_first'] is False


def test_unit_history_csv_written(tmp_path, monkeypatch):
    """fetch 成功后 nav_history_<code>_unit.csv 应被写入(与累计净值的 nav_history_<code>.csv 区分)。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    closes = [1.0] * 19 + [0.95]
    df = _make_unit_df(closes)

    asset = Asset(fund_code='159915', fund_name='创业板')
    with patch('core.runner.fetch_fund_unit_nav', return_value=df):
        process_shortma_asset(asset, prev_asset_state={}, log=_logger())

    expected = tmp_path / 'nav_history_159915_unit.csv'
    assert expected.exists()
    content = expected.read_text()
    assert '0.95' in content
