"""IO 集成层测试 — mock akshare/requests,覆盖 process_asset / process_ndx / 主流程触发判定。

不再只测纯函数,把 fetch → save → state → event 的整条路径串起来。

注:2026-05-28 信号重编号后,MA250 = signal_1(原 signal_3)。
"""

import logging
from datetime import date
from unittest.mock import patch

import pandas as pd

from core.data_io import Asset, save_history
from core.runner import process_asset, process_ndx


def _logger():
    return logging.getLogger('test-integration')


def _make_nav_df(closes: list[float], start='2024-01-01') -> pd.DataFrame:
    """生成测试用累计净值 DataFrame。日期从 start 起每日递增。"""
    dates = pd.date_range(start=start, periods=len(closes), freq='D').date
    return pd.DataFrame({'date': dates, 'close': closes})


# ===== process_asset =====

def test_process_asset_first_activation_on_signal_one(tmp_path, monkeypatch):
    """构造一只基金:close 跌破 MA250 → 首次激活信号一(新编号 MA250 = signal_1)。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)
    # 250 个 close 1.0,最后一天 0.99 → ma250 ≈ 1.0,close < ma250 → 信号一激活
    closes = [1.0] * 249 + [0.99]
    df = _make_nav_df(closes)

    asset = Asset(fund_code='999999', fund_name='测试基金')
    with patch('core.runner.fetch_fund_cumulative_nav', return_value=df):
        result = process_asset(asset, prev_asset_state={}, log=_logger())

    assert result['signals']['signal_1'] is True
    assert 'signal_1' in result['fired_first']
    assert result['fired_new_low'] == []
    assert result['signal_meta']['signal_1']['lowest_close'] == 0.99


def test_process_asset_continuing_signal_with_new_low(tmp_path, monkeypatch):
    """信号一已激活,今日 close 刷新最低 → 探底新低事件。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    closes = [1.0] * 249 + [0.98]  # 比之前 lowest 0.99 更低
    df = _make_nav_df(closes)

    prev_state = {
        'signals': {'signal_1': True, 'signal_2': False, 'signal_3': False},
        'signal_meta': {
            'signal_1': {'lowest_close': 0.99, 'activated_at': '2024-09-01'}
        },
    }
    asset = Asset(fund_code='999999', fund_name='测试基金')
    with patch('core.runner.fetch_fund_cumulative_nav', return_value=df):
        result = process_asset(asset, prev_asset_state=prev_state, log=_logger())

    assert 'signal_1' in result['fired_new_low']
    assert result['fired_first'] == []
    assert result['signal_meta']['signal_1']['lowest_close'] == 0.98
    # activated_at 应该保留旧值
    assert result['signal_meta']['signal_1']['activated_at'] == '2024-09-01'


def test_process_asset_still_active_when_no_new_low(tmp_path, monkeypatch):
    """信号一已激活,今日 close 高于 lowest → still_active 事件。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    closes = [1.0] * 249 + [0.995]  # 仍 < MA250 ≈ 1,但高于 prev lowest 0.99
    df = _make_nav_df(closes)

    prev_state = {
        'signals': {'signal_1': True, 'signal_2': False, 'signal_3': False},
        'signal_meta': {
            'signal_1': {'lowest_close': 0.99, 'activated_at': '2024-09-01'}
        },
    }
    asset = Asset(fund_code='999999', fund_name='测试基金')
    with patch('core.runner.fetch_fund_cumulative_nav', return_value=df):
        result = process_asset(asset, prev_asset_state=prev_state, log=_logger())

    assert 'signal_1' in result['fired_still_active']
    assert result['fired_first'] == []
    assert result['fired_new_low'] == []
    assert result['signal_meta']['signal_1']['lowest_close'] == 0.99


def test_process_asset_fetch_fail_records_error_and_returns_safely(tmp_path, monkeypatch):
    """fetch 抛异常 → result.errors 记录,signals 全 None,不抛。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    asset = Asset(fund_code='999999', fund_name='测试基金')
    with patch('core.runner.fetch_fund_cumulative_nav', side_effect=RuntimeError('akshare 503')):
        result = process_asset(asset, prev_asset_state={}, log=_logger())

    assert result['errors'] != []
    assert any('nav_fetch_failed' in e for e in result['errors'])
    assert result['close'] is None
    assert all(v is None for v in result['signals'].values())


