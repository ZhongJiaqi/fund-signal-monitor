"""TDD: 三个价格类信号 + 首次触发对比(2026-05-28 重编号 + 严格 <)。

信号定义(1 份 = 1 个加仓单位;独立同时触发可能):
- 信号一(MA250):净值 < MA250 → 1 份(最浅档)
- 信号二(常规):净值 < MA120 × (1 - 6%) → 1 份
- 信号三(加倍):净值 < MA120 × (1 - 12%) → 2 份

全部用严格小于 <。数据缺失:相关输入为 None 时,信号置 None。
"""

from monitor import evaluate_signals, first_triggered


# ============ 信号一 / 二 / 三:价格类 ============

def test_signal_one_triggers_when_close_below_ma250():
    s = evaluate_signals(close=99.9, ma120=100.0, ma250=100.0)
    assert s['signal_1'] is True


def test_signal_one_not_triggered_at_exactly_ma250():
    """严格 <,close == ma250 不触发。"""
    s = evaluate_signals(close=100.0, ma120=100.0, ma250=100.0)
    assert s['signal_1'] is False


def test_signal_one_not_triggered_above_ma250():
    s = evaluate_signals(close=100.5, ma120=100.0, ma250=100.0)
    assert s['signal_1'] is False


def test_signal_two_triggers_when_close_drops_6pct_below_ma120():
    """close=93.9 是 6.1% 跌幅,达到信号二阈值。"""
    s = evaluate_signals(close=93.9, ma120=100.0, ma250=100.0)
    assert s['signal_2'] is True


def test_signal_two_not_triggered_at_exactly_threshold():
    """严格 <,close = ma120 × 0.94 正好等于阈值 → 不触发。"""
    s = evaluate_signals(close=94.0, ma120=100.0, ma250=100.0)
    assert s['signal_2'] is False


def test_signal_two_not_triggered_just_above_threshold():
    """close=94.001 比阈值高,未触发。"""
    s = evaluate_signals(close=94.001, ma120=100.0, ma250=100.0)
    assert s['signal_2'] is False


def test_signal_three_triggers_when_close_drops_12pct_below_ma120():
    """close=87.9 是 12.1% 跌幅,信号二 + 信号三同时激活。"""
    s = evaluate_signals(close=87.9, ma120=100.0, ma250=100.0)
    assert s['signal_2'] is True   # 12% 一定也满足 6%
    assert s['signal_3'] is True


def test_signal_three_not_triggered_at_exactly_threshold():
    """严格 <,close = ma120 × 0.88 不触发。"""
    s = evaluate_signals(close=88.0, ma120=100.0, ma250=100.0)
    assert s['signal_3'] is False


def test_price_signals_none_when_ma120_missing():
    """MA120 缺失:信号二/三 None,信号一不受影响。"""
    s = evaluate_signals(close=94.0, ma120=None, ma250=100.0)
    assert s['signal_1'] is True
    assert s['signal_2'] is None
    assert s['signal_3'] is None


def test_signal_one_none_when_ma250_missing():
    """MA250 缺失 → 信号一 None,信号二/三不受影响。"""
    s = evaluate_signals(close=94.0, ma120=100.0, ma250=None)
    assert s['signal_1'] is None
    assert s['signal_2'] is False   # 94.0 = 阈值,严格 < 不触发
    assert s['signal_3'] is False


def test_all_signals_none_when_close_missing():
    s = evaluate_signals(close=None, ma120=100.0, ma250=100.0)
    assert s['signal_1'] is None
    assert s['signal_2'] is None
    assert s['signal_3'] is None


# ============ 首次触发对比 ============

def test_first_triggered_when_prev_false_and_today_true():
    assert first_triggered(prev=False, today=True) is True


def test_not_first_triggered_when_already_active():
    assert first_triggered(prev=True, today=True) is False


def test_first_triggered_when_prev_unknown_and_today_true():
    assert first_triggered(prev=None, today=True) is True


def test_not_first_triggered_when_today_inactive():
    assert first_triggered(prev=False, today=False) is False
    assert first_triggered(prev=True, today=False) is False


def test_not_first_triggered_when_today_unknown():
    assert first_triggered(prev=False, today=None) is False
    assert first_triggered(prev=True, today=None) is False
