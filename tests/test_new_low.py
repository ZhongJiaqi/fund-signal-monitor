"""信号"事件检测"状态机。

激活态信号要兼顾三种推送时机:
- 首次激活('first'):全新跨入加仓区间
- 创新低('new_low'):持续激活期间累计净值刷新最低,捕捉越跌越买
- 持续激活('still_active'):激活态每日存在感汇报,避免用户忘记自己还在加仓窗口

状态机:
  prev_active  today_active  prev_lowest  today_close  →  event           new_lowest
  False/None   False/None    -            -            →  None            None
  False/None   True          -            X            →  'first'         X
  True         True          L            X (X ≥ L)    →  'still_active'  L
  True         True          L            X (X < L)    →  'new_low'       X
  True         False         -            -            →  None            None (reset)
  True         None (缺数)    L            -            →  None            L (保持)
  True         True          None         X            →  None            X (旧 state 迁移,无 lowest 不推)
"""

from monitor import detect_signal_event


def test_first_activation_returns_first_event():
    event, new_lowest = detect_signal_event(
        prev_active=False, today_active=True,
        today_close=1.93, prev_lowest=None,
    )
    assert event == 'first'
    assert new_lowest == 1.93


def test_first_activation_from_none_prev_returns_first():
    event, new_lowest = detect_signal_event(
        prev_active=None, today_active=True,
        today_close=1.93, prev_lowest=None,
    )
    assert event == 'first'
    assert new_lowest == 1.93


def test_continued_activation_with_new_low_returns_new_low():
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=True,
        today_close=1.90, prev_lowest=1.93,
    )
    assert event == 'new_low'
    assert new_lowest == 1.90


def test_continued_activation_without_new_low_returns_still_active():
    """持续激活但未创新低 → 'still_active'(每日存在感推送)"""
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=True,
        today_close=1.95, prev_lowest=1.93,
    )
    assert event == 'still_active'
    assert new_lowest == 1.93


def test_continued_activation_tied_with_previous_low_returns_still_active():
    """收盘正好等于历史最低 → 不算新低,但属于持续激活"""
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=True,
        today_close=1.93, prev_lowest=1.93,
    )
    assert event == 'still_active'
    assert new_lowest == 1.93


def test_deactivation_resets_lowest():
    """信号由激活变未激活 → 重置 lowest,下次再激活算 first"""
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=False,
        today_close=2.00, prev_lowest=1.93,
    )
    assert event is None
    assert new_lowest is None


def test_never_activated_returns_none():
    event, new_lowest = detect_signal_event(
        prev_active=False, today_active=False,
        today_close=2.00, prev_lowest=None,
    )
    assert event is None
    assert new_lowest is None


def test_legacy_state_no_lowest_records_close_but_no_event():
    """旧 state.json 没 prev_lowest 字段但信号已激活 → 视为补记录,不推 still_active 也不推 new_low

    迁移当天保持安静,下一次跑就有 lowest 了。"""
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=True,
        today_close=1.90, prev_lowest=None,
    )
    assert event is None
    assert new_lowest == 1.90


def test_today_data_missing_keeps_previous_lowest():
    """今天数据未取到(today_active=None)→ 保持 prev_lowest,不推"""
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=None,
        today_close=None, prev_lowest=1.93,
    )
    assert event is None
    assert new_lowest == 1.93


def test_today_close_missing_but_active_keeps_previous():
    """信号判断为 True 但 close 缺失(异常情况)→ 保守不推,保留 prev"""
    event, new_lowest = detect_signal_event(
        prev_active=True, today_active=True,
        today_close=None, prev_lowest=1.93,
    )
    assert event is None
    assert new_lowest == 1.93
