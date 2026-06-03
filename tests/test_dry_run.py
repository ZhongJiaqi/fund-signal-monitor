"""dry-run 模式测试 — 验证 `main(dry_run=True)` 完全阻断 5 类副作用。

被阻断:Server 酱推送 / macOS 通知 / save_state / latest_alert_*.md 写文件 / latest_alert_errors.md
被保留:取数、history CSV、trading_calendar、run.log(都是缓存或可观测,不影响下次跑)
"""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.data_io import ASSETS, SHORTMA_ASSETS
from core.runner import main


def _make_df(closes: list[float], start='2024-01-01', freq='D') -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(closes), freq=freq).date
    return pd.DataFrame({'date': dates, 'close': closes})


@pytest.fixture
def dry_run_env(tmp_path, monkeypatch):
    """构造可控环境:今天是交易日 + 第 1 只 dividend / 第 1 只 shortma 触发首次激活 + 其他安全 + VIX 低。

    所有有副作用的函数都换成 MagicMock,主测试通过 .call_count 断言"未被调用"。
    """
    monkeypatch.setattr('core.data_io.ROOT', tmp_path)
    monkeypatch.setattr('core.runner.ROOT', tmp_path)

    today = date(2026, 6, 1)

    div_fire = _make_df([1.0] * 249 + [0.95])       # close 0.95 < MA250 ≈ 1.0 → 信号一触发
    div_safe = _make_df([1.0] * 249 + [1.10])       # close 1.10 > MA250 → 安全
    ma20_fire = _make_df([2.0] * 19 + [1.85])       # close 1.85 < MA20 → 触发
    ma20_safe = _make_df([2.0] * 19 + [2.20])       # close 2.20 > MA20 → 安全
    ndx_df = pd.DataFrame({'date': [today], 'close': [21000.0]})

    def fake_div(code):
        return div_fire if code == ASSETS[0].fund_code else div_safe

    def fake_unit(code):
        return ma20_fire if code == SHORTMA_ASSETS[0].fund_code else ma20_safe

    serverchan_mock = MagicMock()
    macos_mock = MagicMock()
    save_state_mock = MagicMock()

    monkeypatch.setattr('core.runner.fetch_fund_cumulative_nav', fake_div)
    monkeypatch.setattr('core.runner.fetch_fund_unit_nav', fake_unit)
    monkeypatch.setattr('core.runner.fetch_ndx', lambda: ndx_df)
    monkeypatch.setattr('core.runner.fetch_vix_latest', lambda: 17.0)
    monkeypatch.setattr('core.runner.load_trading_calendar_cached', lambda: {today})
    monkeypatch.setattr('core.runner.setup_proxy_env', lambda: None)
    monkeypatch.setattr('core.runner.load_env', lambda: {'SERVERCHAN_SENDKEY': 'SCTtest12345'})
    monkeypatch.setattr('core.runner.send_serverchan', serverchan_mock)
    monkeypatch.setattr('core.runner.send_macos_notification', macos_mock)
    monkeypatch.setattr('core.runner.save_state', save_state_mock)
    # load_state 返回空,让事件分类全走"首次激活"路径
    monkeypatch.setattr('core.runner.load_state', lambda: {
        'assets': {}, 'shortma_assets': {}, 'ndx': {}
    })
    # SIGALRM 在测试环境会被多次 set/clear,跳过即可
    import signal as _signal
    monkeypatch.setattr(_signal, 'alarm', lambda *_a, **_k: None)
    monkeypatch.setattr(_signal, 'signal', lambda *_a, **_k: None)

    return {
        'today': today,
        'tmp_path': tmp_path,
        'serverchan': serverchan_mock,
        'macos': macos_mock,
        'save_state': save_state_mock,
    }


def test_dry_run_does_not_call_serverchan(dry_run_env):
    main(today=dry_run_env['today'], dry_run=True)
    assert dry_run_env['serverchan'].call_count == 0, (
        "dry-run 必须完全阻断 Server 酱推送 — 否则会耗 5/天 免费额度"
    )


def test_dry_run_does_not_call_macos_notification(dry_run_env):
    main(today=dry_run_env['today'], dry_run=True)
    assert dry_run_env['macos'].call_count == 0, (
        "dry-run 不应弹 macOS 通知打扰用户"
    )


def test_dry_run_does_not_call_save_state(dry_run_env):
    main(today=dry_run_env['today'], dry_run=True)
    assert dry_run_env['save_state'].call_count == 0, (
        "dry-run 写 state.json 会污染下次跑的事件分类(尤其 first/new_low 判断)"
    )


def test_dry_run_does_not_write_latest_alert_files(dry_run_env):
    main(today=dry_run_env['today'], dry_run=True)
    tmp = dry_run_env['tmp_path']
    assert not (tmp / 'latest_alert_dividend.md').exists(), "dry-run 不应覆盖上次真实推送的快照"
    assert not (tmp / 'latest_alert_shortma.md').exists()
    assert not (tmp / 'latest_alert_ndx.md').exists()
    assert not (tmp / 'latest_alert_errors.md').exists()


def test_dry_run_prints_marker_to_stdout(dry_run_env, capsys):
    """stdout 必须包含 [DRY-RUN] 标记,用户一眼能看出这不是真实推送日志。"""
    main(today=dry_run_env['today'], dry_run=True)
    captured = capsys.readouterr()
    assert '[DRY-RUN]' in captured.out


def test_dry_run_stdout_shows_fired_channels_with_title_and_md(dry_run_env, capsys):
    """会推的通道必须在 stdout 显示标题 + 完整 markdown,无触发的通道显示"不会推"。"""
    main(today=dry_run_env['today'], dry_run=True)
    captured = capsys.readouterr()
    assert '红利低波' in captured.out
    assert '科技' in captured.out
    # NDX 通道 VIX < 30 不应"会推"
    out = captured.out
    assert '纳指' in out
    # 红利和科技应出现"会推"标记;纳指应是"不会推"
    assert '会推' in out
    assert '不会推' in out


def test_production_path_unchanged_when_dry_run_false(dry_run_env):
    """回归保护:dry_run=False(默认)时,推送/state/文件写入 全部按现行生产路径执行。"""
    main(today=dry_run_env['today'], dry_run=False)
    # 1 只 div 触发 + 1 只 shortma 触发 → 应至少 2 次 send_serverchan(纳指 VIX 低 不算)
    assert dry_run_env['serverchan'].call_count == 2
    assert dry_run_env['macos'].call_count == 2
    assert dry_run_env['save_state'].call_count == 1
    tmp = dry_run_env['tmp_path']
    assert (tmp / 'latest_alert_dividend.md').exists()
    assert (tmp / 'latest_alert_shortma.md').exists()
