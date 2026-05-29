"""信号激活持续天数计算 — 按交易日数,不计周末/节假日。

激活当天 = 第 1 天。
"""

from datetime import date

from monitor import compute_active_days


def _td(*days: tuple[int, int, int]) -> set:
    """语法糖:把 (Y,M,D) 元组列表转成 date 集合。"""
    return {date(*d) for d in days}


def test_same_day_activation_returns_one():
    cal = _td((2026, 5, 22))
    assert compute_active_days('2026-05-22', date(2026, 5, 22), cal) == 1


def test_eight_natural_days_with_weekend_returns_seven_trading_days():
    """5/14(周四)激活,5/22(周五)是第 7 个交易日。

    自然日 9,但 5/16/17 周末跳过,实际交易日:14,15,18,19,20,21,22 = 7。
    """
    cal = _td(
        (2026, 5, 14), (2026, 5, 15),
        (2026, 5, 18), (2026, 5, 19), (2026, 5, 20), (2026, 5, 21), (2026, 5, 22),
    )
    assert compute_active_days('2026-05-14', date(2026, 5, 22), cal) == 7


def test_across_month_boundary_with_weekend():
    """4/28(周二)激活到 5/3(周日)。

    交易日:4/28, 4/29, 4/30, 5/2(周六)、5/3(周日)非交易 → 共 3 个交易日。
    用真实月历:4/28 周二,4/29 周三,4/30 周四,5/1 周五(非节假日仍交易),5/2 周六,5/3 周日。
    这里测试简化:只放 4/28/29/30 进交易日历。
    """
    cal = _td((2026, 4, 28), (2026, 4, 29), (2026, 4, 30))
    assert compute_active_days('2026-04-28', date(2026, 5, 3), cal) == 3


def test_today_not_in_calendar_still_counts_past_trading_days():
    """today 是非交易日(如周末)也能算 — 数到 today 之前的最后一个交易日为止。"""
    cal = _td((2026, 5, 21), (2026, 5, 22))  # 5/23 周六不在
    # 5/22 激活,5/23 是周六 → 历史只有 5/22 一个交易日
    assert compute_active_days('2026-05-22', date(2026, 5, 23), cal) == 1


def test_empty_calendar_returns_zero():
    """交易日历空(取数失败) → 返回 0,UI 显示无意义但不崩。"""
    assert compute_active_days('2026-05-14', date(2026, 5, 22), set()) == 0


def test_activated_after_today_returns_zero():
    """激活日晚于 today(数据异常)→ 返回 0,不返回负数。"""
    cal = _td((2026, 5, 14), (2026, 5, 15))
    assert compute_active_days('2026-05-20', date(2026, 5, 14), cal) == 0
