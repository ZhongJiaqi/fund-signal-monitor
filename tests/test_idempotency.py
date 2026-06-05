"""幂等性测试 — 验证 `main()` 在同日多次调用时只真发一次。

场景:Cloudflare Workers cron 配置多个时间点 (`0 2`,`5 2`,`10 2` UTC) 兜底单点漏跑。
任一触发即推一次,后续触发因 state.last_run.date() == today 而 fast exit,不再推送。

约束:
- dry_run=True 不受幂等限制(预览模式跑多少次都不写 state,不污染)
- force=True 时跳过幂等检查(手动重跑 escape hatch)
"""

from datetime import date, datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.data_io import ASSETS, SHORTMA_ASSETS
from core.runner import main


def _df(closes: list[float], start='2024-01-01') -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(closes), freq='D').date
    return pd.DataFrame({'date': dates, 'close': closes})


@pytest.fixture
def env(tmp_path, monkeypatch):
    """与 test_dry_run 的 fixture 等价,但 load_state 可由各测试覆盖。"""
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)

    today = date(2026, 6, 5)

    div_fire = _df([1.0] * 249 + [0.95])
    div_safe = _df([1.0] * 249 + [1.10])
    ma20_fire = _df([2.0] * 19 + [1.85])
    ma20_safe = _df([2.0] * 19 + [2.20])
    ndx_df = pd.DataFrame({'date': [today], 'close': [21000.0]})

    serverchan_mock = MagicMock()
    macos_mock = MagicMock()
    save_state_mock = MagicMock()

    monkeypatch.setattr('core.runner.fetch_fund_cumulative_nav',
                        lambda code: div_fire if code == ASSETS[0].fund_code else div_safe)
    monkeypatch.setattr('core.runner.fetch_fund_unit_nav',
                        lambda code: ma20_fire if code == SHORTMA_ASSETS[0].fund_code else ma20_safe)
    monkeypatch.setattr('core.runner.fetch_ndx', lambda: ndx_df)
    monkeypatch.setattr('core.runner.fetch_vix_latest', lambda: 17.0)
    monkeypatch.setattr('core.runner.load_trading_calendar_cached', lambda: {today})
    monkeypatch.setattr('core.runner.setup_proxy_env', lambda: None)
    monkeypatch.setattr('core.runner.load_env', lambda: {'SERVERCHAN_SENDKEY': 'SCTtest12345'})
    monkeypatch.setattr('core.runner.send_serverchan', serverchan_mock)
    monkeypatch.setattr('core.runner.send_macos_notification', macos_mock)
    monkeypatch.setattr('core.runner.save_state', save_state_mock)

    import signal as _signal
    monkeypatch.setattr(_signal, 'alarm', lambda *_a, **_k: None)
    monkeypatch.setattr(_signal, 'signal', lambda *_a, **_k: None)

    return {
        'today': today,
        'tmp_path': tmp_path,
        'serverchan': serverchan_mock,
        'macos': macos_mock,
        'save_state': save_state_mock,
        'monkeypatch': monkeypatch,
    }


def _set_state(monkeypatch, last_run_iso: str | None):
    """覆盖 load_state 返回带指定 last_run 的 state。None 表示无 last_run 字段。"""
    state = {'assets': {}, 'shortma_assets': {}, 'shortma_overseas_assets': {}, 'ndx': {}}
    if last_run_iso is not None:
        state['last_run'] = last_run_iso
    monkeypatch.setattr('core.runner.load_state', lambda: state)


def test_idempotency_skips_push_when_already_run_today(env):
    """state.last_run 是今天 → 跳过推送 + save_state 不调用 + return 0。"""
    _set_state(env['monkeypatch'], f"{env['today'].isoformat()}T10:00:00")
    rc = main(today=env['today'], dry_run=False)
    assert rc == 0
    assert env['serverchan'].call_count == 0, '同日重复跑必须不推 Server 酱'
    assert env['macos'].call_count == 0, '同日重复跑不应弹 macOS 通知'
    assert env['save_state'].call_count == 0, '同日重复跑不应写 state(避免 last_run 时间不必要刷新)'


def test_idempotency_normal_run_when_last_run_is_yesterday(env):
    """state.last_run 是昨天 → 正常跑全部 3 通道推送(1+1+1)。"""
    yesterday = date(2026, 6, 4)
    _set_state(env['monkeypatch'], f"{yesterday.isoformat()}T10:00:00")
    rc = main(today=env['today'], dry_run=False)
    assert rc == 0
    assert env['serverchan'].call_count == 3, '跨日应正常推送(红利 1 + 国内 1 + 海外 1)'
    assert env['save_state'].call_count == 1


def test_idempotency_normal_run_when_no_last_run(env):
    """state 无 last_run 字段(全新部署/cache miss)→ 正常跑。"""
    _set_state(env['monkeypatch'], last_run_iso=None)
    rc = main(today=env['today'], dry_run=False)
    assert rc == 0
    assert env['serverchan'].call_count == 3


def test_idempotency_normal_run_when_last_run_malformed(env):
    """state.last_run 是无效字符串(数据腐败防御)→ 视为无 last_run,正常跑。"""
    _set_state(env['monkeypatch'], 'not-a-date')
    rc = main(today=env['today'], dry_run=False)
    assert rc == 0
    assert env['serverchan'].call_count == 3


def test_idempotency_does_not_block_dry_run(env):
    """dry-run 不受幂等限制 — 预览不写 state 不污染,可任意跑。"""
    _set_state(env['monkeypatch'], f"{env['today'].isoformat()}T10:00:00")
    rc = main(today=env['today'], dry_run=True)
    assert rc == 0
    # dry-run 的 serverchan/save_state 本来就 0,但 dry-run stdout 必须有预览内容
    assert env['serverchan'].call_count == 0
    assert env['save_state'].call_count == 0


def test_force_flag_bypasses_idempotency(env):
    """force=True 即使今日已跑过仍照常推送 + 写 state(手动重跑 escape hatch)。"""
    _set_state(env['monkeypatch'], f"{env['today'].isoformat()}T10:00:00")
    rc = main(today=env['today'], dry_run=False, force=True)
    assert rc == 0
    assert env['serverchan'].call_count == 3, 'force 必须绕过幂等'
    assert env['save_state'].call_count == 1
