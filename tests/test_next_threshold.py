"""下一档加仓信号定位(2026-05-28 重编号:信号一 = MA250,从浅到深)。

顺序:signal_1 (MA250) → signal_2 (MA120 × 0.94) → signal_3 (MA120 × 0.88)。
都激活返回 None。MA 数据缺失返回 None。
"""

from monitor import next_threshold


def test_nothing_active_returns_signal_one_threshold():
    """未激活任何信号 → 下一档是信号一(跌破 MA250)"""
    label, price = next_threshold(
        close=1.2207, ma120=1.2109, ma250=1.1638,
        signals={'signal_1': False, 'signal_2': False, 'signal_3': False},
    )
    assert label == '信号一'
    assert abs(price - 1.1638) < 1e-9


def test_signal_one_active_returns_signal_two_threshold():
    """信号一激活(MA250),信号二未激活 → 下一档是信号二(MA120 × 0.94)"""
    label, price = next_threshold(
        close=1.9304, ma120=1.9598, ma250=1.9649,
        signals={'signal_1': True, 'signal_2': False, 'signal_3': False},
    )
    assert label == '信号二'
    assert abs(price - 1.9598 * 0.94) < 1e-9


def test_signal_two_active_returns_signal_three_threshold():
    """信号一+二激活,信号三未激活 → 下一档是信号三(MA120 × 0.88)"""
    label, price = next_threshold(
        close=1.8000, ma120=1.9598, ma250=1.9649,
        signals={'signal_1': True, 'signal_2': True, 'signal_3': False},
    )
    assert label == '信号三'
    assert abs(price - 1.9598 * 0.88) < 1e-9


def test_all_active_returns_none():
    """所有信号都激活 → 无下一档"""
    assert next_threshold(
        close=1.5000, ma120=1.9598, ma250=1.9649,
        signals={'signal_1': True, 'signal_2': True, 'signal_3': True},
    ) is None


def test_ma250_missing_when_signal_one_inactive():
    """信号一未激活 + ma250 缺失 → None"""
    assert next_threshold(
        close=1.2207, ma120=1.2109, ma250=None,
        signals={'signal_1': False, 'signal_2': False, 'signal_3': False},
    ) is None


def test_ma120_missing_when_signal_one_active():
    """信号一激活,需要 ma120 算下一档但缺失 → None"""
    assert next_threshold(
        close=1.9304, ma120=None, ma250=1.9649,
        signals={'signal_1': True, 'signal_2': False, 'signal_3': False},
    ) is None
