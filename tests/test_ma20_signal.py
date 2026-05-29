"""MA20 短线信号判断 — 单位净值 < MA20 → 激活。"""

from monitor import evaluate_ma20_signal


def test_close_below_ma20_activates():
    """close < MA20 → True 激活。"""
    assert evaluate_ma20_signal(close=1.85, ma20=1.90) is True


def test_close_equal_ma20_not_activated():
    """close == MA20 → False(严格小于才算激活,与信号三逻辑一致)。"""
    assert evaluate_ma20_signal(close=1.90, ma20=1.90) is False


def test_close_above_ma20_not_activated():
    """close > MA20 → False。"""
    assert evaluate_ma20_signal(close=1.95, ma20=1.90) is False


def test_close_none_returns_none():
    """close 未取到 → None(永不触发提醒)。"""
    assert evaluate_ma20_signal(close=None, ma20=1.90) is None


def test_ma20_none_returns_none():
    """MA20 数据不足(基金成立<20 个交易日)→ None。"""
    assert evaluate_ma20_signal(close=1.85, ma20=None) is None


def test_both_none_returns_none():
    assert evaluate_ma20_signal(close=None, ma20=None) is None