def test_process_asset_deactivation_clears_signal_meta(tmp_path, monkeypatch):
    """信号原本激活,今日 close 回到 MA250 之上 → 失活,signal_meta 中 signal_1 应被清除。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    closes = [1.0] * 249 + [1.05]  # 远高于 MA250 ≈ 1
    df = _make_nav_df(closes)

    prev_state = {
        'signals': {'signal_1': True, 'signal_2': False, 'signal_3': False},
        'signal_meta': {
            'signal_1': {'lowest_close': 0.99, 'activated_at': '2024-09-01'}
        },
    }
    asset = Asset(fund_code='999999', fund_name='测试基金')
    with patch('core.runner.fetch_fund_cumulative_nav', return_value=df):
        result = process_asset(asset, prev_asset_state=prev_state, log=_logger())

    assert result['signals']['signal_1'] is False
    assert 'signal_1' not in result['signal_meta']
    assert result['fired_first'] == []
    assert result['fired_new_low'] == []
    assert result['fired_still_active'] == []


# ===== process_ndx =====

def test_process_ndx_vix_below_threshold_no_fire(tmp_path, monkeypatch):
    """VIX < 30 → signal=False, fired=False。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    ndx_df = pd.DataFrame({'date': [date(2026, 5, 26)], 'close': [29500.0]})
    with patch('core.runner.fetch_ndx', return_value=ndx_df), \
         patch('core.runner.fetch_vix_latest', return_value=17.5):
        result = process_ndx(prev_state={}, log=_logger())

    assert result['vix'] == 17.5
    assert result['signal'] is False
    assert result['fired'] is False
    assert result['errors'] == []


def test_process_ndx_vix_above_threshold_first_fire(tmp_path, monkeypatch):
    """VIX > 30 + 之前未触发 → fired=True。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    ndx_df = pd.DataFrame({'date': [date(2026, 5, 26)], 'close': [25000.0]})
    with patch('core.runner.fetch_ndx', return_value=ndx_df), \
         patch('core.runner.fetch_vix_latest', return_value=35.2):
        result = process_ndx(prev_state={'signal': False}, log=_logger())

    assert result['signal'] is True
    assert result['fired'] is True


def test_process_ndx_vix_fetch_fails_records_error(tmp_path, monkeypatch):
    """VIX None → errors 含 vix_fetch_failed,signal=None,不抛。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    ndx_df = pd.DataFrame({'date': [date(2026, 5, 26)], 'close': [29500.0]})
    with patch('core.runner.fetch_ndx', return_value=ndx_df), \
         patch('core.runner.fetch_vix_latest', return_value=None):
        result = process_ndx(prev_state={}, log=_logger())

    assert result['vix'] is None
    assert result['signal'] is None
    assert result['fired'] is False
    assert 'vix_fetch_failed' in result['errors']


def test_process_ndx_ndx_fetch_fails_but_vix_ok(tmp_path, monkeypatch):
    """NDX fetch 失败 + VIX OK → close=None 但 signal 仍能评估。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    with patch('core.runner.fetch_ndx', side_effect=RuntimeError('sina blocked')), \
         patch('core.runner.fetch_vix_latest', return_value=18.0):
        result = process_ndx(prev_state={}, log=_logger())

    assert result['close'] is None
    assert any('ndx_fetch_failed' in e for e in result['errors'])
    assert result['vix'] == 18.0
    assert result['signal'] is False


# ===== save_history =====

def test_save_history_writes_csv(tmp_path, monkeypatch):
    """save_history 写 CSV 到 ROOT/nav_history_<code>.csv。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    asset = Asset(fund_code='999999', fund_name='测试')
    df = _make_nav_df([1.0, 1.01, 0.99])
    save_history(asset, df)

    expected = tmp_path / 'nav_history_999999.csv'
    assert expected.exists()
    content = expected.read_text()
    assert 'close' in content
    assert '0.99' in content
